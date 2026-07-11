"""Phase 8: input modes 2 (directory), 3 (shell-out), 4 (stdin)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from sdr_visualizer.cli.main import main
from sdr_visualizer.input.loader import load_snapshot

FIXTURES = Path(__file__).parent / "fixtures"


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


def test_mode3_dataview_shells_to_cja_auto_sdr(tmp_path, monkeypatch):
    payload = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))

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
    rc = main(["--dataview", "dv_xyz", "--output", str(output), "--quiet"])
    assert rc == 0
    assert "cja_auto_sdr" in captured["cmd"][0]
    assert "dv_xyz" in captured["cmd"]
    assert "--format" in captured["cmd"] and "json" in captured["cmd"]
    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")


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
    assert "aa_auto_sdr" in captured["cmd"][0]
    assert "prod_us" in captured["cmd"]


def test_mode3_unknown_tool_returns_validation_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sdr_visualizer.input.shell_out.shutil.which", lambda name: None)
    rc = main(["--dataview", "dv_xyz", "--quiet"])
    assert rc == 3
    err = capsys.readouterr().err
    assert "cja_auto_sdr" in err
    assert "not found on PATH" in err


# ---------------------------------------------------------------------------
# Mode 4: stdin
# ---------------------------------------------------------------------------


def test_mode4_stdin(tmp_path, monkeypatch):
    payload = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    output = tmp_path / "out.html"
    rc = main(["-", "--output", str(output), "--quiet"])
    assert rc == 0
    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")


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


def test_at_on_file_input_warns_and_ignores(tmp_path, capsys):
    f = tmp_path / "snap.json"
    f.write_text('{"a": 1}', encoding="utf-8")
    snap, _ = load_snapshot(str(f), at="2026-01-01")
    assert snap == {"a": 1}
    assert "--at applies only to snapshot directories" in capsys.readouterr().err
