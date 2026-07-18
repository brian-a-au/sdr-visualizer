"""Build the JSON payload embedded in the HTML output (SPEC-VISUALIZER §9).

The principle: do work in Python (where seconds are fine), not in JS (where
we have a millisecond budget). The payload is denormalized — pre-computed
reference counts, pre-flattened segment / formula trees. The client builds
its own search index at load from the embedded catalog entries.

The shape is documented as the consumer-facing contract; external tooling
that reads the embedded payload (or the `--json PATH` output) can rely on
it.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sdr_visualizer import __version__ as VISUALIZER_VERSION
from sdr_visualizer.analysis.formula_tree import parse_formula_tree
from sdr_visualizer.analysis.references import build_reference_graph
from sdr_visualizer.analysis.segment_tree import parse_segment_tree
from sdr_visualizer.core.models import (
    CalculatedMetric,
    Component,
    Implementation,
    Segment,
)


def build_payload(impl: Implementation) -> dict[str, Any]:
    """Return the full embedded payload dict."""
    graph = build_reference_graph(impl)
    in_degree = graph["in_degree"]
    out_degree = graph["out_degree"]

    components: list[dict[str, Any]] = []
    for c in impl.metrics:
        components.append(_component_node(c, "metric", in_degree, out_degree))
    for c in impl.dimensions:
        components.append(_component_node(c, "dimension", in_degree, out_degree))
    for c in impl.derived_fields:
        node = _component_node(c, "derived_field", in_degree, out_degree)
        kind = _derived_kind(c.platform_specific)
        if kind:
            node["derived_kind"] = kind
        components.append(node)

    segments = [_segment_node(s, in_degree, out_degree) for s in impl.segments]
    calc_metrics = [_calc_metric_node(c, in_degree, out_degree) for c in impl.calculated_metrics]

    segment_trees = {s.id: parse_segment_tree(s) for s in impl.segments}
    formula_trees = {c.id: parse_formula_tree(c) for c in impl.calculated_metrics}

    id_counts = Counter(e["id"] for e in (*components, *segments, *calc_metrics))
    duplicates = sorted(i for i, n in id_counts.items() if n > 1)
    if duplicates:
        shown = ", ".join(duplicates[:5])
        more = f" (+{len(duplicates) - 5} more)" if len(duplicates) > 5 else ""
        print(
            f"sdr-visualizer: warning: duplicate component ids in snapshot: {shown}{more}; "
            "anatomy trees for duplicated ids are last-writer-wins",
            file=sys.stderr,
        )

    return {
        "meta": {
            "instance_id": impl.instance_id,
            "instance_name": impl.instance_name,
            "platform": impl.platform,
            "snapshot_taken_at": impl.snapshot_taken_at,
            "snapshot_source": impl.snapshot_source,
            "adapter_version": impl.adapter_version,
            "visualizer_version": VISUALIZER_VERSION,
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "component_count": len(components) + len(segments) + len(calc_metrics),
        },
        "components": components,
        "segments": segments,
        "calculated_metrics": calc_metrics,
        # Only edges ship; nodes and degree maps are derivable from the
        # catalog entries (which carry id/type/name/in_degree/out_degree).
        "graph": {"edges": graph["edges"]},
        "segment_trees": segment_trees,
        "formula_trees": formula_trees,
    }


def _epoch_ms(value: Any) -> int | None:
    """Parse ISO 8601 (incl. trailing Z) or 'YYYY-MM-DD HH:MM:SS' to epoch ms.

    Precomputed server-side so the client never constructs Date objects in
    sort comparators or filter passes. Naive timestamps are assumed UTC.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def _compact(node: dict[str, Any]) -> dict[str, Any]:
    """Drop null / empty-collection / empty-string fields before embedding.

    The client JS guards every optional read (`entry.tags || []` etc.), so
    omitting the keys is safe and saves ~15 bytes per omitted field. Numeric
    zeros (in_degree, complexity_score) are deliberately kept.
    """
    return {k: v for k, v in node.items() if v is not None and v != "" and v != [] and v != {}}


def _component_node(
    c: Component,
    type_: str,
    in_degree: dict[str, int],
    out_degree: dict[str, int],
) -> dict[str, Any]:
    return _compact(
        {
            "id": c.id,
            "type": type_,
            "name": c.name,
            "description": c.description,
            "data_type": c.data_type,
            "polarity": c.polarity,
            "tags": c.tags,
            "owner": c.owner,
            "created_at": c.created_at,
            "modified_at": c.modified_at,
            "modified_ts": _epoch_ms(c.modified_at),
            "in_degree": in_degree.get(c.id, 0),
            "out_degree": out_degree.get(c.id, 0),
        }
    )


def _derived_kind(platform_specific: dict | None) -> str | None:
    """A CJA derived field surfaces in the data view as a dimension or a
    metric, and real cja_auto_sdr records declare which via component_type
    ("Dimension" | "Metric"). Normalize the declared value; anything else
    (legacy "derived_field", absent) yields no kind — declared only,
    never inferred."""
    declared = str((platform_specific or {}).get("component_type") or "").strip().lower()
    return declared if declared in ("dimension", "metric") else None


def _segment_node(
    s: Segment, in_degree: dict[str, int], out_degree: dict[str, int]
) -> dict[str, Any]:
    return _compact(
        {
            "id": s.id,
            "type": "segment",
            "name": s.name,
            "description": s.description,
            "nesting_depth": s.nesting_depth,
            "container_types": s.container_types,
            "references": s.references,
            "owner": s.owner,
            "created_at": s.created_at,
            "modified_at": s.modified_at,
            "modified_ts": _epoch_ms(s.modified_at),
            "in_degree": in_degree.get(s.id, 0),
            "out_degree": out_degree.get(s.id, 0),
        }
    )


def _calc_metric_node(
    c: CalculatedMetric, in_degree: dict[str, int], out_degree: dict[str, int]
) -> dict[str, Any]:
    return _compact(
        {
            "id": c.id,
            "type": "calculated_metric",
            "name": c.name,
            "description": c.description,
            "formula_text": c.formula_text,
            "attribution_model": c.attribution_model,
            "allocation": c.allocation,
            "complexity_score": c.complexity_score,
            "references": c.references,
            "owner": c.owner,
            "created_at": c.created_at,
            "modified_at": c.modified_at,
            "modified_ts": _epoch_ms(c.modified_at),
            "in_degree": in_degree.get(c.id, 0),
            "out_degree": out_degree.get(c.id, 0),
        }
    )
