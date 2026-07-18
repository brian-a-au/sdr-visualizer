"""Payload schema validation (1.0.0 contract).

Every payload shape the tool can emit — the four bundled fixtures, a
--compare-to payload, a --trend payload, and the --json sidecar — must
validate against docs/payload-schema.json, so the published schema cannot
drift from what the pipeline actually produces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import extract_payload
from jsonschema import Draft202012Validator

from sdr_visualizer.analysis.diff import diff_implementations
from sdr_visualizer.analysis.trend import build_trend
from sdr_visualizer.cli.main import main
from sdr_visualizer.core.visualizer import build_implementation
from sdr_visualizer.render.renderer import build_payload_with_options

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = json.loads((REPO / "docs" / "payload-schema.json").read_text(encoding="utf-8"))
FIXTURE_NAMES = [
    "cja_snapshot_clean.json",
    "cja_snapshot_messy.json",
    "aa_snapshot_clean.json",
    "aa_snapshot_messy.json",
]


def _impl(name: str):
    snapshot = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return build_implementation(snapshot, source=name)


def _assert_valid(payload: dict) -> None:
    validator = Draft202012Validator(SCHEMA)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.json_path)
    assert not errors, "\n".join(f"{e.json_path}: {e.message}" for e in errors[:20])


def test_schema_is_valid_draft_2020_12():
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_payload_validates(name):
    _assert_valid(build_payload_with_options(_impl(name)))


def test_compare_payload_validates():
    baseline = _impl("cja_snapshot_clean.json")
    impl = _impl("cja_snapshot_messy.json")
    payload = build_payload_with_options(impl)
    payload["changes"] = diff_implementations(baseline, impl)
    payload["meta"]["compared_to"] = payload["changes"]["baseline"]
    _assert_valid(payload)


def test_trend_payload_validates():
    impls = [_impl("cja_snapshot_clean.json"), _impl("cja_snapshot_messy.json")]
    payload = build_payload_with_options(impls[-1])
    payload["trend"] = build_trend(impls, capped=False)
    _assert_valid(payload)


def test_json_sidecar_validates_and_matches_embedded(tmp_path):
    out = tmp_path / "report.html"
    sidecar = tmp_path / "payload.json"
    rc = main(
        [
            str(FIXTURES / "cja_snapshot_clean.json"),
            "--output",
            str(out),
            "--json",
            str(sidecar),
            "--quiet",
        ]
    )
    assert rc == 0
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    _assert_valid(payload)
    assert payload == extract_payload(out.read_text(encoding="utf-8"))


def test_option_driven_payload_validates(tmp_path):
    """--max-graph-nodes (and --exclude-orphans) mutate payload["meta"];
    no flag-driven payload shape should be able to drift from the schema
    unnoticed."""
    out = tmp_path / "report.html"
    sidecar = tmp_path / "payload.json"
    rc = main(
        [
            str(FIXTURES / "cja_snapshot_clean.json"),
            "--output",
            str(out),
            "--json",
            str(sidecar),
            "--max-graph-nodes",
            "500",
            "--exclude-orphans",
            "--quiet",
        ]
    )
    assert rc == 0
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["meta"]["max_graph_nodes"] == 500
    assert payload["meta"]["exclude_orphans_default"] is True
    _assert_valid(payload)
    assert payload == extract_payload(out.read_text(encoding="utf-8"))


def test_bare_records_payload_validates():
    """A legal, adapter-accepted snapshot can omit component data_type,
    segment owner/container_types, and calculated-metric owner/formula_text
    entirely: cja_auto_sdr does this for a metric with no declared dataType,
    a segment with an empty definition and no declared container, and a bare
    calculated metric with no owner or formula summary. _compact drops these
    keys from the payload rather than emitting null/empty placeholders, so
    the schema must not require them (they stay optional in properties)."""
    snapshot = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))

    bare_metric = snapshot["metrics"][0]
    bare_metric_id = bare_metric["id"]
    del bare_metric["dataType"]
    del bare_metric["type"]  # adapter falls back to "type" for data_type

    bare_segment = snapshot["segments"]["segments"][0]
    bare_segment_id = bare_segment["segment_id"]
    bare_segment["definition_json"] = "{}"
    del bare_segment["container_type"]  # adapter falls back to this too
    del bare_segment["owner"]

    bare_calc = snapshot["calculated_metrics"]["metrics"][0]
    bare_calc_id = bare_calc["metric_id"]
    del bare_calc["formula_summary"]
    del bare_calc["owner"]

    impl = build_implementation(snapshot, source="bare-records")
    payload = build_payload_with_options(impl)

    component = next(c for c in payload["components"] if c["id"] == bare_metric_id)
    assert "data_type" not in component

    segment = next(s for s in payload["segments"] if s["id"] == bare_segment_id)
    assert "owner" not in segment
    assert "container_types" not in segment

    calc = next(c for c in payload["calculated_metrics"] if c["id"] == bare_calc_id)
    assert "owner" not in calc
    assert "formula_text" not in calc

    _assert_valid(payload)


def test_component_polarity_validates():
    """A metric/dimension can declare polarity (e.g. bounce rate = negative);
    data_payload.py's _component_node writes it straight through when set.
    Mutates the loaded snapshot dict in-test — the fixture file itself is
    untouched."""
    snapshot = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    snapshot["metrics"][0]["polarity"] = "negative"
    impl = build_implementation(snapshot, source="cja_snapshot_clean.json")
    payload = build_payload_with_options(impl)
    component = next(c for c in payload["components"] if c["id"] == snapshot["metrics"][0]["id"])
    assert component["polarity"] == "negative"
    _assert_valid(payload)


def test_trend_from_timestampless_snapshots_validates():
    """build_trend emits taken_at=None when a snapshot has no timestamp —
    shipped 1.0.0 behavior the schema wrongly rejected (required string)."""

    def _stripped(name):
        snapshot = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        for key in list(snapshot.get("metadata", {})):
            if "timestamp" in key.lower() or "generated" in key.lower():
                snapshot["metadata"].pop(key)
        return build_implementation(snapshot, source=name)

    impls = [_stripped("cja_snapshot_clean.json"), _stripped("cja_snapshot_messy.json")]
    assert impls[0].snapshot_taken_at is None  # guard against vacuity
    payload = build_payload_with_options(impls[-1])
    payload["trend"] = build_trend(impls, capped=False)
    assert payload["trend"]["snapshots"][0]["taken_at"] is None
    _assert_valid(payload)
