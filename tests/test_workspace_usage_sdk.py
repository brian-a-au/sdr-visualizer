"""Credential-free matching boundary; all projects are synthetic."""

import pytest

from sdr_visualizer.usage.sdk_worker import match_projects


def project(component="variables/evar1", *, platform="cja", project_id="p1"):
    return {
        "id": project_id,
        "name": "Synthetic project",
        "type": "project",
        "owner": {"name": "PRIVATE OWNER"},
        "definition": {
            "workspaces": [
                {
                    "id": "workspace",
                    "panels": [
                        {
                            "id": "panel",
                            "rsid": "other-context",
                            "subPanels": [
                                {
                                    "reportlet": {
                                        "type": "FreeformReportlet",
                                        "freeformTable": {
                                            "dimension": {"id": component},
                                            "staticRows": [],
                                        },
                                        "columnTree": {"nodes": []},
                                    }
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }


@pytest.mark.parametrize("platform", ["aa", "cja"])
def test_real_sdk_positive_and_empty(platform):
    result = match_projects(
        platform,
        [project()],
        [{"type": "dimension", "id": "variables/evar1"}, {"type": "dimension", "id": "missing"}],
        "2026-09-12T12:00:00Z",
    )
    assert len(result.results) == 2
    assert result.results[1]["projects"] == [{"id": "p1", "name": "Synthetic project"}]
    assert result.results[0]["projects"] == []
    assert all(
        r["status"] == "partial" and r["match_basis"] == "unverified_lookup" for r in result.results
    )
    assert "PRIVATE OWNER" not in str(result)


def test_bad_project_does_not_erase_positive():
    result = match_projects(
        "cja",
        [project(), {"id": "broken", "name": "Broken"}],
        [{"type": "dimension", "id": "variables/evar1"}],
        None,
    )
    assert result.results[0]["projects"][0]["id"] == "p1"
    assert any("excluded" in limit for limit in result.limitations)


@pytest.mark.parametrize("platform", ["aa", "cja"])
def test_actual_helper_safe_options_and_no_network_or_credentials(monkeypatch, platform):
    import importlib
    import os
    import socket

    import requests

    from sdr_visualizer.usage import sdk_worker
    from sdr_visualizer.usage.normalize import sanitize_projects

    # Register the originals with monkeypatch so child-only global guards are restored.
    monkeypatch.setattr(socket, "socket", socket.socket)
    monkeypatch.setattr(socket, "create_connection", socket.create_connection)
    monkeypatch.setattr(requests.sessions.Session, "request", requests.sessions.Session.request)
    for key in ("ORG_ID", "CLIENT_ID", "SECRET", "SCOPES"):
        monkeypatch.setenv(key, "SECRET CANARY")
    sdk = importlib.import_module("cjapy" if platform == "cja" else "aanalytics2")
    cls = sdk.CJA if platform == "cja" else sdk.Analytics
    original = cls.findComponentsUsage
    calls = []

    def guarded(client, **kwargs):
        assert not any(key in os.environ for key in ("ORG_ID", "CLIENT_ID", "SECRET", "SCOPES"))
        assert kwargs["recursive"] is kwargs["regexUsed"] is kwargs["resetProjectDetails"] is False
        assert kwargs["calculatedMetrics"] == []
        assert kwargs["filters" if platform == "cja" else "segments"] == []
        assert kwargs["dvIdSuffix" if platform == "cja" else "rsidSuffix"] is False
        assert all(not p.ownerName and not p.ownerEmail for p in kwargs["projectDetails"])
        with pytest.raises(sdk_worker.NetworkDenied):
            requests.get("https://example.invalid")
        with pytest.raises(sdk_worker.NetworkDenied):
            socket.create_connection(("example.invalid", 443))
        with pytest.raises(sdk_worker.NetworkDenied):
            client.connector.getData("https://example.invalid")
        calls.append(kwargs)
        return original(client, **kwargs)

    monkeypatch.setattr(cls, "findComponentsUsage", guarded)
    malformed = project(project_id="malformed")
    malformed["definition"]["workspaces"] = []
    mobile = project(project_id="mobile")
    mobile["definition"]["device"] = "cell"
    projects, _ = sanitize_projects(platform, [project(), malformed, mobile])
    messages = []
    sdk_worker._run_matching(
        {
            "platform": platform,
            "projects": projects,
            "components": [{"type": "dimension", "id": "variables/evar1"}],
            "checked_at": None,
        },
        messages.append,
    )
    assert calls
    assert messages[-1] == {"kind": "done"}
    assert messages[-2]["value"]["projects"]


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        [1],
        [{"type": [], "id": "x"}],
        [{"type": "dimension", "id": ""}],
        [{"type": "dimension", "id": "x"}] * 2,
        [{"type": "derived_field", "id": "x"}],
        [{"type": "dimension", "id": "x"}] * 2001,
    ],
)
def test_invalid_components_are_rejected_before_worker(bad):
    from sdr_visualizer.core.exceptions import InvalidSnapshotError

    with pytest.raises(InvalidSnapshotError):
        match_projects("aa", [], bad, None)


@pytest.mark.parametrize(
    "bad",
    [
        float("nan"),
        {1: "non-string key"},
        {"x": object()},
        {"x": "\ud800"},
        {"x": "x" * (2 * 1024 * 1024 + 1)},
    ],
)
def test_bounded_json_rejects_hostile_scalars(bad):
    from sdr_visualizer.core.exceptions import InvalidSnapshotError
    from sdr_visualizer.usage.normalize import bounded_json

    with pytest.raises(InvalidSnapshotError):
        bounded_json(bad)


def test_bounded_json_byte_depth_cycle_and_project_limits():
    from sdr_visualizer.core.exceptions import InvalidSnapshotError
    from sdr_visualizer.usage.normalize import bounded_json, sanitize_projects

    with pytest.raises(InvalidSnapshotError):
        bounded_json({"x": "abc"}, 1)
    deep = []
    for _ in range(101):
        deep = [deep]
    with pytest.raises(InvalidSnapshotError):
        bounded_json(deep)
    for platform, projects in [("other", []), ("aa", {}), ("aa", [project()] * 201)]:
        with pytest.raises(InvalidSnapshotError):
            sanitize_projects(platform, projects)
    conflict = project()
    conflict["name"] = "Conflicting"
    with pytest.raises(InvalidSnapshotError):
        sanitize_projects("cja", [project(), conflict])
    malformed = [None, {"id": "p", "name": ""}, {"id": "\n", "name": "Hostile"}]
    assert sanitize_projects("cja", malformed)[0] == []


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"x": None},
        {"x": {"projects": {}}},
        {"x": {"projects": [None]}},
        {"x": {"projects": [{"P": "unknown"}]}},
        {"x": {"projects": [{"WRONG": "p1"}]}},
        {"x": {"projects": [{}] * 10001}},
    ],
)
def test_raw_sdk_shape_and_metadata_cannot_fabricate_evidence(raw):
    from sdr_visualizer.usage.normalize import normalize_findings

    with pytest.raises(ValueError):
        normalize_findings(raw, {"type": "dimension", "id": "x"}, {"p1": project()})


@pytest.mark.parametrize("timestamp,timeout", [(True, 30), ("x" * 65, 30), (None, 0), (None, 31)])
def test_invalid_worker_options(timestamp, timeout):
    from sdr_visualizer.core.exceptions import InvalidSnapshotError

    with pytest.raises(InvalidSnapshotError):
        match_projects("cja", [], [{"type": "dimension", "id": "x"}], timestamp, timeout=timeout)


def test_deadline_kills_worker_and_does_not_invent_completed_lookup():
    result = match_projects(
        "cja", [project()], [{"type": "dimension", "id": "x"}], None, timeout=0.000001
    )
    assert result.results == []
    assert result.limitations


def _protocol(messages, monkeypatch, *, cap=None, raw=None):
    import json
    import subprocess
    import sys

    from sdr_visualizer.usage import sdk_worker

    if cap is not None:
        monkeypatch.setattr(sdk_worker, "MAX_IPC_BYTES", cap)
    encoded = raw if raw is not None else b"".join(json.dumps(m).encode() + b"\n" for m in messages)
    with subprocess.Popen(
        [sys.executable, "-c", "import sys;sys.stdout.buffer.write(" + repr(encoded) + ")"],
        stdout=subprocess.PIPE,
        start_new_session=True,
    ) as process:
        try:
            return sdk_worker._receive(
                process,
                [{"type": "dimension", "id": "a"}, {"type": "dimension", "id": "b"}],
                None,
                {"p1": project()},
                2,
            )
        finally:
            sdk_worker._stop(process)


def _completed():
    from sdr_visualizer.usage.normalize import candidate_record

    component = {"type": "dimension", "id": "a"}
    return [
        {"kind": "started", "component": component},
        {
            "kind": "result",
            "value": candidate_record(component, None, [{"id": "p1", "name": "Synthetic project"}]),
        },
    ]


@pytest.mark.parametrize(
    "tail",
    [
        {"kind": "started", "component": {"type": "dimension", "id": "WRONG"}},
        {"kind": "result", "value": {}},
        {"kind": "done"},
        {"kind": "unknown"},
        {"kind": "limitation", "value": "SECRET"},
    ],
)
def test_malformed_protocol_retains_prior_positive(monkeypatch, tail):
    result = _protocol(_completed() + [tail], monkeypatch)
    assert result.results[0]["projects"]
    assert result.results[1]["failure"] == "collection_error"
    assert result.limitations


@pytest.mark.parametrize("corruption", ["identity", "failure", "unknown_project", "duplicate"])
def test_reject_forged_worker_record_retaining_prior(monkeypatch, corruption):
    from sdr_visualizer.usage.normalize import candidate_record

    component = {"type": "dimension", "id": "b"}
    value = candidate_record(component, None, [{"id": "p1", "name": "Synthetic project"}])
    if corruption == "identity":
        value["component"] = {"type": "metric", "id": "b"}
    elif corruption == "failure":
        value["failure"] = "SECRET"
    elif corruption == "unknown_project":
        value["projects"] = [{"id": "unknown", "name": "Unknown"}]
    else:
        value["projects"] *= 2
    result = _protocol(
        _completed()
        + [{"kind": "started", "component": component}, {"kind": "result", "value": value}],
        monkeypatch,
    )
    assert result.results[0]["projects"]
    assert result.results[1]["failure"] == "collection_error"


def test_protocol_invalid_unicode_recursion_and_overrun(monkeypatch):
    for raw in [b"\xff\n", b"[" * 1100 + b"]" * 1100 + b"\n"]:
        assert _protocol([], monkeypatch, raw=raw).limitations
    assert _protocol([], monkeypatch, cap=100, raw=b"x" * 101).limitations


def test_protocol_repeated_limitation_and_in_progress_failure(monkeypatch):
    limitation = {
        "kind": "limitation",
        "value": "Malformed or unsupported projects were excluded from SDK matching",
    }
    result = _protocol(
        [limitation, limitation]
        + _completed()
        + [{"kind": "started", "component": {"type": "dimension", "id": "b"}}],
        monkeypatch,
    )
    assert len(result.limitations) == 2
    assert result.results[1]["failure"] == "collection_error"


@pytest.mark.parametrize("failure", ["blocked", "regex"])
def test_child_adapter_exception_is_sanitized_and_stops(monkeypatch, failure):
    import socket
    from types import SimpleNamespace

    import requests

    from sdr_visualizer.usage import sdk_worker

    monkeypatch.setattr(socket, "socket", socket.socket)
    monkeypatch.setattr(socket, "create_connection", socket.create_connection)
    monkeypatch.setattr(requests.sessions.Session, "request", requests.sessions.Session.request)

    def find(*args):
        if failure == "blocked":
            raise sdk_worker.NetworkDenied("SECRET")
        raise ValueError("SECRET")

    monkeypatch.setattr(
        sdk_worker.importlib,
        "import_module",
        lambda name: SimpleNamespace(prepare=lambda projects, deny: (None, [1], False), find=find),
    )
    messages = []
    sdk_worker._run_matching(
        {
            "platform": "aa",
            "projects": [],
            "checked_at": None,
            "components": [{"type": "dimension", "id": "a"}, {"type": "dimension", "id": "b"}],
        },
        messages.append,
    )
    assert len(messages) == 2
    assert messages[-1]["value"]["failure"] == (
        "unsupported" if failure == "blocked" else "collection_error"
    )
    assert "SECRET" not in str(messages)


@pytest.mark.parametrize("mode", ["okay", "oversized_input", "oversized_output", "invalid"])
def test_child_ipc_bounded_and_suppresses_incidental_output(monkeypatch, mode):
    import io
    import json
    import sys

    from sdr_visualizer.usage import sdk_worker

    source = b"{}" if mode != "invalid" else b"invalid"
    if mode == "oversized_input":
        source = b"x" * 101
    incoming = io.TextIOWrapper(io.BytesIO(source))
    outgoing = io.TextIOWrapper(io.BytesIO(), write_through=True)
    monkeypatch.setattr(sys, "stdin", incoming)
    monkeypatch.setattr(sys, "stdout", outgoing)
    monkeypatch.setattr(sdk_worker, "MAX_IPC_BYTES", 100)
    monkeypatch.setattr(sdk_worker.logging, "disable", lambda level: None)

    def run(request, emit):
        print("SECRET")
        print("SECRET", file=sys.stderr)
        emit(
            {"kind": "done", "value": "x" * 101} if mode == "oversized_output" else {"kind": "done"}
        )

    monkeypatch.setattr(sdk_worker, "_run_matching", run)
    sdk_worker._child()
    data = outgoing.buffer.getvalue()
    assert "SECRET" not in data.decode()
    if mode == "okay":
        assert json.loads(data) == {"kind": "done"}
    else:
        assert data == b""


def test_empty_project_set_still_yields_partial_candidate(monkeypatch):
    import socket
    from types import SimpleNamespace

    import requests

    from sdr_visualizer.usage import sdk_worker

    monkeypatch.setattr(socket, "socket", socket.socket)
    monkeypatch.setattr(socket, "create_connection", socket.create_connection)
    monkeypatch.setattr(requests.sessions.Session, "request", requests.sessions.Session.request)
    monkeypatch.setattr(
        sdk_worker.importlib,
        "import_module",
        lambda name: SimpleNamespace(prepare=lambda projects, deny: (None, [], False)),
    )
    messages = []
    sdk_worker._run_matching(
        {
            "platform": "cja",
            "projects": [],
            "checked_at": None,
            "components": [{"type": "dimension", "id": "a"}],
        },
        messages.append,
    )
    assert messages[1]["value"]["status"] == "partial"
    assert not messages[1]["value"]["projects"]


def test_stop_handles_process_exiting_between_poll_and_signal(monkeypatch):
    from types import SimpleNamespace

    from sdr_visualizer.usage import sdk_worker

    def exited(*args):
        raise ProcessLookupError

    waited = []
    monkeypatch.setattr(sdk_worker.os, "killpg", exited)
    sdk_worker._stop(
        SimpleNamespace(poll=lambda: None, pid=123, wait=lambda timeout: waited.append(timeout))
    )
    assert waited == [2]


def test_stalled_protocol_obeys_whole_worker_deadline():
    import subprocess
    import sys

    from sdr_visualizer.usage import sdk_worker

    with subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        stdout=subprocess.PIPE,
        start_new_session=True,
    ) as process:
        try:
            result = sdk_worker._receive(
                process, [{"type": "dimension", "id": "a"}], None, {}, 0.01
            )
            assert result.results == []
            assert result.limitations
        finally:
            sdk_worker._stop(process)
