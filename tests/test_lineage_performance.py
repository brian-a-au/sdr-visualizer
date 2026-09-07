"""Provisional, synthetic-only performance policy for the lineage POC."""

from __future__ import annotations

import json
from itertools import count
from pathlib import Path

import pytest
import yaml

from scripts import perf_lineage_poc
from scripts.perf_lineage_poc import (
    HTML_SIZE_BUDGET_BYTES,
    MEDIAN_BUILD_BUDGET_SECONDS,
    _prepared_entry_count,
    build_synthetic_evidence,
    generate_representative_discovery,
    generate_scale_topology,
)
from sdr_visualizer.adapters.cja_lineage import adapt
from sdr_visualizer.analysis.lineage_layout import (
    FULL_GRAPH_EDGE_LIMIT,
    FULL_GRAPH_NODE_LIMIT,
    build_lineage_layout,
)
from sdr_visualizer.render.lineage_payload import build_payload


def test_representative_generator_is_deterministic_and_exercises_shape() -> None:
    first = generate_representative_discovery()
    second = generate_representative_discovery()

    assert first == second
    topology = adapt(first, scope_label="Synthetic performance scope")
    assert len(topology.connections) >= 3
    assert len({view.name for view in topology.data_views}) < len(topology.data_views)
    assert max(len(connection.dataset_ids) for connection in topology.connections) > min(
        len(connection.dataset_ids) for connection in topology.connections
    )
    assert (
        max(
            sum(edge.connection_id == connection.id for edge in topology.connection_data_views)
            for connection in topology.connections
        )
        > 1
    )
    assert any(connection.name is None for connection in topology.connections)
    assert any(view.connection_id is None for view in topology.data_views)


@pytest.mark.parametrize(
    ("datasets", "connections", "data_views", "dataset_edges", "expected_gated"),
    [
        (550, 25, 425, 550, False),
        (551, 25, 425, 551, True),
        (484, 16, 256, 7_744, False),
        (484, 16, 257, 7_744, True),
    ],
)
def test_full_graph_gate_is_strictly_over_the_provisional_limits(
    datasets: int,
    connections: int,
    data_views: int,
    dataset_edges: int,
    expected_gated: bool,
) -> None:
    topology = generate_scale_topology(
        dataset_count=datasets,
        connection_count=connections,
        data_view_count=data_views,
        dataset_connection_edge_count=dataset_edges,
    )
    layout = build_lineage_layout(topology)

    assert len(layout.global_layout.nodes) == datasets + connections + data_views
    assert len(layout.global_layout.edges) == dataset_edges + data_views
    assert layout.full_graph_gated is expected_gated
    assert layout.full_graph_gated is (
        len(layout.global_layout.nodes) > FULL_GRAPH_NODE_LIMIT
        or len(layout.global_layout.edges) > FULL_GRAPH_EDGE_LIMIT
    )


@pytest.mark.parametrize(
    ("datasets", "connections", "data_views", "dataset_edges"),
    [(80, 8, 120, 320), (160, 16, 240, 640)],
)
def test_prepared_geometry_and_adjacency_are_linear_in_vertices_plus_edges(
    datasets: int,
    connections: int,
    data_views: int,
    dataset_edges: int,
) -> None:
    topology = generate_scale_topology(
        dataset_count=datasets,
        connection_count=connections,
        data_view_count=data_views,
        dataset_connection_edge_count=dataset_edges,
    )
    payload = build_payload(topology)
    vertices = datasets + connections + data_views
    edges = dataset_edges + data_views

    assert _prepared_entry_count(payload) <= 5 * (vertices + edges) + connections


def test_synthetic_evidence_meets_size_and_structure_budgets_and_is_sanitized(
    monkeypatch,
) -> None:
    # Coverage instrumentation distorts wall-clock build time. The standalone
    # perf_lineage_poc.py gate in test.yml and release.yml owns real timing;
    # keep exercising the full build here for size, structure, and coverage.
    clock = count(step=0.25)
    monkeypatch.setattr(perf_lineage_poc, "perf_counter", lambda: next(clock))
    evidence = build_synthetic_evidence(repeats=3)

    assert evidence
    for metrics in evidence.values():
        assert metrics["median_seconds"] < MEDIAN_BUILD_BUDGET_SECONDS
        assert metrics["html_bytes"] < HTML_SIZE_BUDGET_BYTES
        assert (
            metrics["prepared_entries"]
            <= 5 * (metrics["nodes"] + metrics["edges"]) + metrics["connections"]
        )

    serialized = json.dumps(evidence, sort_keys=True)
    assert "Synthetic performance scope" not in serialized
    assert "dataset-" not in serialized
    assert "connection-" not in serialized
    assert "data-view-" not in serialized


@pytest.mark.parametrize("seconds", [MEDIAN_BUILD_BUDGET_SECONDS, 3.0])
def test_synthetic_timing_gate_rejects_median_at_or_above_budget(monkeypatch, seconds):
    monkeypatch.setattr(
        perf_lineage_poc,
        "_measure",
        lambda *_args, **_kwargs: {"full_graph_gated_count": 0, "median_seconds": seconds},
    )

    with pytest.raises(RuntimeError, match="synthetic timing budget exceeded"):
        build_synthetic_evidence()
    assert perf_lineage_poc.main([]) == 1


@pytest.mark.parametrize("workflow_name", ["test.yml", "release.yml"])
def test_real_lineage_timing_remains_a_blocking_standalone_gate(workflow_name):
    workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows" / workflow_name
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"]["browser-perf"]
    gates = [step for step in job["steps"] if step.get("name") == "Lineage performance gate"]

    assert len(gates) == 1
    assert gates[0]["run"] == "uv run python scripts/perf_lineage_poc.py"
    for settings in (job, gates[0]):
        assert settings.get("continue-on-error", False) is False
        assert "if" not in settings
    if workflow_name == "release.yml":
        assert workflow["jobs"]["build"]["needs"] == "browser-perf"
