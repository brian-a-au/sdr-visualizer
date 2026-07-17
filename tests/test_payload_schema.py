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
