"""Synthetic-only performance evidence for the private CJA lineage POC.

This policy is intentionally separate from ``docs/PERFORMANCE.md``.  It emits
only aggregate counts, timings, and sizes; synthetic labels and identifiers
never enter terminal output.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from sdr_visualizer.adapters.cja_lineage import adapt  # noqa: E402
from sdr_visualizer.core.lineage import (  # noqa: E402
    Availability,
    ConnectionDataView,
    Coverage,
    DatasetConnection,
    LineageConnection,
    LineageDataset,
    LineageDataView,
    LineageTopology,
)
from sdr_visualizer.render.lineage_payload import build_payload  # noqa: E402
from sdr_visualizer.render.lineage_renderer import render_payload  # noqa: E402

MEDIAN_BUILD_BUDGET_SECONDS = 2.0
HTML_SIZE_BUDGET_BYTES = 12 * 1024 * 1024
DEFAULT_REPEATS = 3
_SCOPE_LABEL = "Synthetic performance scope"


def generate_representative_discovery() -> dict[str, Any]:
    """Return a deterministic discovery shape with representative topology."""
    records: list[dict[str, Any]] = []
    shapes = ((10, 19), (2, 3))
    for connection_index, (dataset_count, view_count) in enumerate(shapes):
        datasets = [
            {
                "id": f"dataset-{connection_index:02d}-{index:03d}",
                "name": f"Repeated dataset name {index % 4}",
            }
            for index in range(dataset_count)
        ]
        for view_index in range(view_count):
            records.append(
                {
                    "id": f"data-view-{connection_index:02d}-{view_index:03d}",
                    "name": f"Repeated data view name {view_index % 5}",
                    "connection": {
                        "id": f"connection-{connection_index:02d}",
                        "name": f"Repeated connection name {connection_index % 2}",
                    },
                    "datasets": datasets,
                }
            )
    records.extend(
        (
            {
                "id": "data-view-degraded",
                "name": "Repeated data view name 0",
                "connection": {"id": "connection-degraded", "name": None},
                "datasets": [],
            },
            {
                "id": "data-view-missing-parent",
                "name": "Repeated data view name 0",
                "connection": {"id": None, "name": None},
                "datasets": [],
            },
        )
    )
    return {
        "dataViews": records,
        "count": len(records),
        "warning": "Synthetic permission-degraded marker",
    }


def generate_scale_topology(
    *,
    dataset_count: int,
    connection_count: int,
    data_view_count: int,
    dataset_connection_edge_count: int,
) -> LineageTopology:
    """Build a deterministic model-direct topology with an exact edge count."""
    if (
        min(dataset_count, connection_count, data_view_count) < 0
        or connection_count == 0
        or dataset_connection_edge_count < 0
        or dataset_connection_edge_count > dataset_count * connection_count
    ):
        raise ValueError("invalid synthetic topology dimensions")

    dataset_ids = tuple(f"dataset-{index:04d}" for index in range(dataset_count))
    connection_ids = tuple(f"connection-{index:04d}" for index in range(connection_count))
    data_view_ids = tuple(f"data-view-{index:04d}" for index in range(data_view_count))
    # Connection-major ordering deliberately creates uneven fan-in when the
    # requested edge count is not divisible by the dataset count.
    pairs = tuple(
        (dataset_id, connection_id)
        for connection_id in connection_ids
        for dataset_id in dataset_ids
    )[:dataset_connection_edge_count]
    datasets_by_connection: dict[str, list[str]] = {
        connection_id: [] for connection_id in connection_ids
    }
    for dataset_id, connection_id in pairs:
        datasets_by_connection[connection_id].append(dataset_id)

    datasets = tuple(
        LineageDataset(dataset_id, f"Repeated dataset name {index % 31}", (index,))
        for index, dataset_id in enumerate(dataset_ids)
    )
    connections = tuple(
        LineageConnection(
            connection_id,
            f"Repeated connection name {index % 7}",
            Availability.AVAILABLE,
            (
                Availability.AVAILABLE
                if datasets_by_connection[connection_id]
                else Availability.REPORTED_EMPTY
            ),
            tuple(datasets_by_connection[connection_id]),
            (index,),
        )
        for index, connection_id in enumerate(connection_ids)
    )
    data_views = tuple(
        LineageDataView(
            data_view_id,
            f"Repeated data view name {index % 37}",
            connection_ids[index % connection_count],
            Availability.AVAILABLE,
            (
                Availability.AVAILABLE
                if datasets_by_connection[connection_ids[index % connection_count]]
                else Availability.REPORTED_EMPTY
            ),
            (index,),
        )
        for index, data_view_id in enumerate(data_view_ids)
    )
    return LineageTopology(
        scope_label=_SCOPE_LABEL,
        coverage=Coverage.ACCESSIBLE_SCOPE,
        datasets=datasets,
        connections=connections,
        data_views=data_views,
        dataset_connections=tuple(
            DatasetConnection(dataset_id, connection_id, (index,))
            for index, (dataset_id, connection_id) in enumerate(pairs)
        ),
        connection_data_views=tuple(
            ConnectionDataView(view.connection_id, view.id, (index,))
            for index, view in enumerate(data_views)
            if view.connection_id is not None
        ),
    )


def _prepared_entry_count(payload: dict[str, Any]) -> int:
    """Count prepared geometry and adjacency references without content."""
    geometry = payload["geometry"]
    canvases = (geometry["global"], *geometry["local_by_connection"])
    geometry_entries = sum(len(canvas["nodes"]) + len(canvas["edges"]) for canvas in canvases)
    adjacency = payload["adjacency"]
    adjacency_entries = sum(
        len(values) for values in adjacency["dataset_ids_by_connection"].values()
    ) + sum(len(values) for values in adjacency["data_view_ids_by_connection"].values())
    return geometry_entries + adjacency_entries


def _measure(factory: Callable[[], LineageTopology], *, repeats: int) -> dict[str, int | float]:
    samples: list[float] = []
    payload: dict[str, Any] | None = None
    html = ""
    for _ in range(repeats):
        started = perf_counter()
        topology = factory()
        payload = build_payload(topology)
        html = render_payload(payload)
        samples.append(perf_counter() - started)
    assert payload is not None
    counts = payload["counts"]
    return {
        "datasets": counts["datasets"],
        "connections": counts["connections"],
        "data_views": counts["data_views"],
        "nodes": counts["datasets"] + counts["connections"] + counts["data_views"],
        "edges": counts["edges"],
        "full_graph_gated_count": int(payload["gating"]["full_graph_gated"]),
        "prepared_entries": _prepared_entry_count(payload),
        "median_seconds": statistics.median(samples),
        "html_bytes": len(html.encode("utf-8")),
    }


def build_synthetic_evidence(*, repeats: int = DEFAULT_REPEATS) -> dict[str, dict[str, Any]]:
    """Measure normalized and model-direct cases and enforce POC-only budgets."""
    if repeats < 1:
        raise ValueError("repeats must be positive")
    cases: tuple[tuple[str, Callable[[], LineageTopology], bool], ...] = (
        (
            "representative",
            lambda: adapt(generate_representative_discovery(), scope_label=_SCOPE_LABEL),
            False,
        ),
        (
            "node_boundary",
            lambda: generate_scale_topology(
                dataset_count=550,
                connection_count=25,
                data_view_count=425,
                dataset_connection_edge_count=550,
            ),
            False,
        ),
        (
            "node_over",
            lambda: generate_scale_topology(
                dataset_count=551,
                connection_count=25,
                data_view_count=425,
                dataset_connection_edge_count=551,
            ),
            True,
        ),
        (
            "edge_boundary",
            lambda: generate_scale_topology(
                dataset_count=484,
                connection_count=16,
                data_view_count=256,
                dataset_connection_edge_count=7_744,
            ),
            False,
        ),
        (
            "edge_over",
            lambda: generate_scale_topology(
                dataset_count=484,
                connection_count=16,
                data_view_count=257,
                dataset_connection_edge_count=7_744,
            ),
            True,
        ),
    )
    evidence = {label: _measure(factory, repeats=repeats) for label, factory, _expected in cases}
    for label, _factory, expected_gated in cases:
        metrics = evidence[label]
        if metrics["full_graph_gated_count"] != int(expected_gated):
            raise RuntimeError("synthetic gate evidence failed")
        if metrics["median_seconds"] >= MEDIAN_BUILD_BUDGET_SECONDS:
            raise RuntimeError("synthetic timing budget exceeded")
        if metrics["html_bytes"] >= HTML_SIZE_BUDGET_BYTES:
            raise RuntimeError("synthetic size budget exceeded")
        if metrics["prepared_entries"] > 5 * (metrics["nodes"] + metrics["edges"]):
            raise RuntimeError("synthetic linearity budget exceeded")
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run synthetic CJA lineage POC evidence")
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    args = parser.parse_args(argv)
    try:
        evidence = build_synthetic_evidence(repeats=args.repeats)
    except (RuntimeError, ValueError):
        print("lineage POC synthetic evidence failed", file=sys.stderr)
        return 1
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "HTML_SIZE_BUDGET_BYTES",
    "MEDIAN_BUILD_BUDGET_SECONDS",
    "build_synthetic_evidence",
    "generate_representative_discovery",
    "generate_scale_topology",
    "main",
]
