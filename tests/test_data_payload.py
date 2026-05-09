"""Tests for render/data_payload.py (SPEC-VISUALIZER §10 Phase 3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdr_visualizer.adapters.cja import adapt as cja_adapt
from sdr_visualizer.render.data_payload import build_payload

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def messy_payload():
    snap = json.loads((FIXTURES / "cja_snapshot_messy.json").read_text(encoding="utf-8"))
    return build_payload(cja_adapt(snap))


def test_payload_has_top_level_keys(messy_payload):
    expected = {
        "meta",
        "components",
        "segments",
        "calculated_metrics",
        "graph",
        "catalog_index",
        "segment_trees",
        "formula_trees",
    }
    assert expected <= set(messy_payload.keys())


def test_meta_includes_versions_and_counts(messy_payload):
    meta = messy_payload["meta"]
    assert meta["platform"] == "cja"
    assert meta["instance_id"] == "dv_messy_prod_web"
    assert meta["visualizer_version"]
    assert meta["component_count"] == (
        len(messy_payload["components"])
        + len(messy_payload["segments"])
        + len(messy_payload["calculated_metrics"])
    )


def test_components_include_all_three_types(messy_payload):
    types = {c["type"] for c in messy_payload["components"]}
    assert types == {"metric", "dimension", "derived_field"}


def test_catalog_index_lowercased_search_blob(messy_payload):
    sample_id = messy_payload["components"][0]["id"]
    entry = messy_payload["catalog_index"]["by_id"][sample_id]
    assert entry["search"] == entry["search"].lower()
    assert sample_id.lower() in entry["search"]


def test_segment_and_formula_trees_keyed_by_id(messy_payload):
    segs = messy_payload["segments"]
    assert all(s["id"] in messy_payload["segment_trees"] for s in segs)
    cms = messy_payload["calculated_metrics"]
    assert all(c["id"] in messy_payload["formula_trees"] for c in cms)


def test_in_degree_pre_attached_to_entries(messy_payload):
    entries = [
        *messy_payload["components"],
        *messy_payload["segments"],
        *messy_payload["calculated_metrics"],
    ]
    # Every entry has an in_degree key (may be 0).
    assert all("in_degree" in e for e in entries)
    # Sum across entries should equal the graph edge count.
    edge_count = len(messy_payload["graph"]["edges"])
    assert sum(e["in_degree"] for e in entries) == edge_count


def test_payload_round_trips_through_json(messy_payload):
    """Embedded payload must serialize cleanly — no datetime, no dataclass."""
    text = json.dumps(messy_payload, separators=(",", ":"))
    parsed = json.loads(text)
    assert parsed["meta"]["platform"] == "cja"
