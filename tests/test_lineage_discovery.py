"""Saved/live acquisition contract for CJA lineage discovery."""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

import sdr_visualizer.input.lineage_discovery as lineage_discovery
from sdr_visualizer.core.lineage import LineageTopology
from sdr_visualizer.input.lineage_discovery import (
    LineageDiscoveryFailure,
    LineageDiscoveryFailureCode,
    acquire_live,
    acquire_saved,
)

FIXTURES = Path(__file__).parent / "fixtures"
CANARY = "LINEAGE_SECRET_CANARY_7f6f9b"


def _payload() -> dict:
    return json.loads((FIXTURES / "cja_lineage_shared.json").read_text(encoding="utf-8"))


def _enriched_payload() -> dict:
    return json.loads((FIXTURES / "cja_lineage_enriched.json").read_text(encoding="utf-8"))


def _fake_executable(
    directory: Path,
    *,
    payload: bytes | None = None,
    version: str = "cja_auto_sdr 3.11.8",
    exit_code: int = 0,
    stderr: bytes = b"",
    delay: float = 0,
) -> tuple[Path, Path]:
    executable = directory / "cja_auto_sdr"
    record = directory / "invocation.json"
    program = f"""#!{sys.executable}
import json
import os
import pathlib
import sys
import time

if sys.argv[1:] == [\"--version\"]:
    sys.stdout.buffer.write({version.encode()!r} + b\"\\n\")
    raise SystemExit(0)
pathlib.Path({str(record)!r}).write_text(json.dumps({{
    \"argv\": sys.argv[1:],
    \"env\": dict(os.environ),
}}), encoding=\"utf-8\")
time.sleep({delay!r})
sys.stdout.buffer.write({payload if payload is not None else json.dumps(_payload()).encode()!r})
sys.stderr.buffer.write({stderr!r})
raise SystemExit({exit_code})
"""
    executable.write_text(program, encoding="utf-8")
    executable.chmod(0o700)
    return executable, record


def _assert_content_free(failure: LineageDiscoveryFailure) -> None:
    assert CANARY not in str(failure)
    assert CANARY not in repr(failure)
    assert not hasattr(failure, "stdout")
    assert not hasattr(failure, "stderr")
    assert not hasattr(failure, "path")
    assert not hasattr(failure, "profile")
    assert not hasattr(failure, "config_file")


def test_saved_and_live_success_return_the_same_normalized_topology(tmp_path: Path) -> None:
    saved_path = tmp_path / "lineage.json"
    saved_path.write_text(json.dumps(_payload()), encoding="utf-8")
    executable, record_path = _fake_executable(tmp_path)
    config_path = tmp_path / f"{CANARY}.yaml"
    config_path.write_text("profile: existing\n", encoding="utf-8")

    saved = acquire_saved(saved_path, scope_label="Synthetic scope")
    live = acquire_live(
        executable,
        scope_label="Synthetic scope",
        config_file=config_path,
    )

    assert isinstance(saved, LineageTopology)
    assert live == saved
    invocation = json.loads(record_path.read_text(encoding="utf-8"))
    assert invocation["argv"] == [
        "--config-file",
        str(config_path),
        "--list-datasets",
        "--format",
        "json",
        "--output",
        "-",
        "--quiet",
    ]


def test_live_312_acquires_enriched_relationship_metadata(tmp_path: Path) -> None:
    executable, record_path = _fake_executable(
        tmp_path,
        payload=json.dumps(_enriched_payload()).encode(),
        version="cja_auto_sdr 3.12.0",
    )

    topology = acquire_live(executable, scope_label="Scope", profile="existing")

    edges = {(edge.dataset_id, edge.connection_id): edge for edge in topology.dataset_connections}
    assert edges[("ds-shared", "conn-event")].connection_metadata.role.value == "event"
    assert edges[("ds-shared", "conn-profile")].connection_metadata.role.value == "profile"
    invocation = json.loads(record_path.read_text(encoding="utf-8"))
    assert invocation["argv"] == [
        "--profile",
        "existing",
        "--list-datasets",
        "--format",
        "json",
        "--output",
        "-",
        "--quiet",
    ]


def test_profile_live_uses_only_the_profile_selector(tmp_path: Path) -> None:
    executable, record_path = _fake_executable(tmp_path)

    result = acquire_live(executable, scope_label="Scope", profile="existing")

    assert isinstance(result, LineageTopology)
    invocation = json.loads(record_path.read_text(encoding="utf-8"))
    assert invocation["argv"] == [
        "--profile",
        "existing",
        "--list-datasets",
        "--format",
        "json",
        "--output",
        "-",
        "--quiet",
    ]


def test_live_rejects_conflicting_credential_selectors_before_spawning(
    tmp_path: Path, monkeypatch
) -> None:
    executable, _ = _fake_executable(tmp_path)

    monkeypatch.setattr(
        lineage_discovery.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not spawn")),
    )

    result = acquire_live(
        executable,
        scope_label="Scope",
        profile="existing",
        config_file=Path("/tmp/config.json"),
    )

    assert result == LineageDiscoveryFailure(LineageDiscoveryFailureCode.SELECTOR_INVALID)


def test_default_live_supports_upstream_environment_dotenv_and_config_discovery(
    tmp_path: Path, monkeypatch
) -> None:
    executable, record_path = _fake_executable(tmp_path)
    credential_environment = {
        "CJA_PROFILE": "environment-profile",
        "ORG_ID": "org",
        "CLIENT_ID": "client",
        "SECRET": CANARY,
        "SCOPES": "scope",
        "SANDBOX": "sandbox",
    }
    for name, value in credential_environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("UNRELATED_ENV_CANARY", CANARY)

    result = acquire_live(executable, scope_label="Scope")

    assert isinstance(result, LineageTopology)
    invocation = json.loads(record_path.read_text(encoding="utf-8"))
    assert invocation["argv"] == [
        "--list-datasets",
        "--format",
        "json",
        "--output",
        "-",
        "--quiet",
    ]
    child_env = invocation["env"]
    assert {name: child_env[name] for name in credential_environment} == credential_environment
    assert "HOME" in child_env
    assert "UNRELATED_ENV_CANARY" not in child_env


def test_live_child_receives_only_the_minimal_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNRELATED_ENV_CANARY", CANARY)
    executable, record_path = _fake_executable(tmp_path)
    real_popen = lineage_discovery.subprocess.Popen
    supplied_environments: list[dict[str, str]] = []

    def recording_popen(*args, **kwargs):
        supplied_environments.append(dict(kwargs["env"]))
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(lineage_discovery.subprocess, "Popen", recording_popen)

    result = acquire_live(executable, scope_label="Scope", profile="existing")

    assert isinstance(result, LineageTopology)
    child_env = json.loads(record_path.read_text(encoding="utf-8"))["env"]
    assert "UNRELATED_ENV_CANARY" not in child_env
    assert CANARY not in child_env.values()
    assert set(supplied_environments[0]) == {"LANG", "LC_ALL", "PATH"}
    assert set(supplied_environments[1]) == {"HOME", "LANG", "LC_ALL", "PATH"}
    assert all(CANARY not in environment.values() for environment in supplied_environments)


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("relative", LineageDiscoveryFailureCode.EXECUTABLE_INVALID),
        ("missing", LineageDiscoveryFailureCode.EXECUTABLE_INVALID),
        ("writable", LineageDiscoveryFailureCode.EXECUTABLE_INVALID),
        ("wrong-version", LineageDiscoveryFailureCode.EXECUTABLE_VERSION_MISMATCH),
    ],
)
def test_untrusted_executable_is_rejected_content_free(
    tmp_path: Path, setup: str, expected: LineageDiscoveryFailureCode
) -> None:
    executable, _ = _fake_executable(
        tmp_path,
        version="cja_auto_sdr 3.11.7" if setup == "wrong-version" else "cja_auto_sdr 3.11.8",
    )
    if setup == "relative":
        candidate: Path = Path(executable.name)
    elif setup == "missing":
        candidate = tmp_path / f"missing-{CANARY}"
    else:
        candidate = executable
    if setup == "writable":
        executable.chmod(executable.stat().st_mode | stat.S_IWGRP)

    result = acquire_live(
        candidate,
        scope_label="Scope",
        profile=f"profile-{CANARY}",
    )

    assert result == LineageDiscoveryFailure(expected)
    _assert_content_free(result)


def test_nonzero_exit_wins_over_valid_json_and_discards_all_output(tmp_path: Path) -> None:
    executable, _ = _fake_executable(
        tmp_path,
        exit_code=7,
        stderr=f'{{"detail": "{CANARY}"}}'.encode(),
    )

    result = acquire_live(executable, scope_label="Scope", profile="existing")

    assert result == LineageDiscoveryFailure(LineageDiscoveryFailureCode.PROCESS_FAILED)
    _assert_content_free(result)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"\xff", LineageDiscoveryFailureCode.INVALID_UTF8),
        (b"not-json", LineageDiscoveryFailureCode.INVALID_JSON),
        (b"{}", LineageDiscoveryFailureCode.INVALID_STRUCTURE),
    ],
)
def test_live_decode_parse_and_normalization_failures_are_distinct_and_content_free(
    tmp_path: Path, payload: bytes, expected: LineageDiscoveryFailureCode
) -> None:
    executable, _ = _fake_executable(tmp_path, payload=payload)

    result = acquire_live(executable, scope_label="Scope", profile="existing")

    assert result == LineageDiscoveryFailure(expected)
    _assert_content_free(result)


def test_saved_source_is_incrementally_bounded_and_has_distinct_failures(tmp_path: Path) -> None:
    oversized = tmp_path / f"saved-{CANARY}.json"
    oversized.write_bytes(b"x" * 17)
    invalid_utf8 = tmp_path / "utf8.json"
    invalid_utf8.write_bytes(b"\xff")

    too_large = acquire_saved(oversized, scope_label="Scope", max_bytes=16)
    bad_encoding = acquire_saved(invalid_utf8, scope_label="Scope")
    missing = acquire_saved(tmp_path / f"missing-{CANARY}", scope_label="Scope")

    assert too_large == LineageDiscoveryFailure(LineageDiscoveryFailureCode.SAVED_TOO_LARGE)
    assert bad_encoding == LineageDiscoveryFailure(LineageDiscoveryFailureCode.INVALID_UTF8)
    assert missing == LineageDiscoveryFailure(LineageDiscoveryFailureCode.SAVED_READ_FAILED)
    for failure in (too_large, bad_encoding, missing):
        _assert_content_free(failure)


def test_saved_source_rejects_fifo_without_waiting_for_a_writer(tmp_path: Path) -> None:
    fifo = tmp_path / "lineage.fifo"
    os.mkfifo(fifo)
    results = []

    reader = threading.Thread(
        target=lambda: results.append(acquire_saved(fifo, scope_label="Scope")),
        daemon=True,
    )
    reader.start()
    reader.join(timeout=0.5)
    if reader.is_alive():
        writer = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        os.close(writer)
        reader.join(timeout=0.5)

    assert not reader.is_alive(), "saved acquisition blocked while opening a FIFO"
    assert results == [LineageDiscoveryFailure(LineageDiscoveryFailureCode.SAVED_READ_FAILED)]


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        ("stdout", LineageDiscoveryFailureCode.STDOUT_LIMIT_EXCEEDED),
        ("stderr", LineageDiscoveryFailureCode.STDERR_LIMIT_EXCEEDED),
    ],
)
def test_each_live_channel_is_independently_bounded(
    tmp_path: Path, channel: str, expected: LineageDiscoveryFailureCode
) -> None:
    payload = b"x" * 65 if channel == "stdout" else json.dumps(_payload()).encode()
    stderr = b"x" * 33 if channel == "stderr" else b""
    executable, _ = _fake_executable(tmp_path, payload=payload, stderr=stderr)

    result = acquire_live(
        executable,
        scope_label="Scope",
        profile="existing",
        stdout_limit=64,
        stderr_limit=32,
    )

    assert result == LineageDiscoveryFailure(expected)
    _assert_content_free(result)


def test_live_capture_checks_limit_before_appending_chunk(tmp_path: Path, monkeypatch) -> None:
    executable, _ = _fake_executable(tmp_path, payload=b"x" * 65)
    real_bytearray = bytearray

    class GuardedBytearray(bytearray):
        def extend(self, chunk) -> None:
            assert len(self) + len(chunk) <= 64
            super().extend(chunk)

    monkeypatch.setattr(lineage_discovery, "bytearray", GuardedBytearray, raising=False)
    result = acquire_live(
        executable,
        scope_label="Scope",
        profile="existing",
        stdout_limit=64,
        stderr_limit=64,
    )
    monkeypatch.setattr(lineage_discovery, "bytearray", real_bytearray)

    assert result == LineageDiscoveryFailure(LineageDiscoveryFailureCode.STDOUT_LIMIT_EXCEEDED)


@pytest.mark.parametrize("timeout_seconds", [float("inf"), float("nan")])
def test_non_finite_timeout_is_rejected_before_spawning(
    tmp_path: Path, monkeypatch, timeout_seconds: float
) -> None:
    executable, _ = _fake_executable(tmp_path)

    def unexpected_spawn(*args, **kwargs):
        raise AssertionError("non-finite timeout must be rejected before spawning")

    monkeypatch.setattr(lineage_discovery.subprocess, "Popen", unexpected_spawn)

    result = acquire_live(
        executable,
        scope_label="Scope",
        profile="existing",
        timeout_seconds=timeout_seconds,
    )

    assert result == LineageDiscoveryFailure(LineageDiscoveryFailureCode.PROCESS_FAILED)
    _assert_content_free(result)


def test_live_timeout_is_content_free(tmp_path: Path) -> None:
    executable, _ = _fake_executable(tmp_path, delay=2)

    started = time.monotonic()
    result = acquire_live(
        executable,
        scope_label="Scope",
        profile="existing",
        timeout_seconds=0.05,
    )

    assert time.monotonic() - started < 1.5
    assert result == LineageDiscoveryFailure(LineageDiscoveryFailureCode.TIMEOUT)
    _assert_content_free(result)


@pytest.mark.parametrize("failure_mode", ["timeout", "overflow"])
def test_timeout_and_overflow_terminate_descendants(tmp_path: Path, failure_mode: str) -> None:
    executable = tmp_path / "cja_auto_sdr"
    survivor = tmp_path / "descendant-survived"
    child_program = (
        "import pathlib,signal,time;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "time.sleep(0.5);"
        f"pathlib.Path({str(survivor)!r}).write_text('alive')"
    )
    overflow_line = (
        'sys.stdout.buffer.write(b"x" * 65); sys.stdout.buffer.flush()'
        if failure_mode == "overflow"
        else ""
    )
    executable.write_text(
        f"""#!{sys.executable}
import subprocess
import sys
import time

if sys.argv[1:] == [\"--version\"]:
    print(\"cja_auto_sdr 3.11.8\")
    raise SystemExit(0)
subprocess.Popen([sys.executable, \"-c\", {child_program!r}])
{overflow_line}
time.sleep(2)
""",
        encoding="utf-8",
    )
    executable.chmod(0o700)

    result = acquire_live(
        executable,
        scope_label="Scope",
        profile="existing",
        timeout_seconds=0.05 if failure_mode == "timeout" else 1,
        stdout_limit=64,
        stderr_limit=64,
    )

    expected = (
        LineageDiscoveryFailureCode.TIMEOUT
        if failure_mode == "timeout"
        else LineageDiscoveryFailureCode.STDOUT_LIMIT_EXCEEDED
    )
    assert result == LineageDiscoveryFailure(expected)
    time.sleep(0.6)
    assert not survivor.exists()


def test_wrong_owner_is_rejected_when_observable(tmp_path: Path, monkeypatch) -> None:
    executable, _ = _fake_executable(tmp_path)
    real_lstat = os.lstat

    def wrong_owner(path):
        result = real_lstat(path)
        values = list(result)
        values[4] = result.st_uid + 1
        return os.stat_result(values)

    monkeypatch.setattr(os, "lstat", wrong_owner)

    result = acquire_live(executable, scope_label="Scope", profile="existing")

    assert result == LineageDiscoveryFailure(LineageDiscoveryFailureCode.EXECUTABLE_INVALID)


@pytest.mark.parametrize("limit", [0, -1, True, None])
def test_invalid_saved_limits_rejected_before_read(tmp_path, limit):
    assert (
        acquire_saved(tmp_path / "missing", scope_label="Scope", max_bytes=limit).code
        == LineageDiscoveryFailureCode.SAVED_TOO_LARGE
    )


@pytest.mark.parametrize(
    "profile,config",
    [
        ("bad profile", None),
        (None, b"/tmp/config"),
        (None, object()),
        (None, "relative"),
        (None, "/tmp/\nconfig"),
    ],
)
def test_invalid_live_selectors_are_content_free(tmp_path, profile, config):
    executable, _ = _fake_executable(tmp_path)
    result = acquire_live(executable, scope_label="Scope", profile=profile, config_file=config)
    assert result.code == LineageDiscoveryFailureCode.SELECTOR_INVALID
    _assert_content_free(result)


def test_failed_version_probe_never_acquires(tmp_path, monkeypatch):
    executable, record = _fake_executable(tmp_path)
    monkeypatch.setattr(
        lineage_discovery, "_run_bounded", lambda *a, **kw: lineage_discovery._Capture(b"", 1)
    )
    result = acquire_live(executable, scope_label="Scope")
    assert result.code == LineageDiscoveryFailureCode.EXECUTABLE_INVALID
    assert not record.exists()


def _capture_args():
    return dict(env={}, stdout_limit=4096, stderr_limit=4096, timeout_seconds=2)


def test_spawn_error_is_content_free(monkeypatch):
    def fail(*a, **kw):
        raise OSError(CANARY)

    monkeypatch.setattr(lineage_discovery.subprocess, "Popen", fail)
    result = lineage_discovery._run_bounded(["missing"], **_capture_args())
    assert result.code == LineageDiscoveryFailureCode.PROCESS_FAILED
    _assert_content_free(result)


def test_closed_pipes_do_not_bypass_process_timeout():
    args = _capture_args()
    args["timeout_seconds"] = 0.1
    result = lineage_discovery._run_bounded(
        [sys.executable, "-c", "import os,time;os.close(1);os.close(2);time.sleep(5)"], **args
    )
    assert result.code == LineageDiscoveryFailureCode.TIMEOUT


def test_nonblocking_read_retry_keeps_output(monkeypatch):
    real_spawn = lineage_discovery.subprocess.Popen
    real_read = os.read
    ready = False
    retried = False

    def spawn(*a, **kw):
        nonlocal ready
        process = real_spawn(*a, **kw)
        ready = True
        return process

    def read(*a, **kw):
        nonlocal retried
        if ready and not retried:
            retried = True
            raise BlockingIOError()
        return real_read(*a, **kw)

    monkeypatch.setattr(lineage_discovery.subprocess, "Popen", spawn)
    monkeypatch.setattr(lineage_discovery.os, "read", read)
    result = lineage_discovery._run_bounded(
        [sys.executable, "-c", "print('complete')"], **_capture_args()
    )
    assert retried
    assert result.stdout == b"complete\n"


def test_termination_races_use_fallbacks(monkeypatch):
    from unittest.mock import Mock

    process = Mock(pid=123)
    process.poll.return_value = None

    def fail(*a, **kw):
        raise ProcessLookupError()

    monkeypatch.setattr(lineage_discovery.os, "killpg", fail)
    lineage_discovery._terminate_process_tree(process)
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count == 2


def test_missing_capture_pipe_and_read_error_are_controlled(monkeypatch):
    from unittest.mock import Mock

    process = Mock(stdout=None, stderr=None)
    process.poll.return_value = 0
    monkeypatch.setattr(lineage_discovery.subprocess, "Popen", lambda *a, **kw: process)
    terminate = Mock()
    monkeypatch.setattr(lineage_discovery, "_terminate_process_tree", terminate)
    assert (
        lineage_discovery._run_bounded(["fake"], **_capture_args()).code
        == LineageDiscoveryFailureCode.PROCESS_FAILED
    )
    terminate.assert_called_once_with(process)
    process.stdout = Mock()
    process.stderr = Mock()
    monkeypatch.setattr(
        lineage_discovery.os, "set_blocking", lambda *a: (_ for _ in ()).throw(OSError(CANARY))
    )
    assert (
        lineage_discovery._run_bounded(["fake"], **_capture_args()).code
        == LineageDiscoveryFailureCode.PROCESS_FAILED
    )
    process.stdout.close.assert_called_once()
