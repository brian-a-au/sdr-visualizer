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


def test_compare_to_embeds_changes_section(tmp_path):
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
    assert "snapshot path not found" in capsys.readouterr().err


def test_compare_to_instance_mismatch_exits_3(tmp_path, capsys):
    # Instance divergence is fatal, matching --trend: comparing different data
    # views / report suites would diff unrelated inventories.
    old = _write_json(tmp_path / "old.json", _cja_compare_snapshot(dv_id="dv_other"))
    new = _write_json(tmp_path / "new.json", _cja_compare_snapshot(dv_id="dv_cmp"))
    rc = main([str(new), "--compare-to", str(old), "--output", str(tmp_path / "o.html"), "--quiet"])
    assert rc == 3
    assert "instance mismatch" in capsys.readouterr().err


def test_compare_to_instance_mismatch_allowed_with_flag(tmp_path, capsys):
    # Explicit opt-in restores the cross-instance comparison (e.g. staging vs
    # prod drift): the run proceeds with a warning instead of exiting 3.
    old = _write_json(tmp_path / "old.json", _cja_compare_snapshot(dv_id="dv_other"))
    new = _write_json(tmp_path / "new.json", _cja_compare_snapshot(dv_id="dv_cmp"))
    rc = main(
        [
            str(new),
            "--compare-to",
            str(old),
            "--allow-instance-mismatch",
            "--output",
            str(tmp_path / "o.html"),
            "--quiet",
        ]
    )
    assert rc == 0
    err = capsys.readouterr().err
    assert "different instances" in err
    assert "allow-instance-mismatch" in err


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


def test_compare_to_directory_honors_at(tmp_path):
    # --at resolves a --compare-to baseline directory the same way it resolves
    # the primary directory: to the snapshot at or before the target, not latest.
    base_dir = tmp_path / "baselines"
    base_dir.mkdir()
    _write_json(base_dir / "snapshot_2026-01-01T00-00-00.json", _cja_compare_snapshot("Old Name"))
    _write_json(base_dir / "snapshot_2026-06-01T00-00-00.json", _cja_compare_snapshot("Metric One"))
    new = _write_json(tmp_path / "new.json", _cja_compare_snapshot("Metric One"))
    out = tmp_path / "out.html"
    rc = main(
        [
            str(new),
            "--compare-to",
            str(base_dir),
            "--at",
            "2026-03-01",
            "--output",
            str(out),
            "--quiet",
        ]
    )
    assert rc == 0
    payload = extract_payload(out.read_text(encoding="utf-8"))
    # --at pins the baseline to the January snapshot ("Old Name"); comparing the
    # "Metric One" primary against it shows the rename. Latest (June) shows none.
    assert payload["changes"]["modified"][0]["fields"] == [
        {"field": "name", "old": "Old Name", "new": "Metric One"}
    ]
    assert payload["meta"]["compared_to"]["source"].endswith("snapshot_2026-01-01T00-00-00.json")


def _trend_dir(tmp_path, names_and_metric_lists):
    d = tmp_path / "series"
    d.mkdir()
    for name, metrics in names_and_metric_lists:
        snap = _cja_compare_snapshot()
        snap["metrics"] = metrics
        _write_json(d / name, snap)
    return d


def test_trend_embeds_trend_section(tmp_path):
    d = _trend_dir(
        tmp_path,
        [
            (
                "snapshot_2026-01-01T00-00-00.json",
                [{"id": "metrics/m1", "name": "One", "description": "d"}],
            ),
            (
                "snapshot_2026-02-01T00-00-00.json",
                [
                    {"id": "metrics/m1", "name": "One", "description": "d"},
                    {"id": "metrics/m2", "name": "Two", "description": "d"},
                ],
            ),
            (
                "snapshot_2026-03-01T00-00-00.json",
                [{"id": "metrics/m2", "name": "Two", "description": "d"}],
            ),
        ],
    )
    out = tmp_path / "trend.html"
    rc = main([str(d), "--trend", "--output", str(out), "--quiet"])
    assert rc == 0
    payload = extract_payload(out.read_text(encoding="utf-8"))
    trend = payload["trend"]
    assert len(trend["snapshots"]) == 3
    assert [s["aggregates"]["metrics"] for s in trend["snapshots"]] == [1, 2, 1]
    assert len(trend["intervals"]) == 2
    assert trend["intervals"][0]["added"] == ["metrics/m2"]
    assert trend["intervals"][1]["removed"] == ["metrics/m1"]
    assert trend["capped"] is False
    # The primary report is the newest snapshot.
    ids = {c["id"] for c in payload["components"]}
    assert ids == {"metrics/m2"}


def test_no_trend_flag_means_no_trend_section(tmp_path):
    snap = _write_json(tmp_path / "snap.json", _cja_compare_snapshot())
    out = tmp_path / "plain.html"
    rc = main([str(snap), "--output", str(out), "--quiet"])
    assert rc == 0
    assert "trend" not in extract_payload(out.read_text(encoding="utf-8"))


def test_trend_with_file_input_exits_3(tmp_path, capsys):
    snap = _write_json(tmp_path / "snap.json", _cja_compare_snapshot())
    rc = main([str(snap), "--trend", "--output", str(tmp_path / "o.html"), "--quiet"])
    assert rc == 3
    assert "snapshot directory" in capsys.readouterr().err


def test_trend_with_compare_to_exits_3(tmp_path):
    d = _trend_dir(
        tmp_path,
        [
            ("snapshot_2026-01-01T00-00-00.json", []),
            ("snapshot_2026-02-01T00-00-00.json", []),
        ],
    )
    other = _write_json(tmp_path / "b.json", _cja_compare_snapshot())
    with pytest.raises(SystemExit) as exc_info:
        main([str(d), "--trend", "--compare-to", str(other), "--quiet"])
    assert exc_info.value.code == 3


def test_trend_with_dataview_exits_3():
    with pytest.raises(SystemExit) as exc_info:
        main(["--dataview", "dv_1", "--trend", "--quiet"])
    assert exc_info.value.code == 3


def test_trend_fewer_than_two_snapshots_exits_3(tmp_path, capsys):
    d = _trend_dir(
        tmp_path,
        [("snapshot_2026-01-01T00-00-00.json", [])],
    )
    rc = main([str(d), "--trend", "--output", str(tmp_path / "o.html"), "--quiet"])
    assert rc == 3
    assert "at least 2" in capsys.readouterr().err


_AA_SNAP = {"report_suite": {"rsid": "test"}, "dimensions": [], "metrics": []}


def test_trend_mixed_platform_without_declaration_exits_3(tmp_path, capsys):
    # Platform is declarable, so a directory mixing CJA and AA without
    # --platform is ambiguous: refuse rather than guess a majority (mirrors
    # --compare-to's platform-mismatch error).
    d = _trend_dir(
        tmp_path,
        [
            ("snapshot_2026-01-01T00-00-00.json", []),
            ("snapshot_2026-02-01T00-00-00.json", []),
        ],
    )
    _write_json(d / "snapshot_2026-03-01T00-00-00.json", _AA_SNAP)
    rc = main([str(d), "--trend", "--output", str(tmp_path / "o.html"), "--quiet"])
    assert rc == 3
    err = capsys.readouterr().err
    assert "mixes platforms" in err
    assert "--platform" in err


def test_trend_platform_declaration_selects_one_platform(tmp_path, capsys):
    # With --platform, the non-matching snapshot fails to adapt and is skipped,
    # leaving a clean single-platform series.
    d = _trend_dir(
        tmp_path,
        [
            (
                "snapshot_2026-01-01T00-00-00.json",
                [{"id": "metrics/m1", "name": "One", "description": "d"}],
            ),
            (
                "snapshot_2026-02-01T00-00-00.json",
                [{"id": "metrics/m1", "name": "One", "description": "d"}],
            ),
        ],
    )
    _write_json(d / "snapshot_2026-03-01T00-00-00.json", _AA_SNAP)
    out = tmp_path / "o.html"
    rc = main([str(d), "--trend", "--platform", "cja", "--output", str(out), "--quiet"])
    assert rc == 0
    assert "skipping" in capsys.readouterr().err  # AA snapshot failed CJA adaptation
    payload = extract_payload(out.read_text(encoding="utf-8"))
    assert len(payload["trend"]["snapshots"]) == 2


def _cja_trend_snapshot(dv_id, metric_ids):
    return {
        "metadata": {"Data View ID": dv_id, "Data View Name": dv_id},
        "data_view": {"id": dv_id},
        "metrics": [{"id": mid, "name": mid, "description": "d"} for mid in metric_ids],
        "dimensions": [],
        "segments": {"segments": []},
        "calculated_metrics": {"metrics": []},
    }


def test_trend_mixed_instance_exits_3(tmp_path, capsys):
    # A directory mixing two data views of the same platform is refused rather
    # than diffing unrelated inventories, the same way --compare-to refuses an
    # instance mismatch.
    d = tmp_path / "series"
    d.mkdir()
    _write_json(d / "snapshot_2026-01-01T00-00-00.json", _cja_trend_snapshot("dv_main", ["m1"]))
    _write_json(
        d / "snapshot_2026-02-01T00-00-00.json", _cja_trend_snapshot("dv_main", ["m1", "m2"])
    )
    _write_json(
        d / "snapshot_2026-03-01T00-00-00.json", _cja_trend_snapshot("dv_other", ["x1", "x2"])
    )
    rc = main([str(d), "--trend", "--output", str(tmp_path / "o.html"), "--quiet"])
    assert rc == 3
    err = capsys.readouterr().err
    assert "mixes data views / report suites" in err
    assert "dv_main" in err and "dv_other" in err


def test_trend_mixed_instance_allowed_with_flag(tmp_path, capsys):
    # Explicit opt-in lets a mixed-instance directory chart anyway, with a
    # warning; every usable snapshot is included.
    d = tmp_path / "series"
    d.mkdir()
    _write_json(d / "snapshot_2026-01-01T00-00-00.json", _cja_trend_snapshot("dv_main", ["m1"]))
    _write_json(
        d / "snapshot_2026-02-01T00-00-00.json", _cja_trend_snapshot("dv_main", ["m1", "m2"])
    )
    _write_json(
        d / "snapshot_2026-03-01T00-00-00.json", _cja_trend_snapshot("dv_other", ["x1", "x2"])
    )
    out = tmp_path / "o.html"
    rc = main([str(d), "--trend", "--allow-instance-mismatch", "--output", str(out), "--quiet"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "mixes data views / report suites" in err
    assert "allow-instance-mismatch" in err
    payload = extract_payload(out.read_text(encoding="utf-8"))
    assert len(payload["trend"]["snapshots"]) == 3


def test_trend_snapshot_with_bad_scalar_skipped_not_aborted(tmp_path, capsys):
    # A non-numeric scalar makes the adapter raise ValueError. Trend mode must
    # warn and skip that one snapshot, not abort the whole build with exit 1.
    d = _trend_dir(
        tmp_path,
        [
            (
                "snapshot_2026-01-01T00-00-00.json",
                [{"id": "metrics/m1", "name": "One", "description": "d"}],
            ),
            (
                "snapshot_2026-02-01T00-00-00.json",
                [
                    {"id": "metrics/m1", "name": "One", "description": "d"},
                    {"id": "metrics/m2", "name": "Two", "description": "d"},
                ],
            ),
        ],
    )
    bad = _cja_compare_snapshot()
    bad["calculated_metrics"] = {
        "metrics": [{"metric_id": "cm/c1", "name": "C", "complexity_score": "high"}]
    }
    _write_json(d / "snapshot_2026-03-01T00-00-00.json", bad)
    out = tmp_path / "o.html"
    rc = main([str(d), "--trend", "--output", str(out), "--quiet"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "skipping" in err
    assert "snapshot_2026-03-01T00-00-00.json" in err
    payload = extract_payload(out.read_text(encoding="utf-8"))
    assert len(payload["trend"]["snapshots"]) == 2


def _extreme_snapshot() -> dict:
    """A valid CJA snapshot inflated past the Q4 threshold (5,000+ components)."""
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    base = snap["metrics"][0]
    snap["metrics"] = [
        {**base, "id": f"metrics/gen_{i:05d}", "name": f"Generated Metric {i}"} for i in range(5001)
    ]
    return snap


def test_extreme_size_warns_but_builds(tmp_path, capsys):
    src = tmp_path / "extreme.json"
    src.write_text(json.dumps(_extreme_snapshot()), encoding="utf-8")
    out = tmp_path / "report.html"
    rc = main([str(src), "--output", str(out), "--quiet"])
    assert rc == 0
    assert out.exists()
    err = capsys.readouterr().err
    # The warning states the size and that the graph view needs opt-in —
    # and --quiet must NOT suppress it (warnings are never quiet-gated).
    assert "warning:" in err
    assert "components" in err
    assert "--max-graph-nodes" in err


def test_normal_size_does_not_warn(tmp_path, capsys):
    out = tmp_path / "report.html"
    rc = main([str(FIXTURES / "cja_snapshot_clean.json"), "--output", str(out), "--quiet"])
    assert rc == 0
    assert "components" not in capsys.readouterr().err


def test_newer_generator_version_prints_compat_warning(tmp_path, capsys):
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    snap["metadata"]["Tool Version"] = "99.0.0"
    src = tmp_path / "newer.json"
    src.write_text(json.dumps(snap), encoding="utf-8")
    rc = main([str(src), "--output", str(tmp_path / "r.html"), "--quiet"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "warning:" in err
    assert "99.0.0" in err


def test_tested_generator_version_does_not_warn(tmp_path, capsys):
    rc = main(
        [
            str(FIXTURES / "cja_snapshot_clean.json"),
            "--output",
            str(tmp_path / "r.html"),
            "--quiet",
        ]
    )
    assert rc == 0
    assert "generator version" not in capsys.readouterr().err
