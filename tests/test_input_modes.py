"""Phase 8: input modes 2 (directory), 3 (shell-out), 4 (stdin)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from conftest import extract_payload

from sdr_visualizer.cli.main import main
from sdr_visualizer.core.exceptions import InvalidSnapshotError, UnknownPlatformError
from sdr_visualizer.input.detect import detect_platform
from sdr_visualizer.input.loader import load_snapshot
from sdr_visualizer.input.shell_out import shell_aa, shell_cja

FIXTURES = Path(__file__).parent / "fixtures"


def _write_cja_json_output(cmd: list[str], content: str) -> subprocess.CompletedProcess[str]:
    output_dir = Path(cmd[cmd.index("--output-dir") + 1])
    (output_dir / "current.json").write_text(content, encoding="utf-8")
    return subprocess.CompletedProcess(cmd, 0, stdout="SDR JSON written to disk\n")


# ---------------------------------------------------------------------------
# Mode 2: directory
# ---------------------------------------------------------------------------


def test_mode2_picks_latest_snapshot_in_directory(tmp_path):
    """Loader picks the most recent snapshot by filename timestamp."""
    early = tmp_path / "snapshot_2026-01-01T00-00-00.json"
    late = tmp_path / "snapshot_2026-04-25T09-14-00.json"
    payload = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    early.write_text(
        json.dumps({**payload, "metadata": {**payload["metadata"], "Tool Version": "old"}})
    )
    late.write_text(
        json.dumps({**payload, "metadata": {**payload["metadata"], "Tool Version": "new"}})
    )

    snap, source = load_snapshot(str(tmp_path))
    assert snap["metadata"]["Tool Version"] == "new"
    assert source.endswith("snapshot_2026-04-25T09-14-00.json")


def test_mode2_at_picks_closest_not_after(tmp_path):
    payload = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    a = tmp_path / "snapshot_2026-01-15.json"
    b = tmp_path / "snapshot_2026-03-01.json"
    c = tmp_path / "snapshot_2026-05-01.json"
    for p, version in [(a, "v1"), (b, "v2"), (c, "v3")]:
        p.write_text(
            json.dumps({**payload, "metadata": {**payload["metadata"], "Tool Version": version}})
        )

    snap, source = load_snapshot(str(tmp_path), at="2026-04-01")
    assert snap["metadata"]["Tool Version"] == "v2"
    assert "2026-03-01" in source


def test_mode2_cli_renders_directory(tmp_path):
    """End-to-end: CLI accepts a directory and produces HTML for the latest."""
    payload = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()
    (snap_dir / "snapshot_2026-04-25T09-14-00.json").write_text(json.dumps(payload))
    output = tmp_path / "out.html"
    rc = main([str(snap_dir), "--output", str(output), "--quiet"])
    assert rc == 0
    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")


# ---------------------------------------------------------------------------
# Mode 3: shell out
# ---------------------------------------------------------------------------


def test_mode3_dataview_shells_to_cja_auto_sdr_and_ignores_at(tmp_path, monkeypatch, capsys):
    payload = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))

    monkeypatch.setattr(
        "sdr_visualizer.input.shell_out.shutil.which",
        lambda name: "/usr/local/bin/" + name,
    )

    captured = {}

    def fake_subprocess_run(cmd, **kwargs):
        captured["cmd"] = cmd
        output_dir = Path(cmd[cmd.index("--output-dir") + 1])
        captured["output_dir"] = output_dir
        return _write_cja_json_output(cmd, json.dumps(payload))

    monkeypatch.setattr("sdr_visualizer.input.shell_out.subprocess.run", fake_subprocess_run)

    output = tmp_path / "out.html"
    rc = main(
        [
            "--dataview",
            "dv_xyz",
            "--at",
            "2026-04-25",
            "--output",
            str(output),
            "--quiet",
        ]
    )
    assert rc == 0
    assert captured["cmd"] == [
        "/usr/local/bin/cja_auto_sdr",
        "dv_xyz",
        "--format",
        "json",
        "--output-dir",
        str(captured["output_dir"]),
        "--include-all-inventory",
        "--quiet",
    ]
    assert not captured["output_dir"].exists()
    html = output.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    report = extract_payload(html)
    assert report["segments"]
    assert report["calculated_metrics"]
    assert any(component["type"] == "derived_field" for component in report["components"])
    assert "--at applies only to snapshot directories; ignoring" in capsys.readouterr().err


def test_shell_cja_appends_extra_args_after_complete_inventory_defaults(monkeypatch):
    payload = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        "sdr_visualizer.input.shell_out.shutil.which",
        lambda name: "/usr/local/bin/" + name,
    )
    captured = {}

    def fake_subprocess_run(cmd, **kwargs):
        captured["cmd"] = cmd
        output_dir = Path(cmd[cmd.index("--output-dir") + 1])
        captured["output_dir"] = output_dir
        return _write_cja_json_output(cmd, json.dumps(payload))

    monkeypatch.setattr("sdr_visualizer.input.shell_out.subprocess.run", fake_subprocess_run)

    shell_cja("dv_xyz", extra_args=["--log-level", "debug"])

    assert captured["cmd"] == [
        "/usr/local/bin/cja_auto_sdr",
        "dv_xyz",
        "--format",
        "json",
        "--output-dir",
        str(captured["output_dir"]),
        "--include-all-inventory",
        "--quiet",
        "--log-level",
        "debug",
    ]
    assert captured["cmd"].count("--include-all-inventory") == 1
    assert captured["cmd"].count("--quiet") == 1


def test_mode3_rsid_shells_to_aa_auto_sdr(tmp_path, monkeypatch):
    payload = json.loads((FIXTURES / "aa_snapshot_clean.json").read_text(encoding="utf-8"))

    monkeypatch.setattr(
        "sdr_visualizer.input.shell_out.shutil.which",
        lambda name: "/usr/local/bin/" + name,
    )

    class FakeRun:
        def __init__(self, stdout: str):
            self.stdout = stdout
            self.returncode = 0

    captured = {}

    def fake_subprocess_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeRun(json.dumps(payload))

    monkeypatch.setattr("sdr_visualizer.input.shell_out.subprocess.run", fake_subprocess_run)

    output = tmp_path / "out.html"
    rc = main(["--rsid", "prod_us", "--output", str(output), "--quiet"])
    assert rc == 0
    assert captured["cmd"] == [
        "/usr/local/bin/aa_auto_sdr",
        "prod_us",
        "--format",
        "json",
        "--output",
        "-",
    ]


@pytest.mark.parametrize(
    ("call", "tool"),
    [
        (lambda: shell_cja("dv_timeout"), "cja_auto_sdr"),
        (lambda: shell_aa("rs_timeout"), "aa_auto_sdr"),
    ],
)
def test_live_shell_timeout_is_bounded_and_content_free(monkeypatch, call, tool):
    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda _name: "/bin/tool")
    captured = {}

    def time_out(cmd, **kwargs):
        captured["timeout"] = kwargs["timeout"]
        if "--output-dir" in cmd:
            captured["output_dir"] = Path(cmd[cmd.index("--output-dir") + 1])
        raise subprocess.TimeoutExpired(
            cmd,
            kwargs["timeout"],
            output="customer snapshot content",
            stderr="customer credential content",
        )

    monkeypatch.setattr("sdr_visualizer.input.shell_out.subprocess.run", time_out)

    with pytest.raises(InvalidSnapshotError, match=rf"^{tool} exceeded 600-second timeout$") as exc:
        call()

    assert captured["timeout"] == 600
    assert "customer" not in str(exc.value)
    if "output_dir" in captured:
        assert not captured["output_dir"].exists()


@pytest.mark.parametrize(
    "argv",
    [["--dataview", "dv_timeout"], ["--rsid", "rs_timeout"]],
)
def test_live_shell_timeout_exits_3_without_artifacts(tmp_path, monkeypatch, capsys, argv):
    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda _name: "/bin/tool")

    def time_out(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"], stderr="hostile child output")

    monkeypatch.setattr("sdr_visualizer.input.shell_out.subprocess.run", time_out)
    html_output = tmp_path / "report.html"
    json_output = tmp_path / "report.json"

    rc = main([*argv, "--output", str(html_output), "--json", str(json_output), "--quiet"])

    assert rc == 3
    assert not html_output.exists()
    assert not json_output.exists()
    err = capsys.readouterr().err
    assert "600-second timeout" in err
    assert "hostile child output" not in err
    assert "Traceback" not in err


def test_mode3_unknown_tool_returns_validation_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda name: None)
    rc = main(["--dataview", "dv_xyz", "--quiet"])
    assert rc == 3
    err = capsys.readouterr().err
    assert "cja_auto_sdr" in err
    assert "not found on PATH" in err


@pytest.mark.parametrize("stderr", ["credentials rejected\n", None])
def test_shell_out_nonzero_exit_preserves_status_and_stderr(monkeypatch, stderr):
    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda _name: "/bin/tool")

    def fail(cmd, **_kwargs):
        raise subprocess.CalledProcessError(7, cmd, stderr=stderr)

    monkeypatch.setattr("sdr_visualizer.input.shell_out.subprocess.run", fail)

    with pytest.raises(InvalidSnapshotError) as exc_info:
        shell_cja("dv_xyz")

    message = str(exc_info.value)
    assert "cja_auto_sdr exited 7" in message
    assert ("credentials rejected" if stderr else "(no stderr)") in message


def test_shell_out_file_disappearing_after_lookup_is_domain_error(monkeypatch):
    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda _name: "/bin/tool")

    def disappear(_cmd, **_kwargs):
        raise FileNotFoundError("binary disappeared")

    monkeypatch.setattr("sdr_visualizer.input.shell_out.subprocess.run", disappear)

    with pytest.raises(InvalidSnapshotError, match="could not be invoked: binary disappeared"):
        shell_cja("dv_xyz")


def test_shell_out_invalid_utf8_is_domain_error(monkeypatch):
    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda _name: "/bin/tool")

    def invalid_utf8(_cmd, **_kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr("sdr_visualizer.input.shell_out.subprocess.run", invalid_utf8)

    with pytest.raises(InvalidSnapshotError, match="could not be invoked"):
        shell_cja("dv_xyz")


def test_shell_out_invalid_json_is_domain_error(monkeypatch):
    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda _name: "/bin/tool")
    captured = {}

    def write_invalid_json(cmd, **_kwargs):
        captured["output_dir"] = Path(cmd[cmd.index("--output-dir") + 1])
        return _write_cja_json_output(cmd, "not json")

    monkeypatch.setattr(
        "sdr_visualizer.input.shell_out.subprocess.run",
        write_invalid_json,
    )

    with pytest.raises(InvalidSnapshotError, match="produced output that is not valid JSON"):
        shell_cja("dv_xyz")
    assert not captured["output_dir"].exists()


def test_shell_out_oversized_integer_is_domain_error(monkeypatch):
    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda _name: "/bin/tool")
    oversized = '{"value":' + ("9" * 5_000) + "}"
    monkeypatch.setattr(
        "sdr_visualizer.input.shell_out.subprocess.run",
        lambda cmd, **_kwargs: _write_cja_json_output(cmd, oversized),
    )

    with pytest.raises(InvalidSnapshotError, match="not valid JSON"):
        shell_cja("dv_xyz")


def test_shell_out_json_recursion_error_is_domain_error(monkeypatch):
    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda _name: "/bin/tool")
    monkeypatch.setattr(
        "sdr_visualizer.input.shell_out.subprocess.run",
        lambda cmd, **_kwargs: _write_cja_json_output(cmd, "{}"),
    )

    def recurse(_value):
        raise RecursionError("decoder recursion")

    monkeypatch.setattr("sdr_visualizer.input.shell_out.json.loads", recurse)

    with pytest.raises(InvalidSnapshotError, match="JSON exceeds nesting limits"):
        shell_cja("dv_xyz")


@pytest.mark.parametrize("output_count", [0, 2])
def test_shell_cja_requires_exactly_one_generated_json(monkeypatch, output_count):
    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda _name: "/bin/tool")
    captured = {}

    def write_outputs(cmd, **_kwargs):
        output_dir = Path(cmd[cmd.index("--output-dir") + 1])
        captured["output_dir"] = output_dir
        for index in range(output_count):
            (output_dir / f"{index}.json").write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="")

    monkeypatch.setattr("sdr_visualizer.input.shell_out.subprocess.run", write_outputs)

    with pytest.raises(InvalidSnapshotError, match=rf"produced {output_count} JSON outputs"):
        shell_cja("dv_xyz")
    assert not captured["output_dir"].exists()


def test_shell_cja_output_inspection_error_is_domain_error(monkeypatch):
    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda _name: "/bin/tool")
    monkeypatch.setattr(
        "sdr_visualizer.input.shell_out.subprocess.run",
        lambda cmd, **_kwargs: subprocess.CompletedProcess(cmd, 0, stdout=""),
    )

    def fail_glob(_path, _pattern):
        raise PermissionError("inspection denied")

    monkeypatch.setattr(Path, "glob", fail_glob)

    with pytest.raises(InvalidSnapshotError, match="JSON outputs could not be inspected"):
        shell_cja("dv_xyz")


def test_shell_cja_output_read_error_is_domain_error(monkeypatch):
    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda _name: "/bin/tool")
    monkeypatch.setattr(
        "sdr_visualizer.input.shell_out.subprocess.run",
        lambda cmd, **_kwargs: _write_cja_json_output(cmd, "{}"),
    )

    def fail_read(_path, **_kwargs):
        raise PermissionError("read denied")

    monkeypatch.setattr(Path, "read_text", fail_read)

    with pytest.raises(InvalidSnapshotError, match="JSON output could not be read"):
        shell_cja("dv_xyz")


def test_shell_cja_temporary_output_error_is_domain_error(monkeypatch):
    def fail_temporary_directory(**_kwargs):
        raise PermissionError("temporary directory denied")

    monkeypatch.setattr(
        "sdr_visualizer.input.shell_out.tempfile.TemporaryDirectory",
        fail_temporary_directory,
    )

    with pytest.raises(InvalidSnapshotError, match="temporary output handling failed"):
        shell_cja("dv_xyz")


# ---------------------------------------------------------------------------
# Mode 4: stdin
# ---------------------------------------------------------------------------


def test_mode4_stdin_ignores_at_with_warning(tmp_path, monkeypatch, capsys):
    payload = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    output = tmp_path / "out.html"
    rc = main(["-", "--at", "2026-04-25", "--output", str(output), "--quiet"])
    assert rc == 0
    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert "--at applies only to snapshot directories; ignoring" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("stdin_text", "expected"),
    [
        (" \n", "stdin is empty; expected JSON snapshot"),
        ("{not json", "stdin is not valid JSON"),
    ],
)
def test_mode4_malformed_stdin_exits_3(monkeypatch, capsys, stdin_text, expected):
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))

    rc = main(["-", "--quiet"])

    assert rc == 3
    assert expected in capsys.readouterr().err


def test_mode4_oversized_integer_exits_3(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"value":' + ("9" * 5_000) + "}"))

    rc = main(["-", "--quiet"])

    assert rc == 3
    assert "stdin is not valid JSON" in capsys.readouterr().err


def test_invalid_utf8_file_exits_3(tmp_path, capsys):
    snapshot = tmp_path / "invalid-utf8.json"
    snapshot.write_bytes(b"\xff")

    rc = main([str(snapshot), "--quiet"])

    assert rc == 3
    assert "could not read" in capsys.readouterr().err


def test_stdin_json_recursion_error_is_domain_error(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    def recurse(_value):
        raise RecursionError("decoder recursion")

    monkeypatch.setattr("sdr_visualizer.input.loader.json.loads", recurse)

    with pytest.raises(InvalidSnapshotError, match="stdin JSON exceeds nesting limits"):
        load_snapshot("-")


def test_file_json_recursion_error_is_domain_error(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("{}", encoding="utf-8")

    def recurse(_value):
        raise RecursionError("decoder recursion")

    monkeypatch.setattr("sdr_visualizer.input.loader.json.loads", recurse)

    with pytest.raises(InvalidSnapshotError, match="JSON exceeds nesting limits"):
        load_snapshot(str(snapshot))


# ---------------------------------------------------------------------------
# Mutual exclusion
# ---------------------------------------------------------------------------


def test_cli_rejects_both_path_and_dataview(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main([str(FIXTURES / "cja_snapshot_clean.json"), "--dataview", "dv_x", "--quiet"])
    err = capsys.readouterr().err
    assert "exactly one" in err


def test_cli_rejects_no_input(capsys):
    with pytest.raises(SystemExit):
        main(["--quiet"])
    err = capsys.readouterr().err
    assert "exactly one" in err


def test_at_accepts_iso_offset_and_fractional_seconds(tmp_path):
    (tmp_path / "snapshot_2026-01-01T00-00-00.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "snapshot_2026-03-01T00-00-00.json").write_text('{"b": 2}', encoding="utf-8")
    snap, _ = load_snapshot(str(tmp_path), at="2026-02-01T09:14:00+00:00")
    assert snap == {"a": 1}
    snap, _ = load_snapshot(str(tmp_path), at="2026-03-01T00:00:00.500")
    assert snap == {"b": 2}


def test_at_accepts_z_timestamp(tmp_path):
    (tmp_path / "snapshot_2026-01-01T00-00-00.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "snapshot_2026-03-01T00-00-00.json").write_text('{"b": 2}', encoding="utf-8")

    snap, source = load_snapshot(str(tmp_path), at="2026-03-01T00:00:00Z")

    assert snap == {"b": 2}
    assert source.endswith("snapshot_2026-03-01T00-00-00.json")


def test_invalid_at_value_and_missing_prior_snapshot_are_domain_errors(tmp_path):
    (tmp_path / "snapshot_2026-03-01T00-00-00.json").write_text('{"a": 1}', encoding="utf-8")

    with pytest.raises(InvalidSnapshotError, match="not a recognized timestamp"):
        load_snapshot(str(tmp_path), at="not-a-date")
    with pytest.raises(InvalidSnapshotError, match="no snapshot in directory is at or before"):
        load_snapshot(str(tmp_path), at="2026-01-01")


def test_empty_directory_is_domain_error(tmp_path):
    with pytest.raises(InvalidSnapshotError, match=r"no \.json snapshots found"):
        load_snapshot(str(tmp_path))


def test_unreadable_file_is_domain_error(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("{}", encoding="utf-8")

    def deny_read(_path, **_kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "read_text", deny_read)

    with pytest.raises(InvalidSnapshotError, match="could not read.*permission denied"):
        load_snapshot(str(snapshot))


def test_invalid_filename_timestamp_falls_back_to_mtime(tmp_path):
    older = tmp_path / "snapshot_2026-99-99.json"
    newer = tmp_path / "snapshot_2026-98-98.json"
    older.write_text('{"chosen": false}', encoding="utf-8")
    newer.write_text('{"chosen": true}', encoding="utf-8")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    snap, source = load_snapshot(str(tmp_path))

    assert snap == {"chosen": True}
    assert source.endswith(newer.name)


def test_mtime_cutoff_selection_is_timezone_independent(tmp_path):
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_text('{"chosen": "before"}', encoding="utf-8")
    after.write_text('{"chosen": "after"}', encoding="utf-8")
    os.utime(before, (1767265200, 1767265200))  # 2026-01-01T11:00:00Z
    os.utime(after, (1767272400, 1767272400))  # 2026-01-01T13:00:00Z
    original_tz = os.environ.get("TZ")
    selected = []
    try:
        for zone in ("UTC", "America/Los_Angeles", "Pacific/Auckland"):
            os.environ["TZ"] = zone
            time.tzset()
            snapshot, _source = load_snapshot(
                str(tmp_path),
                at="2026-01-01T07:00:00-05:00",
            )
            selected.append(snapshot["chosen"])
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()

    assert selected == ["before", "before", "before"]


def test_detect_platform_rejects_non_object_and_unknown_shape():
    with pytest.raises(UnknownPlatformError, match="not a JSON object"):
        detect_platform([])
    with pytest.raises(UnknownPlatformError, match="could not auto-detect"):
        detect_platform({"metadata": {}})


def test_detect_platform_accepts_data_view_shape():
    assert detect_platform({"data_view": {"id": "dv_xyz"}}) == "cja"


def _hybrid_snapshot() -> dict:
    return {
        "metadata": {"Data View ID": "shared", "Data View Name": "Shared"},
        "data_view": {"id": "shared"},
        "report_suite": {"rsid": "shared", "name": "Shared"},
        "dimensions": [],
        "metrics": [],
        "segments": [],
        "calculated_metrics": [],
    }


def test_detect_platform_rejects_dual_match_but_overrides_remain_explicit():
    snapshot = _hybrid_snapshot()

    with pytest.raises(UnknownPlatformError, match=r"matches both CJA and AA.*--platform cja\|aa"):
        detect_platform(snapshot)

    from sdr_visualizer.core.visualizer import build_implementation

    assert build_implementation(snapshot, platform="cja").platform == "cja"
    assert build_implementation(snapshot, platform="aa").platform == "aa"


@pytest.mark.parametrize("platform", ["cja", "aa"])
def test_hybrid_snapshot_explicit_override_works_for_cli_and_comparison(tmp_path, platform):
    primary = tmp_path / "primary.json"
    baseline = tmp_path / "baseline.json"
    primary.write_text(json.dumps(_hybrid_snapshot()), encoding="utf-8")
    baseline.write_text(json.dumps(_hybrid_snapshot()), encoding="utf-8")
    output = tmp_path / f"{platform}.html"

    rc = main(
        [
            str(primary),
            "--compare-to",
            str(baseline),
            "--platform",
            platform,
            "--output",
            str(output),
            "--quiet",
        ]
    )

    assert rc == 0
    assert output.exists()


def test_hybrid_snapshot_without_override_exits_3_without_artifacts(tmp_path, capsys):
    source = tmp_path / "hybrid.json"
    source.write_text(json.dumps(_hybrid_snapshot()), encoding="utf-8")
    html_output = tmp_path / "report.html"
    json_output = tmp_path / "report.json"

    rc = main(
        [
            str(source),
            "--output",
            str(html_output),
            "--json",
            str(json_output),
            "--quiet",
        ]
    )

    assert rc == 3
    assert not html_output.exists()
    assert not json_output.exists()
    assert "matches both CJA and AA" in capsys.readouterr().err


@pytest.mark.parametrize("platform", ["cja", "aa"])
def test_hybrid_snapshot_explicit_override_works_for_directory(tmp_path, platform):
    directory = tmp_path / "snapshots"
    directory.mkdir()
    (directory / "snapshot_2026-01-01T00-00-00.json").write_text(
        json.dumps(_hybrid_snapshot()), encoding="utf-8"
    )
    output = tmp_path / f"directory-{platform}.html"

    rc = main([str(directory), "--platform", platform, "--output", str(output), "--quiet"])

    assert rc == 0
    assert output.exists()


def test_at_on_file_input_warns_and_ignores(tmp_path, capsys):
    f = tmp_path / "snap.json"
    f.write_text('{"a": 1}', encoding="utf-8")
    snap, _ = load_snapshot(str(f), at="2026-01-01")
    assert snap == {"a": 1}
    assert "--at applies only to snapshot directories" in capsys.readouterr().err


def test_directory_drops_untimestamped_file_with_warning(tmp_path, capsys):
    # An un-timestamped file in an otherwise-timestamped directory is excluded
    # from selection with the same warning --trend emits (consistent feedback).
    (tmp_path / "snapshot_2026-01-01T00-00-00.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "snapshot_2026-02-01T00-00-00.json").write_text('{"b": 2}', encoding="utf-8")
    (tmp_path / "plain.json").write_text('{"c": 3}', encoding="utf-8")
    snap, _ = load_snapshot(str(tmp_path))
    assert snap == {"b": 2}  # latest timestamped; plain.json excluded
    assert (
        "skipping plain.json: no filename timestamp while other snapshots have one"
        in capsys.readouterr().err
    )


def test_mode3_ignores_platform_with_warning(tmp_path, monkeypatch, capsys):
    # --platform does not apply to Mode 3 (the flag selects the platform), so a
    # contradictory --platform is ignored with a warning rather than forced onto
    # a mismatched adapter (which would exit 3).
    payload = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        "sdr_visualizer.input.shell_out.shutil.which",
        lambda name: "/usr/local/bin/" + name,
    )

    monkeypatch.setattr(
        "sdr_visualizer.input.shell_out.subprocess.run",
        lambda cmd, **kwargs: _write_cja_json_output(cmd, json.dumps(payload)),
    )
    output = tmp_path / "out.html"
    rc = main(["--dataview", "dv_xyz", "--platform", "aa", "--output", str(output), "--quiet"])
    assert rc == 0
    assert "--platform does not apply to --dataview / --rsid" in capsys.readouterr().err
