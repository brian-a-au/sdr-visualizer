"""End-to-end CLI tests (SPEC-VISUALIZER §10 Phase 3 — Mode 1 only for now)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdr_visualizer.cli.main import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_mode1_writes_html(tmp_path):
    output = tmp_path / "out.html"
    rc = main([str(FIXTURES / "cja_snapshot_clean.json"), "--output", str(output), "--quiet"])
    assert rc == 0
    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert "<!doctype html>" in text
    assert 'id="catalog-view"' in text


def test_missing_path_returns_input_validation_error(tmp_path, capsys):
    rc = main([str(tmp_path / "does-not-exist.json"), "--quiet"])
    assert rc == 3
    err = capsys.readouterr().err
    assert "snapshot path not found" in err


def test_explicit_platform_override(tmp_path):
    """Adapter-mismatch should fail with InvalidSnapshotError -> exit 3."""
    bogus = tmp_path / "bogus.json"
    bogus.write_text('{"foo": "bar"}', encoding="utf-8")
    rc = main([str(bogus), "--platform", "cja", "--quiet"])
    assert rc == 3


def test_default_output_path_uses_instance_id(tmp_path, monkeypatch):
    """Without --output, the file lands at ./visualize-{instance}-{ts}.html."""
    monkeypatch.chdir(tmp_path)
    rc = main([str(FIXTURES / "cja_snapshot_clean.json"), "--quiet"])
    assert rc == 0
    files = list(tmp_path.glob("visualize-dv_clean_prod_web-*.html"))
    assert len(files) == 1


@pytest.mark.parametrize(
    "fixture_name",
    [
        "cja_snapshot_clean.json",
        "cja_snapshot_messy.json",
        "aa_snapshot_clean.json",
        "aa_snapshot_messy.json",
    ],
)
def test_renders_all_fixtures(tmp_path, fixture_name):
    output = tmp_path / "out.html"
    rc = main([str(FIXTURES / fixture_name), "--output", str(output), "--quiet"])
    assert rc == 0
    text = output.read_text(encoding="utf-8")
    assert "<!doctype html>" in text


def test_nan_snapshot_exits_3(tmp_path, capsys):
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    snap["calculated_metrics"]["metrics"][0]["complexity_score"] = float("nan")
    bad = tmp_path / "nan_snapshot.json"
    bad.write_text(json.dumps(snap), encoding="utf-8")
    rc = main([str(bad), "--output", str(tmp_path / "out.html"), "--quiet"])
    assert rc == 3
    assert "NaN or Infinity" in capsys.readouterr().err


def test_no_input_source_exits_3():
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 3


def test_conflicting_input_sources_exit_3():
    with pytest.raises(SystemExit) as exc_info:
        main([str(FIXTURES / "cja_snapshot_clean.json"), "--dataview", "dv_1"])
    assert exc_info.value.code == 3


def test_unknown_flag_exits_3():
    with pytest.raises(SystemExit) as exc_info:
        main(["--no-such-flag"])
    assert exc_info.value.code == 3


def test_unwritable_output_exits_1_with_clean_message(tmp_path, capsys):
    rc = main(
        [
            str(FIXTURES / "cja_snapshot_clean.json"),
            "--output",
            str(tmp_path / "missing-dir" / "out.html"),
            "--quiet",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "sdr-visualizer: could not write" in err
    assert "Traceback" not in err
