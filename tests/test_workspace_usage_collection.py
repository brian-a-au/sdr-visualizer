"""Synthetic, offline tests for independent Workspace collection providers."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.visualizer import build_implementation
from sdr_visualizer.usage import collector
from sdr_visualizer.usage.collector import collect_api
from sdr_visualizer.usage.transport import BoundedTransport, Receipt, TransportError


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    for key in ("ORG_ID", "CLIENT_ID", "SECRET", "SCOPES"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("sdr_visualizer.usage.collector._now", lambda: "2026-09-12T12:00:00Z")


class FakeTransport:
    request_attempts = 0
    transferred_bytes = 0

    def route_url(self, kind, identifier=None):
        return (kind, identifier)

    def get_json(self, url, headers=None, params=None):
        self.request_attempts += 1
        if url[0] == "dataview":
            data = {"id": "dv"}
        elif url[0] == "discovery":
            data = {"imsOrgs": [{"imsOrgId": "org", "companies": [{"globalCompanyId": "co"}]}]}
        elif url[0] == "suite":
            data = {"rsid": "dv", "parentRsid": "not-this-suite"}
        else:
            data = {
                "content": [],
                "number": 0,
                "lastPage": True,
                "totalPages": 0,
                "totalElements": 0,
            }
        return Receipt(200, data, "2026-09-12T12:00:00Z")


@pytest.mark.parametrize("platform", ["aa", "cja"])
def test_empty_collection_is_completed_retrieval(platform):
    result = collect_api(
        FakeTransport(),
        {},
        platform=platform,
        instance_id="dv",
        org_id="org",
        company_id="co" if platform == "aa" else None,
    )
    assert result["retrieval"]["status"] == "complete"
    assert result["retrieval"]["projects_discovered"] == 0
    assert result["projects"] == []


def implementation(platform="cja"):
    raw = json.loads(
        (Path(__file__).parent / f"fixtures/{platform}_snapshot_clean.json").read_text()
    )
    return build_implementation(raw, source="synthetic")


def synthetic_project(identity="p", component="variables/evar1"):
    return {
        "id": identity,
        "name": "Synthetic project " + identity,
        "modified": "revision-1",
        "type": "project",
        "owner": {"name": "PRIVATE OWNER"},
        "definition": {
            "workspaces": [
                {
                    "id": "w",
                    "panels": [
                        {
                            "id": "panel",
                            "rsid": "unrelated",
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


def metadata(project):
    return {k: project[k] for k in ("id", "name", "modified")}


def page(projects, number=0, total=None):
    total = len(projects) if total is None else total
    pages = (total + 49) // 50
    return {
        "content": [metadata(p) for p in projects],
        "number": number,
        "lastPage": number >= pages - 1,
        "totalPages": pages,
        "totalElements": total,
    }


class Scripted(FakeTransport):
    def __init__(self, pages=None, details=None, identity=None):
        self.pages = pages or [page([])]
        self.details = details or {}
        self.identity = identity or {}
        self.calls = []
        self.request_attempts = 0

    def get_json(self, url, headers=None, params=None):
        self.calls.append((url, params))
        kind, key = url
        if kind in self.identity:
            value = self.identity[kind]
        elif kind == "projects":
            value = self.pages[params["page"]]
        elif kind == "project":
            value = self.details[key]
        else:
            return super().get_json(url, headers=headers, params=params)
        self.request_attempts += 1
        if isinstance(value, Exception):
            raise value
        return Receipt(200, value, "2026-09-12T12:00:00Z")


def run(transport, platform="cja", **kwargs):
    return collector.collect_api(
        transport,
        {},
        platform=platform,
        instance_id="dv",
        org_id="org",
        company_id="co" if platform == "aa" else None,
        **kwargs,
    )


@pytest.mark.parametrize("platform", ["cja", "aa"])
@pytest.mark.parametrize("scope", ["all", "owned", "shared"])
def test_scopes_and_positive_real_sdk(monkeypatch, platform, scope):
    impl = implementation(platform)
    component = {"type": "dimension", "id": impl.dimensions[0].id}
    p = synthetic_project(component=component["id"])
    transport = Scripted([page([p])], {"p": p})

    # Exercise guarded HTTP response decoding, followed by the real isolated helper.
    def response(session, method, url, **kwargs):
        from urllib.parse import unquote

        path = unquote(url)
        kind = "project" if "/projects/" in path else "projects"
        if "/dataviews/" in path:
            value = {"id": impl.instance_id}
        elif "/discovery/" in path:
            value = {"imsOrgs": [{"imsOrgId": "org", "companies": [{"globalCompanyId": "co"}]}]}
        elif "/suites/" in path:
            value = {"rsid": impl.instance_id}
        else:
            value = transport.get_json(
                (kind, path.rsplit("/", 1)[-1]), params=kwargs.get("params")
            ).data
        raw = json.dumps(value).encode()
        return SimpleNamespace(
            status_code=200, headers={}, iter_content=lambda **_: [raw], close=lambda: None
        )

    import requests

    monkeypatch.setattr(requests.Session, "request", response)

    def acquire(request):
        with BoundedTransport(platform, "co" if platform == "aa" else None) as guarded:
            return collector.collect_api(
                guarded,
                {"x-proxy-global-company-id": "co"},
                platform=platform,
                instance_id=impl.instance_id,
                org_id="org",
                company_id="co" if platform == "aa" else None,
                scope=scope,
            )

    monkeypatch.setattr(collector, "_acquire", acquire)
    bound = collector.collect_workspace_usage(
        impl,
        organization_context="org",
        company_context="co" if platform == "aa" else None,
        components=[component],
        scope=scope,
    )
    evidence = bound.evidence
    assert evidence["results"][0]["projects"] == [{"id": "p", "name": p["name"]}]
    assert evidence["results"][0]["match_basis"] == "unverified_lookup"
    assert evidence["collection"]["status"] == "partial"
    assert "PRIVATE OWNER" not in str(evidence)
    assert "definition" not in str(evidence)
    params = next(params for (kind, _), params in transport.calls if kind == "projects")
    assert params.get("includeType") == (None if scope == "owned" else scope)


@pytest.mark.parametrize("platform", ["aa", "cja"])
def test_explicit_projects_skip_index_and_preserve_positive_after_failure(platform):
    p = synthetic_project()
    result = run(
        Scripted(details={"p": p, "q": TransportError(failure="permission_denied")}),
        platform,
        project_ids=["q", "p"],
    )
    assert result["retrieval"]["projects_fetched"] == result["retrieval"]["projects_failed"] == 1
    assert result["projects"][0]["id"] == "p"
    assert result["retrieval"]["pages_fetched"] == 0
    assert result["failure"] == "permission_denied"


@pytest.mark.parametrize("problem", [TransportError(failure="permission_denied"), {"content": []}])
def test_later_page_error_fetches_previous_ids(problem):
    ps = [synthetic_project(f"p{i:02}") for i in range(50)]
    result = run(Scripted([page(ps, total=51), problem], {p["id"]: p for p in ps}))
    assert len(result["projects"]) == 50
    assert result["retrieval"]["status"] == "partial"
    assert result["retrieval"]["pages_fetched"] == 1


def test_complete_two_pages_and_timing():
    ps = [synthetic_project(f"p{i:02}") for i in range(51)]
    result = run(
        Scripted(
            [page(ps[:50], total=51), page(ps[50:], number=1, total=51)], {p["id"]: p for p in ps}
        )
    )
    assert result["retrieval"]["status"] == "complete"
    assert result["retrieval"]["pages_fetched"] == 2
    assert result["checked_at"] == "2026-09-12T12:00:00Z"


@pytest.mark.parametrize("change", ["revision", "name", "id", "type", "definition"])
def test_bad_detail_retains_other_projects(change):
    ps = [synthetic_project("p"), synthetic_project("q")]
    bad = deepcopy(ps[1])
    if change == "revision":
        bad["modified"] = "changed"
    elif change in ("name", "id", "type"):
        bad[change] = "changed"
    else:
        bad.pop("definition")
    result = run(Scripted([page(ps)], {"p": ps[0], "q": bad}))
    assert [p["id"] for p in result["projects"]] == ["p"]
    assert result["retrieval"]["status"] == (
        "complete" if change in ("type", "definition") else "partial"
    )


def test_malformed_or_conflicting_index_quarantines_only_bad_project():
    p, q = synthetic_project("p"), synthetic_project("q")
    malformed = page([p, q])
    malformed["content"][1].pop("modified")
    result = run(Scripted([malformed], {"p": p}))
    assert [p["id"] for p in result["projects"]] == ["p"]
    conflict = page([p, q, q])
    conflict["content"][2]["name"] = "conflict"
    result = run(Scripted([conflict], {"p": p}))
    assert [p["id"] for p in result["projects"]] == ["p"]


@pytest.mark.parametrize("platform", ["aa", "cja"])
def test_identity_access_failure_records_failure(platform):
    result = run(
        Scripted(
            identity={
                "discovery" if platform == "aa" else "dataview": TransportError(
                    failure="permission_denied"
                )
            }
        ),
        platform,
    )
    assert result["retrieval"]["status"] == "failed"
    assert result["checked_at"] is None


@pytest.mark.parametrize(
    "kind,data",
    [
        ("dataview", {"id": "wrong"}),
        ("suite", {"rsid": "parent"}),
        ("discovery", {"imsOrgs": [{"imsOrgId": "other", "companies": []}]}),
        (
            "discovery",
            {"imsOrgs": [{"imsOrgId": "org", "companies": [{"globalCompanyId": "wrong"}]}]},
        ),
    ],
)
def test_identity_contradiction_is_input_error(kind, data):
    with pytest.raises(InvalidSnapshotError):
        run(Scripted(identity={kind: data}), "cja" if kind == "dataview" else "aa")


@pytest.mark.parametrize(
    "kind,data",
    [
        ("dataview", []),
        ("suite", {}),
        ("discovery", []),
        ("discovery", {"imsOrgs": [None]}),
        ("discovery", {"imsOrgs": [{"imsOrgId": "org", "companies": [None]}]}),
    ],
)
def test_malformed_identity_is_failed_collection(kind, data):
    result = run(Scripted(identity={kind: data}), "cja" if kind == "dataview" else "aa")
    assert result["failure"] == "collection_error"


def test_aa_selects_exact_org_and_virtual_suite():
    data = {
        "imsOrgs": [
            {"imsOrgId": "other", "companies": [{"globalCompanyId": "co"}]},
            {"imsOrgId": "org", "companies": [{"globalCompanyId": "co"}]},
        ]
    }
    assert run(Scripted(identity={"discovery": data}), "aa")["retrieval"]["status"] == "complete"


@pytest.mark.parametrize(
    "overrides",
    [
        {"organization_context": ""},
        {"company_context": "co"},
        {"scope": "bad"},
        {"project_ids": []},
        {"project_ids": ["p", "p"]},
        {"project_ids": [1]},
        {"project_ids": ["p"], "scope": "owned"},
        {"components": []},
        {"components": [{"type": "metric", "id": "unknown"}]},
    ],
)
def test_preflight_rejects_before_acquisition(overrides):
    args = {"organization_context": "org", **overrides}
    with pytest.raises(InvalidSnapshotError):
        collector.preflight_collection(implementation(), **args)


def test_preflight_sdk_versions_and_aa_context(monkeypatch):
    with pytest.raises(InvalidSnapshotError):
        collector.preflight_collection(implementation("aa"), organization_context="org")
    monkeypatch.setattr(collector.importlib.metadata, "version", lambda _: "wrong")
    with pytest.raises(InvalidSnapshotError, match="pinned"):
        collector.preflight_collection(implementation(), organization_context="org")

    def missing(_):
        raise collector.importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(collector.importlib.metadata, "version", missing)
    with pytest.raises(InvalidSnapshotError, match="Install"):
        collector.preflight_collection(implementation(), organization_context="org")


def test_empty_and_failed_final_contract(monkeypatch):
    impl = implementation()
    for transport, expected in [
        (FakeTransport(), "partial"),
        (Scripted(identity={"dataview": TransportError(failure="permission_denied")}), "failed"),
    ]:
        monkeypatch.setattr(collector, "_acquire", lambda _, t=transport: run(t))
        bound = collector.collect_workspace_usage(impl, organization_context="org")
        assert bound.evidence["collection"]["status"] == expected
        assert all(not r["projects"] for r in bound.evidence["results"])


def test_clock_reversal_is_explicit(monkeypatch):
    times = iter(["2026-09-12T12:01:00Z"] + ["2026-09-12T12:00:00Z"] * 10)
    monkeypatch.setattr(collector, "_now", lambda: next(times))
    result = run(FakeTransport())
    assert result["retrieval"]["started_at"] is result["retrieval"]["finished_at"] is None
    assert collector.CLOCK_REVERSAL_LIMITATION in result["retrieval"]["limitations"]


def test_detail_and_source_caps_retain_prior_projects(monkeypatch):
    ps = [synthetic_project(str(i)) for i in range(201)]
    result = run(Scripted(details={p["id"]: p for p in ps}), project_ids=[p["id"] for p in ps])
    assert len(result["projects"]) == 200
    assert result["retrieval"]["status"] == "partial"
    monkeypatch.setattr(collector, "MAX_IPC_BYTES", 66000)
    result = run(Scripted(details={p["id"]: p for p in ps}), project_ids=[p["id"] for p in ps[:3]])
    assert len(result["projects"]) < 3


def request(platform="cja", project_ids=None):
    return {
        "platform": platform,
        "instance_id": "dv",
        "org_id": "org",
        "company_id": "co" if platform == "aa" else None,
        "config_path": None,
        "scope": "all",
        "project_ids": project_ids,
    }


def protocol(messages, *, timeout=2, stall=False, req=None):
    import subprocess
    import sys

    code = (
        "import sys,time;sys.stdout.write("
        + repr("\n".join(json.dumps(m) for m in messages) + "\n")
        + ");sys.stdout.flush()"
    )
    if stall:
        code += ";time.sleep(10)"
    with subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, start_new_session=True, env={}
    ) as process:
        try:
            return collector._receive(process, req or request(), timeout=timeout)
        finally:
            collector._stop(process)


@pytest.mark.parametrize("exit_code", [0, -9])
def test_cleanup_signal_permission_race_requires_reaped_child(monkeypatch, exit_code):
    waits = []

    def denied(pid, signal):
        raise PermissionError("process group is exiting")

    def wait(*, timeout):
        waits.append(timeout)
        return exit_code

    monkeypatch.setattr(collector.os, "killpg", denied)
    process = SimpleNamespace(pid=123, poll=lambda: None, wait=wait)
    collector._stop(process)
    assert waits == [2]


def test_cleanup_signal_permission_failure_preserved_for_running_child(monkeypatch):
    import subprocess

    error = PermissionError("signal denied")

    def denied(pid, signal):
        raise error

    def wait(*, timeout):
        assert timeout == 2
        raise subprocess.TimeoutExpired("synthetic child", timeout)

    monkeypatch.setattr(collector.os, "killpg", denied)
    process = SimpleNamespace(pid=123, poll=lambda: None, wait=wait)
    with pytest.raises(PermissionError) as caught:
        collector._stop(process)
    assert caught.value is error


def retrieval(**kwargs):
    kwargs.setdefault(
        "request_attempts",
        sum(kwargs.get(k, 0) for k in ("pages_fetched", "projects_fetched", "projects_failed")),
    )
    return {**collector._initial("all", None, "2026-09-12T12:00:00Z"), **kwargs}


def clean_project():
    from sdr_visualizer.usage.normalize import sanitize_projects

    return sanitize_projects("cja", [synthetic_project()])[0][0]


def test_protocol_retains_projects_when_worker_stalls():
    state = retrieval(request_attempts=3, projects_discovered=1, projects_fetched=1)
    result = protocol(
        [
            {"kind": "progress", "retrieval": state},
            {"kind": "project", "project": clean_project(), "received_at": "2026-09-12T12:00:00Z"},
        ],
        timeout=0.2,
        stall=True,
    )
    assert len(result["projects"]) == 1
    assert result["retrieval"]["status"] == "partial"
    assert result["retrieval"]["request_attempts"] == 3


def test_protocol_success_and_input_error():
    state = retrieval(status="complete")
    result = protocol(
        [
            {
                "kind": "done",
                "retrieval": state,
                "checked_at": "2026-09-12T12:00:00Z",
                "failure": None,
            }
        ]
    )
    assert result["retrieval"]["status"] == "complete"
    with pytest.raises(InvalidSnapshotError):
        protocol([{"kind": "input_error"}])


@pytest.mark.parametrize(
    "message",
    [
        [],
        {"kind": "bad"},
        {"kind": "progress", "retrieval": {}},
        {"kind": "project", "project": {}, "received_at": None},
        {"kind": "project", "project": clean_project(), "received_at": "bad"},
        {"kind": "done", "retrieval": retrieval(), "checked_at": "bad", "failure": None},
        {"kind": "done", "retrieval": retrieval(), "checked_at": None, "failure": "secret"},
    ],
)
def test_malformed_protocol_is_failure_without_raw_strings(message):
    result = protocol([message])
    assert result["retrieval"]["status"] == "failed"
    assert "secret" not in str(result)


@pytest.mark.parametrize(
    "overrides",
    [
        {"request_attempts": -1},
        {"request_attempts": 257},
        {"pages_fetched": True},
        {"projects_failed": 1},
        {"include_type": "shared"},
        {"status": "bad"},
        {"limitations": "bad"},
        {"limitations": ["secret"]},
        {"started_at": "bad"},
    ],
)
def test_progress_rejects_untrusted_counters_and_strings(overrides):
    with pytest.raises(ValueError):
        collector._validate_progress(retrieval(**overrides), retrieval(), "all", None)


def test_protocol_bounds_clock_and_project_scope(monkeypatch):
    result = protocol(
        [{"kind": "project", "project": clean_project(), "received_at": "2026-09-12T12:00:00Z"}],
        req=request(project_ids=["other"]),
    )
    assert not result["projects"]
    p = {"kind": "project", "project": clean_project(), "received_at": "2026-09-12T12:00:00Z"}
    result = protocol([p, p])
    assert len(result["projects"]) == 1
    state = retrieval(started_at="2026-09-12T12:01:00Z")
    result = protocol([{"kind": "progress", "retrieval": state}])
    assert result["retrieval"]["started_at"] is None
    monkeypatch.setattr(collector, "MAX_IPC_BYTES", 2)
    assert protocol([{}])["retrieval"]["status"] == "failed"


def test_parser_limits_survive_protocol_and_final_matching(monkeypatch):
    limit = {"kind": "limitation", "value": collector.EXCLUDED_PROJECTS_LIMITATION}
    result = protocol([limit, limit])
    assert result["matching_limitations"] == [collector.EXCLUDED_PROJECTS_LIMITATION]
    acquired = run(Scripted(details={"p": synthetic_project()}), project_ids=["p"])
    from sdr_visualizer.usage.normalize import MatchResult

    monkeypatch.setattr(collector, "_acquire", lambda _: acquired)
    monkeypatch.setattr(collector, "match_projects", lambda *args: MatchResult([], []))
    bound = collector.collect_workspace_usage(
        implementation(), organization_context="org", project_ids=["p"]
    )
    assert collector.NO_RESULTS_LIMITATION in bound.evidence["collection"]["limitations"]


def test_real_child_missing_synthetic_config_cannot_reach_network(tmp_path):
    req = request()
    req["config_path"] = str(tmp_path / "nonexistent-synthetic-config.json")
    with pytest.raises(InvalidSnapshotError):
        collector._acquire(req)


def child(monkeypatch, *, failure=None, backwards=False):
    import contextlib
    import io

    output = io.BytesIO()
    monkeypatch.setattr(
        collector.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(request()).encode()))
    )
    monkeypatch.setattr(collector.sys, "stdout", SimpleNamespace(buffer=output))
    transport = Scripted()
    monkeypatch.setattr(
        collector, "BoundedTransport", lambda *args, **kwargs: contextlib.nullcontext(transport)
    )
    monkeypatch.setattr(collector.auth, "quiet_sdk", contextlib.nullcontext)
    monkeypatch.setattr(collector.auth, "resolve_credentials", lambda *args, **kwargs: object())

    def initialize(*args):
        if failure:
            raise failure
        return SimpleNamespace(header={})

    monkeypatch.setattr(collector.auth, "initialize_sdk", initialize)

    # Wrapper provides both guard context and transport counters used on auth failure.
    class Guard:
        request_attempts = 1

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def route_url(self, *args):
            return transport.route_url(*args)

        def get_json(self, *args, **kwargs):
            value = transport.get_json(*args, **kwargs)
            self.request_attempts = transport.request_attempts
            return value

    monkeypatch.setattr(collector, "BoundedTransport", lambda *args, **kwargs: Guard())
    if backwards:
        times = iter(["2026-09-12T12:01:00Z", "2026-09-12T12:00:00Z"])
        monkeypatch.setattr(collector, "_now", lambda: next(times))
    collector._child()
    return [json.loads(line) for line in output.getvalue().splitlines()]


@pytest.mark.parametrize(
    "failure,expected",
    [
        (None, None),
        (InvalidSnapshotError("secret"), "input_error"),
        (TransportError(failure="permission_denied"), "permission_denied"),
        (RuntimeError("secret"), "collection_error"),
    ],
)
def test_child_only_sanitized_success_or_failure_crosses_boundary(monkeypatch, failure, expected):
    messages = child(monkeypatch, failure=failure)
    assert "secret" not in str(messages)
    assert messages[-1]["kind"] == ("input_error" if expected == "input_error" else "done")
    if expected != "input_error":
        assert messages[-1]["failure"] == expected


def test_auth_failure_clock_reversal(monkeypatch):
    messages = child(monkeypatch, failure=RuntimeError(), backwards=True)
    assert messages[-1]["retrieval"]["started_at"] is None


def test_interrupt_stops_child_and_propagates(monkeypatch):
    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(collector, "_receive", interrupt)
    with pytest.raises(KeyboardInterrupt):
        collector._acquire(request())


@pytest.mark.parametrize(
    "data",
    [
        None,
        {"id": 1},
        {"id": "p"},
        {"id": "p", "name": "", "modified": "r"},
        {"id": "p", "name": "p", "modified": 1},
    ],
)
def test_invalid_project_metadata(data):
    with pytest.raises(TransportError):
        collector._metadata(data)


@pytest.mark.parametrize(
    "overrides",
    [
        {"content": None},
        {"number": True},
        {"lastPage": 1},
        {"totalPages": 5},
        {"totalElements": 10},
        {"number": 1},
    ],
)
def test_pagination_malformed_never_empty_success(overrides):
    with pytest.raises(TransportError):
        collector._page({**page([]), **overrides}, 0)


def test_changing_totals_and_repeated_pages_are_partial():
    ps = [synthetic_project(str(i)) for i in range(50)]
    for second in [page(ps, number=1, total=100), page(ps, number=1, total=101)]:
        result = run(Scripted([page(ps, total=100), second], {p["id"]: p for p in ps}))
        assert len(result["projects"]) == 50
        assert result["retrieval"]["status"] == "partial"


def test_budget_failure_does_not_invent_unattempted_detail_failures():
    class Exhausted(Scripted):
        def get_json(self, url, headers=None, params=None):
            if url[0] == "project":
                raise TransportError("Workspace request budget exhausted")
            return super().get_json(url, headers, params)

    result = run(Exhausted(), project_ids=["p", "q"])
    assert result["retrieval"]["projects_failed"] == 0


def test_all_parser_exclusions_are_not_completed_empty(monkeypatch):
    p = synthetic_project()
    p["type"] = "unsupported"
    acquired = run(Scripted(details={"p": p}), project_ids=["p"])
    assert acquired["retrieval"]["status"] == "complete"
    assert acquired["checked_at"] is None
    monkeypatch.setattr(collector, "_acquire", lambda _: acquired)
    bound = collector.collect_workspace_usage(
        implementation(), organization_context="org", project_ids=["p"]
    )
    assert bound.evidence["collection"]["status"] == "failed"
    assert bound.evidence["collection"]["failure"] == "unsupported"
    assert bound.evidence["results"] == []


def test_attempt_protocol_retains_inflight_request_on_deadline():
    result = protocol([{"kind": "attempt", "count": 1}], stall=True, timeout=0.1)
    assert result["retrieval"]["request_attempts"] == 1
    for count in (True, 2, 257):
        assert protocol([{"kind": "attempt", "count": count}])["retrieval"]["status"] == "failed"


def test_page_bound_and_unidentifiable_row():
    with pytest.raises(TransportError, match="page count"):
        collector._page({**page([]), "totalElements": 1, "totalPages": 1}, 0)
    malformed = {**page([synthetic_project()]), "content": [None]}
    result = run(Scripted([malformed]))
    assert result["retrieval"]["status"] == "failed"


def test_twenty_page_budget_emits_retained_project_and_parser_limits():
    ps = [synthetic_project(f"p{i:04}") for i in range(1000)]
    messages = []
    pages = [page(ps[i * 50 : (i + 1) * 50], number=i, total=1001) for i in range(20)]
    result = run(Scripted(pages, {p["id"]: p for p in ps}), emit=messages.append)
    assert result["retrieval"]["pages_fetched"] == 20
    assert result["retrieval"]["projects_fetched"] == 200
    assert sum(m["kind"] == "project" for m in messages) == 200
    for p in ps[:2]:
        p["type"] = "unsupported"
    messages.clear()
    run(
        Scripted(details={p["id"]: p for p in ps[:2]}),
        project_ids=[p["id"] for p in ps[:2]],
        emit=messages.append,
    )
    assert sum(m["kind"] == "limitation" for m in messages) == 1


def test_invalid_timestamp_types_in_protocol():
    with pytest.raises(ValueError):
        collector._validate_progress(retrieval(started_at=1), retrieval(), "all", None)
    assert (
        protocol([{"kind": "project", "project": clean_project(), "received_at": 1}])["retrieval"][
            "status"
        ]
        == "failed"
    )
    assert (
        protocol([{"kind": "done", "retrieval": retrieval(), "checked_at": 1, "failure": None}])[
            "retrieval"
        ]["status"]
        == "failed"
    )


def test_protocol_complete_positive_and_zero_timeout():
    p = {"kind": "project", "project": clean_project(), "received_at": "2026-09-12T12:00:00Z"}
    state = retrieval(status="complete", projects_discovered=1, projects_fetched=1)
    result = protocol(
        [p, {"kind": "done", "retrieval": state, "checked_at": p["received_at"], "failure": None}]
    )
    assert len(result["projects"]) == 1
    assert protocol([], timeout=0)["retrieval"]["status"] == "failed"


def test_final_clock_reversal_retains_project_after_timestamped_progress():
    stamp = "2026-09-12T12:00:00Z"
    project = clean_project()
    progress = retrieval(projects_discovered=1, projects_fetched=1)
    final = {
        **progress,
        "started_at": None,
        "finished_at": None,
        "limitations": [collector.CLOCK_REVERSAL_LIMITATION],
    }
    result = protocol(
        [
            {"kind": "progress", "retrieval": progress},
            {"kind": "project", "project": project, "received_at": stamp},
            {"kind": "done", "retrieval": final, "checked_at": stamp, "failure": None},
        ]
    )
    assert result["projects"] == [project]
    assert result["checked_at"] == stamp
    assert result["retrieval"] == final
    assert result["failure"] is None


def test_module_entry_point_without_credentials(monkeypatch):
    import io
    import runpy

    output = io.BytesIO()
    monkeypatch.setattr(
        collector.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(request()).encode()))
    )
    monkeypatch.setattr(collector.sys, "stdout", SimpleNamespace(buffer=output))
    # Environment quartet was removed by the autouse fixture: fails before authentication.
    with pytest.warns(RuntimeWarning, match="found in sys.modules"):
        runpy.run_module("sdr_visualizer.usage.collector", run_name="__main__")
    assert json.loads(output.getvalue()) == {"kind": "input_error"}


def test_progress_rejects_impossible_requests_and_explicit_pages():
    with pytest.raises(ValueError):
        collector._validate_progress(
            retrieval(pages_fetched=1, request_attempts=0), retrieval(), "all", None
        )
    previous = collector._initial("all", ["p"], "2026-09-12T12:00:00Z")
    with pytest.raises(ValueError):
        collector._validate_progress(
            {**previous, "pages_fetched": 1, "request_attempts": 1}, previous, "all", ["p"]
        )
    assert protocol([{"kind": "progress", "unknown": "secret"}])["retrieval"]["status"] == "failed"
