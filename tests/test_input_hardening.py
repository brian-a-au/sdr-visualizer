"""Regressions for 1.2.8 catalog input hardening.

Each case was a crash (exit 1), a payload schema violation, or a diagnostic
that echoed snapshot content.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from sdr_visualizer.cli.main import main

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"
CJA = json.loads((FIXTURES / "cja_snapshot_minimal.json").read_text(encoding="utf-8"))
AA = json.loads((FIXTURES / "aa_snapshot_clean.json").read_text(encoding="utf-8"))
SECRET = "SECRET-owner-jane@corp.example"


def _write(path: Path, data) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _run(argv, capsys):
    code = main(argv)
    return code, capsys.readouterr().err


def _cja_with(key: str, records: list) -> dict:
    snap = copy.deepcopy(CJA)
    snap[key] = {key if key != "calculated_metrics" else "metrics": records}
    return snap


@pytest.mark.parametrize(
    ("key", "record"),
    [
        ("calculated_metrics", {"metric_id": "cm1", "complexity_score": 10**400}),
        ("segments", {"segment_id": "s1", "nesting_depth": float("inf")}),
        ("segments", {"segment_id": "s1", "nesting_depth": float("-inf")}),
    ],
)
def test_cja_overflowing_numbers_are_invalid_input(tmp_path, capsys, key, record):
    src = _write(tmp_path / "s.json", _cja_with(key, [record]))

    code, err = _run([str(src), "--output", str(tmp_path / "o.html")], capsys)

    assert code == 3, err
    assert "unexpected error" not in err
    assert not (tmp_path / "o.html").exists()


def test_aa_overflowing_complexity_is_invalid_input(tmp_path, capsys):
    snap = copy.deepcopy(AA)
    snap["calculated_metrics"][0]["complexity_score"] = 10**400
    src = _write(tmp_path / "s.json", snap)

    code, err = _run([str(src), "--output", str(tmp_path / "o.html")], capsys)

    assert code == 3, err
    assert "unexpected error" not in err


def test_trend_skips_member_with_overflowing_number(tmp_path, capsys):
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    for day in ("01", "02"):
        _write(snaps / f"snap_2026-05-{day}.json", CJA)
    bad = _cja_with("calculated_metrics", [{"metric_id": "cm1", "complexity_score": 10**400}])
    _write(snaps / "snap_2026-05-03.json", bad)

    code, err = _run([str(snaps), "--trend", "--output", str(tmp_path / "o.html")], capsys)

    assert code == 0, err
    assert "skipping" in err and "snap_2026-05-03.json" in err


@pytest.mark.parametrize("at", ["9999-12-31T23:59:59-01:00", "0001-01-01T00:00:00+01:00"])
@pytest.mark.parametrize("trend", [False, True])
def test_at_outside_datetime_range_is_invalid_input(tmp_path, capsys, at, trend):
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    _write(snaps / "snap_2026-05-01.json", CJA)
    _write(snaps / "snap_2026-05-02.json", CJA)
    argv = [str(snaps), "--at", at, "--output", str(tmp_path / "o.html")]

    code, err = _run([*argv, "--trend"] if trend else argv, capsys)

    assert code == 3, err
    assert "not a recognized timestamp" in err


def test_dangling_symlink_is_skipped_in_mtime_directory(tmp_path, capsys):
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    _write(snaps / "good.json", CJA)
    (snaps / "dangling.json").symlink_to(tmp_path / "missing.json")

    code, err = _run([str(snaps), "--output", str(tmp_path / "o.html")], capsys)

    assert code == 0, err
    assert "skipping dangling.json: could not read file metadata" in err


def test_directory_of_only_dangling_symlinks_is_invalid_input(tmp_path, capsys):
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    (snaps / "dangling.json").symlink_to(tmp_path / "missing.json")

    code, err = _run([str(snaps), "--output", str(tmp_path / "o.html")], capsys)

    assert code == 3, err
    assert "no readable .json snapshots" in err


def test_trend_skips_dangling_symlink_in_mtime_directory(tmp_path, capsys):
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    _write(snaps / "a.json", CJA)
    _write(snaps / "b.json", CJA)
    (snaps / "dangling.json").symlink_to(tmp_path / "missing.json")

    code, err = _run([str(snaps), "--trend", "--output", str(tmp_path / "o.html")], capsys)

    assert code == 0, err
    assert "skipping dangling.json" in err


def test_dangling_symlink_stays_a_protected_output_candidate(tmp_path, capsys):
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    _write(snaps / "good.json", CJA)
    (snaps / "dangling.json").symlink_to(tmp_path / "target.json")

    code, err = _run([str(snaps), "--json", str(tmp_path / "target.json")], capsys)

    assert code == 3, err
    assert not (tmp_path / "target.json").exists()


def test_non_utf8_stdin_is_invalid_input(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "sdr_visualizer", "-", "--output", str(tmp_path / "o.html")],
        input=b'{"metadata": {"Data View ID": "\xff"}}',
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        cwd=REPO,
        timeout=60,
    )

    assert result.returncode == 3, result.stderr
    assert b"stdin is not valid UTF-8" in result.stderr


@pytest.mark.parametrize(
    ("platform", "key", "record", "context"),
    [
        ("cja", "metrics", {"name": "Revenue", "description": SECRET}, "CJA metrics"),
        ("cja", "dimensions", {"name": "Page", "owner": SECRET}, "CJA dimensions"),
        ("aa", "segments", {"name": "Seg", "definition": {"note": SECRET}}, "AA segments"),
        ("aa", "metrics", {"name": "Orders", "description": SECRET}, "AA metrics"),
    ],
)
def test_missing_id_errors_name_the_position_not_the_record(
    tmp_path, capsys, platform, key, record, context
):
    snap = copy.deepcopy(CJA if platform == "cja" else AA)
    snap[key].append(record)
    src = _write(tmp_path / "s.json", snap)

    code, err = _run([str(src), "--output", str(tmp_path / "o.html")], capsys)

    assert code == 3
    assert f"{context}[{len(snap[key]) - 1}]" in err
    assert SECRET not in err
    assert record["name"] not in err


@pytest.mark.parametrize(
    "key", ["derived_fields", "calculated_metrics", "segments"], ids=lambda key: key
)
def test_cja_missing_id_errors_do_not_echo_nested_records(tmp_path, capsys, key):
    snap = _cja_with(key, [{"name": "Hidden", "description": SECRET}])
    if key == "derived_fields":
        snap[key] = [{"name": "Hidden", "description": SECRET}]
    src = _write(tmp_path / "s.json", snap)

    code, err = _run([str(src), "--output", str(tmp_path / "o.html")], capsys)

    assert code == 3
    assert f"CJA {key}[0]" in err
    assert SECRET not in err


def test_coercion_errors_do_not_echo_values(tmp_path, capsys):
    src = _write(
        tmp_path / "s.json",
        _cja_with("calculated_metrics", [{"metric_id": "cm1", "complexity_score": SECRET}]),
    )

    code, err = _run([str(src), "--output", str(tmp_path / "o.html")], capsys)

    assert code == 3
    assert "expected a number, got str" in err
    assert SECRET not in err


def test_trend_skip_warning_does_not_echo_record(tmp_path, capsys):
    snaps = tmp_path / "snaps"
    snaps.mkdir()
    _write(snaps / "snap_2026-05-01.json", CJA)
    _write(snaps / "snap_2026-05-02.json", CJA)
    bad = copy.deepcopy(CJA)
    bad["dimensions"].append({"name": "n", "description": SECRET})
    _write(snaps / "snap_2026-05-03.json", bad)

    code, err = _run([str(snaps), "--trend", "--output", str(tmp_path / "o.html")], capsys)

    assert code == 0
    assert "skipping" in err and "snap_2026-05-03.json" in err
    assert SECRET not in err


def test_live_failure_does_not_echo_generator_stderr(tmp_path, monkeypatch, capsys):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "aa_auto_sdr"
    fake.write_text(f"#!/bin/sh\necho 'Segment {SECRET}' >&2\nexit 4\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")

    code, err = _run(["--rsid", "rs1", "--output", str(tmp_path / "o.html")], capsys)

    assert code == 3
    assert "aa_auto_sdr exited 4" in err
    assert SECRET not in err


@pytest.mark.parametrize(
    ("attribution", "allocation"),
    [({"model": "x", "lookback": 30}, 7), (["last"], {"kind": "x"}), (5, True)],
)
def test_aa_non_string_attribution_fields_are_omitted(tmp_path, capsys, attribution, allocation):
    snap = copy.deepcopy(AA)
    snap["calculated_metrics"][0]["attribution"] = attribution
    snap["calculated_metrics"][0]["allocation"] = allocation
    src = _write(tmp_path / "s.json", snap)
    sidecar = tmp_path / "o.json"

    code, err = _run(
        [str(src), "--output", str(tmp_path / "o.html"), "--json", str(sidecar)], capsys
    )

    assert code == 0, err
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    schema = json.loads((REPO / "docs" / "payload-schema.json").read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(schema).iter_errors(payload))
    metric_id = snap["calculated_metrics"][0]["id"]
    entry = next(item for item in payload["calculated_metrics"] if item["id"] == metric_id)
    assert "attribution_model" not in entry
    assert "allocation" not in entry


def test_aa_string_attribution_fields_are_kept(tmp_path, capsys):
    snap = copy.deepcopy(AA)
    snap["calculated_metrics"][0]["attribution"] = "linear"
    snap["calculated_metrics"][0]["allocation"] = "participation"
    src = _write(tmp_path / "s.json", snap)
    sidecar = tmp_path / "o.json"

    code, err = _run(
        [str(src), "--output", str(tmp_path / "o.html"), "--json", str(sidecar)], capsys
    )

    assert code == 0, err
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    metric_id = snap["calculated_metrics"][0]["id"]
    entry = next(item for item in payload["calculated_metrics"] if item["id"] == metric_id)
    assert entry["attribution_model"] == "linear"
    assert entry["allocation"] == "participation"


def test_undecodable_stdin_is_invalid_input_in_process(monkeypatch, tmp_path, capsys):
    class Undecodable:
        def read(self):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(sys, "stdin", Undecodable())

    code, err = _run(["-", "--output", str(tmp_path / "o.html")], capsys)

    assert code == 3
    assert "stdin is not valid UTF-8" in err


# sdr-grader 1.7.0 parity: 82c742e, 90a9b3f, 5736d46, 7cf980b.


def _stdin_bytes(data: bytes, *, encoding: str):
    import io

    # A text stream whose locale encoding is not UTF-8; .buffer holds the raw bytes.
    return io.TextIOWrapper(io.BytesIO(data), encoding=encoding)


def test_stdin_is_decoded_as_utf8_regardless_of_locale_encoding(monkeypatch):
    from sdr_visualizer.input.loader import load_snapshot

    snapshot = copy.deepcopy(AA)
    snapshot["report_suite"]["name"] = "Café Ünïcode"
    payload = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
    monkeypatch.setattr(sys, "stdin", _stdin_bytes(payload, encoding="latin-1"))

    loaded, source = load_snapshot("-")

    assert source == "stdin"
    assert loaded["report_suite"]["name"] == "Café Ünïcode"


def test_stdin_bytes_that_are_not_utf8_are_invalid(monkeypatch):
    from sdr_visualizer.core.exceptions import InvalidSnapshotError
    from sdr_visualizer.input.loader import load_snapshot

    monkeypatch.setattr(sys, "stdin", _stdin_bytes(b'{"name": "\xff"}', encoding="latin-1"))

    with pytest.raises(InvalidSnapshotError, match="^stdin is not valid UTF-8$"):
        load_snapshot("-")


@pytest.mark.parametrize("flag", ["--dataview", "--rsid"])
@pytest.mark.parametrize("identifier", ["", "--help", "-x", "--output=/tmp/x"])
def test_live_ids_that_are_empty_or_option_like_are_rejected_before_spawning(
    monkeypatch, flag, identifier
):
    from sdr_visualizer.core.exceptions import InvalidSnapshotError
    from sdr_visualizer.input import shell_out

    def no_spawn(*_args, **_kwargs):
        raise AssertionError("the upstream tool must not be started")

    monkeypatch.setattr(shell_out.shutil, "which", lambda _tool: sys.executable)
    monkeypatch.setattr(shell_out.subprocess, "run", no_spawn)
    shell = shell_out.shell_cja if flag == "--dataview" else shell_out.shell_aa

    with pytest.raises(InvalidSnapshotError) as exc_info:
        shell(identifier)

    assert str(exc_info.value) == (
        f"{flag} requires an ID that is not empty and does not start with '-'"
    )


def test_option_like_live_id_exits_3_from_the_cli(tmp_path, capsys):
    code, err = _run(["--rsid=--help", "--output", str(tmp_path / "o.html")], capsys)

    assert code == 3
    assert "--rsid requires an ID" in err


@pytest.mark.parametrize("primary", [None, {}, "", []])
def test_detection_reads_the_same_report_suite_key_as_the_adapter(primary):
    from sdr_visualizer.core.exceptions import UnknownPlatformError
    from sdr_visualizer.input.detect import detect_platform

    snapshot = {
        "report_suite": primary,
        "reportSuite": {"rsid": "rs1", "name": "Main suite"},
        "dimensions": [],
        "metrics": [],
    }

    with pytest.raises(UnknownPlatformError, match="could not auto-detect platform"):
        detect_platform(snapshot)


@pytest.mark.parametrize("missing", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_names_and_types_count_as_missing(missing):
    from sdr_visualizer.adapters import aa, cja

    component = aa._component_from_record(
        {"id": "evar1", "name": missing, "type": missing}, "dimension", {}
    )
    assert (component.name, component.data_type) == ("evar1", None)
    assert aa._calc_from_record({"id": "cm1", "name": missing}).name == "cm1"
    assert aa._segment_from_record({"id": "s1", "name": missing}).name == "s1"
    snapshot = {"report_suite": {"rsid": "rs1", "name": missing}, "dimensions": [], "metrics": []}
    assert aa.adapt(snapshot, source="nan.json").instance_name == "rs1"

    metric = cja._component_from_record(
        {"id": "metrics/m1", "name": missing, "title": "Title", "type": missing}, "metric"
    )
    assert (metric.name, metric.data_type) == ("Title", None)
    derived = cja._derived_field_from_record(
        {"component_id": "variables/df1", "component_name": missing}
    )
    assert derived.name == "variables/df1"
    assert cja._calc_metric_from_record({"metric_id": "cm1", "metric_name": missing}).name == "cm1"
    assert cja._segment_from_record({"segment_id": "s1", "segment_name": missing}).name == "s1"
