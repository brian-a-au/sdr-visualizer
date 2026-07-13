"""Trend section builder (0.5.0 trend mode).

Turns an ordered list of normalized Implementations (oldest to newest) into
the payload `trend` section: one aggregate row per snapshot and one pairwise
change interval per adjacent pair, reusing the 0.4.0 diff engine. Pure over
the normalized model — no file IO, no platform logic (the CLI handles both).

Aggregates are descriptive facts the catalog already exposes as filters
(counts, orphans by in-degree, missing descriptions, reference edges); no
judgment is attached to any of them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sdr_visualizer.analysis.diff import diff_implementations
from sdr_visualizer.analysis.references import build_reference_graph
from sdr_visualizer.core.models import Implementation


def compute_aggregates(impl: Implementation) -> dict[str, int]:
    """One row of descriptive counts for a single snapshot."""
    graph = build_reference_graph(impl)
    in_degree = graph["in_degree"]
    entries = [
        *impl.metrics,
        *impl.dimensions,
        *impl.derived_fields,
        *impl.segments,
        *impl.calculated_metrics,
    ]
    return {
        "total": len(entries),
        "metrics": len(impl.metrics),
        "dimensions": len(impl.dimensions),
        "derived_fields": len(impl.derived_fields),
        "segments": len(impl.segments),
        "calculated_metrics": len(impl.calculated_metrics),
        "orphans": sum(1 for e in entries if in_degree.get(e.id, 0) == 0),
        "no_description": sum(1 for e in entries if not e.description),
        "edges": len(graph["edges"]),
    }


def build_trend(impls: list[Implementation], *, capped: bool) -> dict[str, Any]:
    """Return the payload `trend` section for an ordered snapshot series."""
    snapshots = [
        {
            "source": impl.snapshot_source,
            "taken_at": impl.snapshot_taken_at,
            "aggregates": compute_aggregates(impl),
        }
        for impl in impls
    ]
    intervals = []
    for prev, curr in zip(impls, impls[1:], strict=False):
        diff = diff_implementations(prev, curr)
        intervals.append(
            {
                "from": prev.snapshot_taken_at or prev.snapshot_source,
                "to": curr.snapshot_taken_at or curr.snapshot_source,
                "from_source": Path(prev.snapshot_source).name,
                "to_source": Path(curr.snapshot_source).name,
                "added": [e["id"] for e in diff["added"]],
                "removed": [e["id"] for e in diff["removed"]],
                "modified": [e["id"] for e in diff["modified"]],
            }
        )
    return {"snapshots": snapshots, "intervals": intervals, "capped": capped}
