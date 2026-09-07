"""Tests for normalized reference-graph analysis."""

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


def test_derived_field_references_create_unique_edges_and_drop_dangles():
    snapshot = {
        "metadata": {"Data View ID": "dv-derived-references"},
        "metrics": [{"id": "metrics/orders", "name": "Orders"}],
        "dimensions": [{"id": "variables/channel", "name": "Channel"}],
        "derived_fields": {
            "fields": [
                {
                    "component_id": "variables/derived-channel",
                    "component_name": "Derived Channel",
                    "component_references": (
                        '["metrics/orders", "variables/channel", '
                        '"metrics/orders", "variables/missing"]'
                    ),
                }
            ]
        },
    }

    graph = build_reference_graph(cja_adapt(snapshot))

    edges = [edge for edge in graph["edges"] if edge["source"] == "variables/derived-channel"]
    assert edges == [
        {
            "source": "variables/derived-channel",
            "target": "metrics/orders",
            "kind": "references",
        },
        {
            "source": "variables/derived-channel",
            "target": "variables/channel",
            "kind": "references",
        },
    ]
    assert graph["out_degree"]["variables/derived-channel"] == 2
    assert graph["in_degree"]["metrics/orders"] == 1
    assert graph["in_degree"]["variables/channel"] == 1


@pytest.mark.parametrize("encoded", [False, True])
def test_short_references_resolve_with_types_and_unique_counts(encoded):
    def refs(values):
        return json.dumps(values) if encoded else values

    snapshot = {
        "metadata": {"Data View ID": "dv-synthetic"},
        "metrics": [{"id": "metrics/url"}, {"id": "metrics/orders"}],
        "dimensions": [{"id": "variables/url"}],
        "segments": {
            "segments": [
                {
                    "segment_id": "segments/consumer",
                    "dimension_references": refs(["url", "variables/url", "url", "missing"]),
                    "metric_references": refs(["url"]),
                },
            ]
        },
        "calculated_metrics": {
            "metrics": [
                {
                    "metric_id": "calc/ratio",
                    "metric_references": refs(["orders", "orders"]),
                    "segment_references": refs(["consumer"]),
                },
            ]
        },
    }
    graph = build_reference_graph(cja_adapt(snapshot))
    assert {(e["source"], e["target"]) for e in graph["edges"]} == {
        ("segments/consumer", "variables/url"),
        ("segments/consumer", "metrics/url"),
        ("calc/ratio", "metrics/orders"),
        ("calc/ratio", "segments/consumer"),
    }
    assert len(graph["edges"]) == 4
    assert graph["out_degree"]["segments/consumer"] == 2
    assert graph["in_degree"]["variables/url"] == 1
    assert graph["unresolved"] == [
        {
            "source": "segments/consumer",
            "reference": "missing",
            "reference_type": "dimension",
            "reason": "missing",
        },
    ]


@pytest.mark.parametrize(
    "dimensions,metrics,ref,scope,target,reason",
    [
        (["url", "variables/url"], [], "url", "dimension", "url", None),
        (["variables/url", "custom/url"], [], "url", "dimension", None, "ambiguous"),
        (["xdm.web.url", "xdm.page.url"], [], "url", "dimension", None, "ambiguous"),
        (["variables/url", "xdm.page.url"], [], "url", "dimension", None, "ambiguous"),
        (["variables/url"], ["metrics/url"], "url", None, None, "ambiguous"),
        (["variables/url"], ["url"], "url", "dimension", "variables/url", None),
        (["variables/url"], [], "variables/url", "metric", None, "missing"),
        (["variables/url"], [], "other/url", "dimension", None, "missing"),
        (["variables/xdm.web.url"], [], "url", "dimension", None, "missing"),
        (["variables/xdm.web.url"], [], "xdm.web.url", "dimension", "variables/xdm.web.url", None),
        (["xdm.web.url"], [], "url", "dimension", "xdm.web.url", None),
        (["variables/url"], [], "URL", "dimension", None, "missing"),
    ],
)
def test_resolution_precedence_and_collisions(dimensions, metrics, ref, scope, target, reason):
    impl = cja_adapt(
        {
            "metadata": {"Data View ID": "dv-resolution"},
            "dimensions": [{"id": id_} for id_ in dimensions],
            "metrics": [{"id": id_} for id_ in metrics],
            "segments": {"segments": [{"segment_id": "consumer"}]},
        }
    )
    segment = impl.segments[0]
    segment.references = [ref, ref]
    segment.reference_types = {scope: [ref, ref]} if scope else {}
    graph = build_reference_graph(impl)
    assert [e["target"] for e in graph["edges"]] == ([target] if target else [])
    assert graph["out_degree"]["consumer"] == (1 if target else 0)
    assert [d["reason"] for d in graph["unresolved"]] == ([reason] if reason else [])
    assert sum(graph["in_degree"].values()) == len(graph["edges"])


def test_resolution_is_snapshot_local_and_aa_keeps_exact_matching():
    snapshot = {
        "metadata": {"Data View ID": "dv-local"},
        "metrics": [],
        "dimensions": [{"id": "variables/url"}],
        "segments": {"segments": [{"segment_id": "s", "dimension_references": ["url"]}]},
    }
    impl = cja_adapt(snapshot)
    assert len(build_reference_graph(impl)["edges"]) == 1
    impl.platform = "aa"
    assert build_reference_graph(impl)["edges"] == []
    impl.segments[0].reference_types = {}
    impl.segments[0].references = ["variables/url", "variables/url"]
    assert len(build_reference_graph(impl)["edges"]) == 1
    snapshot["dimensions"] = []
    assert build_reference_graph(cja_adapt(snapshot))["edges"] == []


def test_derived_kinds_and_calculated_metric_targets():
    impl = cja_adapt(
        {
            "metadata": {"Data View ID": "dv-derived"},
            "metrics": [],
            "dimensions": [],
            "derived_fields": {
                "fields": [
                    {"component_id": "variables/url", "component_type": "Dimension"},
                    {"component_id": "metrics/url", "component_type": "Metric"},
                    {
                        "component_id": "derived/untyped",
                        "component_references": ["url", "variables/url"],
                    },
                ]
            },
            "segments": {
                "segments": [
                    {
                        "segment_id": "s",
                        "dimension_references": ["url"],
                        "metric_references": ["url", "total"],
                    }
                ]
            },
            "calculated_metrics": {"metrics": [{"metric_id": "calc/total"}]},
        }
    )
    graph = build_reference_graph(impl)
    assert {(e["source"], e["target"]) for e in graph["edges"]} == {
        ("s", "variables/url"),
        ("s", "metrics/url"),
        ("s", "calc/total"),
        ("derived/untyped", "variables/url"),
    }
    assert graph["unresolved"] == [
        {"source": "derived/untyped", "reference": "url", "reason": "ambiguous"},
    ]


@pytest.mark.parametrize("scope", ["dimension", "metric"])
def test_exact_references_to_legacy_derived_fields_keep_existing_edges(scope):
    impl = cja_adapt(
        {
            "metadata": {"Data View ID": "dv-legacy-derived"},
            "metrics": [],
            "dimensions": [],
            "derived_fields": {"fields": [{"component_id": "variables/legacy"}]},
            "segments": {
                "segments": [
                    {"segment_id": "s", f"{scope}_references": ["variables/legacy", "legacy"]}
                ]
            },
        }
    )
    graph = build_reference_graph(impl)
    assert graph["edges"] == [
        {"source": "s", "target": "variables/legacy", "kind": "references"},
    ]
    # An absent functional kind cannot authorize a typed shortened match.
    assert graph["unresolved"] == [
        {"source": "s", "reference": "legacy", "reference_type": scope, "reason": "missing"},
    ]


@pytest.mark.parametrize("scope", ["metric", "dimension"])
def test_short_references_do_not_link_duplicate_ids_across_types(scope):
    impl = cja_adapt(
        {
            "metadata": {"Data View ID": "dv-duplicate-id"},
            "metrics": [{"id": "shared/url", "name": "Metric URL"}],
            "dimensions": [{"id": "shared/url", "name": "Dimension URL"}],
            "segments": {"segments": [{"segment_id": "s", f"{scope}_references": ["url"]}]},
        }
    )
    graph = build_reference_graph(impl)
    assert graph["edges"] == []
    assert graph["out_degree"]["s"] == 0
    assert graph["unresolved"] == [
        {"source": "s", "reference": "url", "reference_type": scope, "reason": "ambiguous"},
    ]
    # The patch does not redesign the existing duplicate-ID exact-match contract.
    impl.segments[0].reference_types = {scope: ["shared/url"]}
    impl.segments[0].references = ["shared/url"]
    assert len(build_reference_graph(impl)["edges"]) == 1
