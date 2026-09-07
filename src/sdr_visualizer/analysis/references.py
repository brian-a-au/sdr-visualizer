"""Snapshot-local reference graph with exact-first, type-scoped resolution."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sdr_visualizer.core.models import Implementation


def _short_id(component_id: str) -> str:
    """Match cja_auto_sdr's extract_short_name: slash takes priority over dot."""
    return (
        component_id.rsplit("/", 1)[-1] if "/" in component_id else component_id.rsplit(".", 1)[-1]
    )


def build_reference_graph(impl: Implementation) -> dict[str, Any]:
    """Build unique directed edges, degrees, and unresolved-reference diagnostics.

    Exact IDs win within the declared reference type. Only CJA shortened IDs
    get a fallback, using the upstream shortening rule on inventory IDs (never
    shortening a missing full reference). Untyped references require uniqueness
    across the whole snapshot. No definitions or indirect dependencies are read.
    """
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    identity_types: dict[str, set[str]] = defaultdict(set)
    exact: dict[str | None, set[str]] = defaultdict(set)
    aliases: dict[tuple[str | None, str], set[str]] = defaultdict(set)

    def add_node(component_id: str, type_: str, label: str, reference_type: str) -> None:
        identity_types[component_id].add(reference_type)
        for scope in (None, reference_type):
            exact[scope].add(component_id)
            if impl.platform == "cja":
                aliases[scope, _short_id(component_id)].add(component_id)
        if component_id not in seen:
            seen.add(component_id)
            nodes.append({"id": component_id, "type": type_, "label": label})

    for m in impl.metrics:
        add_node(m.id, "metric", m.name, "metric")
    for d in impl.dimensions:
        add_node(d.id, "dimension", d.name, "dimension")
    for df in impl.derived_fields:
        declared = str(df.platform_specific.get("component_type") or "").strip().lower()
        scope = declared if declared in ("metric", "dimension") else "derived_field"
        add_node(df.id, "derived_field", df.name, scope)
        if scope == "derived_field":
            # Legacy inventories omit functional kind. Preserve exact links,
            # but do not make their shortened IDs eligible for typed matching.
            exact["metric"].add(df.id)
            exact["dimension"].add(df.id)
    for s in impl.segments:
        add_node(s.id, "segment", s.name, "segment")
    for cm in impl.calculated_metrics:
        add_node(cm.id, "calculated_metric", cm.name, "metric")

    # The browser addresses nodes by ID alone. A new alias must not point at
    # an ID shared by incompatible kinds; derived echoes may share one kind.
    ambiguous_ids = {
        id_ for id_, kinds in identity_types.items() if len(kinds - {"derived_field"}) > 1
    }
    edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str]] = set()
    ref_keys: set[tuple[str, str, str | None]] = set()
    in_degree = dict.fromkeys(seen, 0)
    out_degree = dict.fromkeys(seen, 0)

    def add_reference(source: str, ref: str, scope: str | None = None) -> None:
        key = (source, ref, scope)
        if key in ref_keys:
            return
        ref_keys.add(key)
        exact_match = ref in exact[scope]
        if exact_match:
            targets = {ref}
        elif impl.platform == "cja":
            targets = aliases.get((scope, ref), set())
        else:
            targets = set()
        if len(targets) != 1 or (not exact_match and targets & ambiguous_ids):
            diagnostic = {
                "source": source,
                "reference": ref,
                "reason": "ambiguous" if targets else "missing",
            }
            if scope:
                diagnostic["reference_type"] = scope
            unresolved.append(diagnostic)
            return
        target = next(iter(targets))
        if (source, target) not in edge_keys:
            edge_keys.add((source, target))
            edges.append({"source": source, "target": target, "kind": "references"})
            out_degree[source] += 1
            in_degree[target] += 1

    for component in [*impl.segments, *impl.calculated_metrics]:
        typed_refs: set[str] = set()
        for scope, refs in component.reference_types.items():
            for ref in refs:
                add_reference(component.id, ref, scope)
                typed_refs.add(ref)
        for ref in component.references:
            if ref not in typed_refs:
                add_reference(component.id, ref)
    for df in impl.derived_fields:
        references = df.platform_specific.get("component_references", [])
        if isinstance(references, list):
            for ref in references:
                if isinstance(ref, str):
                    add_reference(df.id, ref)

    return {
        "nodes": nodes,
        "edges": edges,
        "in_degree": in_degree,
        "out_degree": out_degree,
        "unresolved": unresolved,
    }
