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
        "segment_trees",
        "formula_trees",
    }
    assert expected <= set(messy_payload.keys())
    # Removed in 0.2.0 — the client builds its own search index at load.
    assert "catalog_index" not in messy_payload


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


def test_epoch_ms_parses_iso_and_spaced_timestamps():
    from sdr_visualizer.render.data_payload import _epoch_ms

    assert _epoch_ms("2026-04-25T09:14:00Z") == 1777108440000
    assert _epoch_ms("2026-04-25 09:14:00") == 1777108440000  # cja_auto_sdr shape
    assert _epoch_ms("not a date") is None
    assert _epoch_ms(None) is None
    assert _epoch_ms("") is None
    assert _epoch_ms("2026-04-25T09:14:00+05:30") != _epoch_ms("2026-04-25T09:14:00Z")


def test_modified_ts_mirrors_modified_at(messy_payload):
    from sdr_visualizer.render.data_payload import _epoch_ms

    entries = [
        *messy_payload["components"],
        *messy_payload["segments"],
        *messy_payload["calculated_metrics"],
    ]
    assert any(e.get("modified_ts") is not None for e in entries)
    for e in entries:
        assert e.get("modified_ts") == _epoch_ms(e.get("modified_at"))


def test_graph_embeds_edges_only(messy_payload):
    """nodes / degree maps were redundant with the catalog entries (0.2.0)."""
    assert set(messy_payload["graph"].keys()) == {"edges"}


def test_components_exclude_platform_specific(messy_payload):
    assert all("platform_specific" not in c for c in messy_payload["components"])


def test_entries_omit_null_and_empty_fields(messy_payload):
    entries = [
        *messy_payload["components"],
        *messy_payload["segments"],
        *messy_payload["calculated_metrics"],
    ]
    for entry in entries:
        for key, value in entry.items():
            assert value is not None, f"{entry['id']}: null field {key!r} not stripped"
            assert value != [], f"{entry['id']}: empty list {key!r} not stripped"
            assert value != {}, f"{entry['id']}: empty dict {key!r} not stripped"
            assert value != "", f"{entry['id']}: empty string {key!r} not stripped"


def test_duplicate_component_ids_warn_on_stderr(capsys):
    snapshot = {
        "metadata": {"Data View ID": "dv_dup", "Data View Name": "Dup"},
        "data_view": {"id": "dv_dup"},
        "metrics": [],
        "dimensions": [],
        "segments": {
            "segments": [
                {"segment_id": "segments/s1", "segment_name": "A", "definition_json": "{}"},
                {"segment_id": "segments/s1", "segment_name": "B", "definition_json": "{}"},
            ]
        },
        "calculated_metrics": {"metrics": []},
    }
    impl = cja_adapt(snapshot)
    build_payload(impl)
    err = capsys.readouterr().err
    assert "duplicate component ids" in err
    assert "segments/s1" in err
