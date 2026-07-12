"""End-to-end CLI tests (SPEC-VISUALIZER §10 Phase 3 — Mode 1 only for now)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import extract_payload

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


def _cja_compare_snapshot(metric_name="Metric One", extra_metric=False, dv_id="dv_cmp"):
    metrics = [{"id": "metrics/m1", "name": metric_name, "description": "d"}]
    if extra_metric:
        metrics.append({"id": "metrics/m2", "name": "Metric Two", "description": "d"})
    return {
        "metadata": {"Data View ID": dv_id, "Data View Name": "Compare"},
        "data_view": {"id": dv_id},
        "metrics": metrics,
        "dimensions": [],
        "segments": {"segments": []},
        "calculated_metrics": {"metrics": []},
    }


def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_compare_to_embeds_changes_section(tmp_path, capsys):
    old = _write_json(tmp_path / "old.json", _cja_compare_snapshot("Metric One"))
    new = _write_json(
        tmp_path / "new.json", _cja_compare_snapshot("Metric One (renamed)", extra_metric=True)
    )
    out = tmp_path / "out.html"
    rc = main([str(new), "--compare-to", str(old), "--output", str(out), "--quiet"])
    assert rc == 0
    payload = extract_payload(out.read_text(encoding="utf-8"))
    changes = payload["changes"]
    assert [e["id"] for e in changes["added"]] == ["metrics/m2"]
    assert changes["removed"] == []
    assert changes["modified"][0]["fields"] == [
        {"field": "name", "old": "Metric One", "new": "Metric One (renamed)"}
    ]
    assert payload["meta"]["compared_to"]["source"].endswith("old.json")


def test_no_compare_flag_means_no_changes_section(tmp_path):
    snap = _write_json(tmp_path / "snap.json", _cja_compare_snapshot())
    out = tmp_path / "plain.html"
    rc = main([str(snap), "--output", str(out), "--quiet"])
    assert rc == 0
    payload = extract_payload(out.read_text(encoding="utf-8"))
    assert "changes" not in payload
    assert "compared_to" not in payload["meta"]


def test_compare_to_platform_mismatch_exits_3(tmp_path, capsys):
    rc = main(
        [
            str(FIXTURES / "cja_snapshot_clean.json"),
            "--compare-to",
            str(FIXTURES / "aa_snapshot_clean.json"),
            "--output",
            str(tmp_path / "out.html"),
            "--quiet",
        ]
    )
    assert rc == 3
    assert "platform mismatch" in capsys.readouterr().err


def test_compare_to_rejects_stdin(tmp_path, capsys):
    snap = _write_json(tmp_path / "snap.json", _cja_compare_snapshot())
    rc = main([str(snap), "--compare-to", "-", "--output", str(tmp_path / "o.html"), "--quiet"])
    assert rc == 3
    assert "stdin" in capsys.readouterr().err


def test_compare_to_missing_path_exits_3(tmp_path, capsys):
    snap = _write_json(tmp_path / "snap.json", _cja_compare_snapshot())
    rc = main(
        [
            str(snap),
            "--compare-to",
            str(tmp_path / "nope.json"),
            "--output",
            str(tmp_path / "o.html"),
            "--quiet",
        ]
    )
    assert rc == 3


def test_compare_to_instance_mismatch_warns(tmp_path, capsys):
    old = _write_json(tmp_path / "old.json", _cja_compare_snapshot(dv_id="dv_other"))
    new = _write_json(tmp_path / "new.json", _cja_compare_snapshot(dv_id="dv_cmp"))
    rc = main([str(new), "--compare-to", str(old), "--output", str(tmp_path / "o.html"), "--quiet"])
    assert rc == 0
    assert "comparing different instances" in capsys.readouterr().err


def test_compare_to_directory_resolves_latest(tmp_path):
    base_dir = tmp_path / "baselines"
    base_dir.mkdir()
    _write_json(base_dir / "snapshot_2026-01-01T00-00-00.json", _cja_compare_snapshot("Old Name"))
    _write_json(base_dir / "snapshot_2026-06-01T00-00-00.json", _cja_compare_snapshot("Metric One"))
    new = _write_json(tmp_path / "new.json", _cja_compare_snapshot("Metric One"))
    out = tmp_path / "out.html"
    rc = main([str(new), "--compare-to", str(base_dir), "--output", str(out), "--quiet"])
    assert rc == 0
    payload = extract_payload(out.read_text(encoding="utf-8"))
    # Latest baseline has the same name, so nothing is modified. If the old
    # one had been picked, metrics/m1 would report a name change.
    assert payload["changes"]["modified"] == []
    assert payload["meta"]["compared_to"]["source"].endswith("snapshot_2026-06-01T00-00-00.json")
