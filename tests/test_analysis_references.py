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
    assert type_counts["metric"] == 175
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


def test_referenced_components_have_in_degree(messy_graph):
    """variables/evar2 is referenced by segments; metrics/revenue and
    metrics/visits are referenced by calc metrics. All three are in the
    inventory, so all three should accrue in_degree from those edges."""
    assert messy_graph["in_degree"].get("variables/evar2", 0) >= 1
    assert messy_graph["in_degree"].get("metrics/revenue", 0) >= 1
    assert messy_graph["in_degree"].get("metrics/visits", 0) >= 1


def test_dangling_references_are_dropped(messy_graph):
    """Edges only exist when the target is in the inventory."""
    ids = {n["id"] for n in messy_graph["nodes"]}
    for edge in messy_graph["edges"]:
        assert edge["target"] in ids


def test_dangling_references_dropped_synthetic():
    """The messy fixture is now internally consistent; verify dangle-dropping
    against a synthetic implementation that explicitly contains one."""
    from sdr_visualizer.core.models import (
        CalculatedMetric,
        Component,
        Implementation,
    )

    known = Component(
        id="metrics/known",
        name="Known",
        description=None,
        component_type="metric",
        data_type="integer",
        polarity=None,
        created_at=None,
        modified_at=None,
        owner=None,
    )
    cm = CalculatedMetric(
        id="calc/x",
        name="X",
        description=None,
        formula={},
        formula_text="",
        attribution_model=None,
        allocation=None,
        complexity_score=0,
        references=["metrics/known", "metrics/missing"],
    )
    impl = Implementation(
        instance_id="t",
        instance_name="t",
        platform="cja",
        snapshot_taken_at=None,
        snapshot_source="t",
        adapter_version="0",
        metrics=[known],
        dimensions=[],
        derived_fields=[],
        segments=[],
        calculated_metrics=[cm],
        raw={},
    )
    g = build_reference_graph(impl)
    targets = {e["target"] for e in g["edges"]}
    assert "metrics/known" in targets
    assert "metrics/missing" not in targets
    assert "metrics/missing" not in g["in_degree"]
