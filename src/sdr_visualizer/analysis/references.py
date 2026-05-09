"""Reference graph builder.

Walks an Implementation and produces a graph of components and the directed
edges between them. Segments and calculated metrics already carry an explicit
`references` list (computed by the adapters); this module turns those plus
the component inventory into nodes/edges with degree counts so the renderer
can size graph nodes and the catalog can show "references-to" counts without
re-walking the data on the client.

Output is a plain dict (JSON-serializable) so it can be embedded in the HTML
payload directly.
"""

from __future__ import annotations

from typing import Any

from sdr_visualizer.core.models import Implementation


def build_reference_graph(impl: Implementation) -> dict[str, Any]:
    """Return {nodes: [...], edges: [...], in_degree: {...}, out_degree: {...}}.

    Each node has {id, type, label}. Each edge has {source, target, kind}.
    `in_degree` and `out_degree` are flat id -> int maps so the renderer can
    look up reference counts in O(1).
    """
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_node(component_id: str, type_: str, label: str) -> None:
        if component_id in seen:
            return
        seen.add(component_id)
        nodes.append({"id": component_id, "type": type_, "label": label})

    for m in impl.metrics:
        add_node(m.id, "metric", m.name)
    for d in impl.dimensions:
        add_node(d.id, "dimension", d.name)
    for df in impl.derived_fields:
        add_node(df.id, "derived_field", df.name)
    for s in impl.segments:
        add_node(s.id, "segment", s.name)
    for cm in impl.calculated_metrics:
        add_node(cm.id, "calculated_metric", cm.name)

    edges: list[dict[str, Any]] = []
    in_degree: dict[str, int] = {n["id"]: 0 for n in nodes}
    out_degree: dict[str, int] = {n["id"]: 0 for n in nodes}

    def add_edge(source: str, target: str, kind: str) -> None:
        # Skip dangling references — the target isn't in the inventory, so
        # there's no node to draw. The catalog can still surface the dangle
        # via the raw segment.references list if it wants.
        if target not in seen:
            return
        edges.append({"source": source, "target": target, "kind": kind})
        out_degree[source] = out_degree.get(source, 0) + 1
        in_degree[target] = in_degree.get(target, 0) + 1

    for s in impl.segments:
        for ref in s.references:
            add_edge(s.id, ref, "references")
    for cm in impl.calculated_metrics:
        for ref in cm.references:
            add_edge(cm.id, ref, "references")

    return {
        "nodes": nodes,
        "edges": edges,
        "in_degree": in_degree,
        "out_degree": out_degree,
    }
