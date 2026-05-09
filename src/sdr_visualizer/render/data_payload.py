"""Build the JSON payload embedded in the HTML output (SPEC-VISUALIZER §9).

The principle: do work in Python (where seconds are fine), not in JS (where
we have a millisecond budget). The payload is denormalized — pre-computed
reference counts, pre-flattened segment / formula trees, lowercased index
fields for substring search.

The shape is documented as the consumer-facing contract; external tooling
that reads the embedded payload (or the `--json PATH` output) can rely on
it.
"""

from __future__ import annotations

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
        components.append(_component_node(c, "derived_field", in_degree, out_degree))

    segments = [_segment_node(s, in_degree, out_degree) for s in impl.segments]
    calc_metrics = [_calc_metric_node(c, in_degree, out_degree) for c in impl.calculated_metrics]

    by_id: dict[str, dict[str, Any]] = {}
    for entry in [*components, *segments, *calc_metrics]:
        by_id[entry["id"]] = _index_entry(entry)

    segment_trees = {s.id: parse_segment_tree(s) for s in impl.segments}
    formula_trees = {c.id: parse_formula_tree(c) for c in impl.calculated_metrics}

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
        "graph": graph,
        "catalog_index": {"by_id": by_id},
        "segment_trees": segment_trees,
        "formula_trees": formula_trees,
    }


def _component_node(
    c: Component,
    type_: str,
    in_degree: dict[str, int],
    out_degree: dict[str, int],
) -> dict[str, Any]:
    return {
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
        "in_degree": in_degree.get(c.id, 0),
        "out_degree": out_degree.get(c.id, 0),
        "platform_specific": c.platform_specific,
    }


def _segment_node(
    s: Segment, in_degree: dict[str, int], out_degree: dict[str, int]
) -> dict[str, Any]:
    return {
        "id": s.id,
        "type": "segment",
        "name": s.name,
        "description": s.description,
        "nesting_depth": s.nesting_depth,
        "container_types": s.container_types,
        "references": s.references,
        "tags": [],
        "owner": s.owner,
        "created_at": s.created_at,
        "modified_at": s.modified_at,
        "in_degree": in_degree.get(s.id, 0),
        "out_degree": out_degree.get(s.id, 0),
    }


def _calc_metric_node(
    c: CalculatedMetric, in_degree: dict[str, int], out_degree: dict[str, int]
) -> dict[str, Any]:
    return {
        "id": c.id,
        "type": "calculated_metric",
        "name": c.name,
        "description": c.description,
        "formula_text": c.formula_text,
        "attribution_model": c.attribution_model,
        "allocation": c.allocation,
        "complexity_score": c.complexity_score,
        "references": c.references,
        "tags": [],
        "owner": c.owner,
        "created_at": c.created_at,
        "modified_at": c.modified_at,
        "in_degree": in_degree.get(c.id, 0),
        "out_degree": out_degree.get(c.id, 0),
    }


def _index_entry(node: dict[str, Any]) -> dict[str, Any]:
    """Lowercased searchable text for fast substring matching on the client."""
    bits = [
        str(node.get("id") or ""),
        str(node.get("name") or ""),
        str(node.get("description") or ""),
        str(node.get("formula_text") or ""),
        " ".join(node.get("tags") or []),
    ]
    return {
        "search": " ".join(bits).lower(),
        "type": node["type"],
        "tags": node.get("tags") or [],
    }
