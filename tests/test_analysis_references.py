"""Tests for analysis/references.py (SPEC-VISUALIZER §10 Phase 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdr_visualizer.adapters.cja import adapt as cja_adapt
from sdr_visualizer.analysis.references import build_reference_graph

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def messy_graph():
    snap = json.loads((FIXTURES / "cja_snapshot_messy.json").read_text(encoding="utf-8"))
    return build_reference_graph(cja_adapt(snap))


def test_graph_has_node_for_every_component(messy_graph):
    type_counts: dict[str, int] = {}
    for n in messy_graph["nodes"]:
        type_counts[n["type"]] = type_counts.get(n["type"], 0) + 1
    assert type_counts["metric"] == 142
    assert type_counts["dimension"] == 203
    assert type_counts["derived_field"] == 142
    assert type_counts["segment"] == 25
    assert type_counts["calculated_metric"] == 30


def test_graph_edges_have_consistent_endpoints(messy_graph):
    ids = {n["id"] for n in messy_graph["nodes"]}
    for e in messy_graph["edges"]:
        assert e["source"] in ids
        assert e["target"] in ids
        assert e["kind"] == "references"


def test_graph_in_out_degrees_sum_to_edge_count(messy_graph):
    edges = len(messy_graph["edges"])
    assert sum(messy_graph["in_degree"].values()) == edges
    assert sum(messy_graph["out_degree"].values()) == edges


def test_referenced_evars_have_in_degree(messy_graph):
    """variables/evar2 is in the dimension inventory and referenced by
    multiple segments / calc metrics; revenue and visits are NOT in the
    inventory (they're dangling refs from upstream) so the parser drops
    those edges. Use a present id."""
    assert messy_graph["in_degree"].get("variables/evar2", 0) >= 1
    assert "metrics/revenue" not in messy_graph["in_degree"]


def test_dangling_references_are_dropped(messy_graph):
    """Edges only exist when the target is in the inventory."""
    ids = {n["id"] for n in messy_graph["nodes"]}
    for edge in messy_graph["edges"]:
        assert edge["target"] in ids
