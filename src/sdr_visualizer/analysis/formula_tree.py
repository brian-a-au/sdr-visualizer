"""Calculated-metric formula -> renderable tree.

Two operand shapes show up in the wild:

  CJA: {"func": "divide", "col1": {...}, "col2": {...}}
  AA : {"func": "divide", "args": ["metrics/orders", "metrics/visits"]}

Operands can be:
  - metric refs   ({"func": "metric", "name": "metrics/x"} or a bare
                   "metrics/x" string in the AA shape)
  - constants     (numeric or string literals)
  - sub-formulas  (another binary op)
  - segment scopes ({"func": "segment", "name": "segments/x", "col": {...}})
"""

from __future__ import annotations

from typing import Any

from sdr_visualizer.core.models import CalculatedMetric

BINARY_OPS = {"divide", "multiply", "subtract", "add"}
NARY_OPS = {"sum", "product", "min", "max", "mean", "median"}


def parse_formula_tree(metric: CalculatedMetric) -> dict[str, Any]:
    return _walk(metric.formula or {})


def _walk(node: Any) -> dict[str, Any]:
    if isinstance(node, str):
        if node.startswith(("metrics/", "variables/")):
            return _metric_ref(node, node)
        return {"kind": "constant", "value": node}

    if isinstance(node, (int, float)):
        return {"kind": "constant", "value": node}

    if not isinstance(node, dict):
        return _unknown(node)

    func = node.get("func")

    if func == "metric":
        name = node.get("name") or ""
        return _metric_ref(name, name)

    if func == "segment":
        inner = node.get("col") or node.get("formula") or {}
        return {
            "kind": "segment_scope",
            "segment_id": node.get("name") or "",
            "child": _walk(inner),
        }

    if func in BINARY_OPS:
        col1 = node.get("col1")
        col2 = node.get("col2")
        if col1 is not None or col2 is not None:
            return {
                "kind": "operation",
                "op": func,
                "args": [_walk(col1), _walk(col2)],
            }
        return _operation(func, node.get("args") or [])

    if func in NARY_OPS:
        return _operation(func, node.get("args") or [])

    if "formula" in node and isinstance(node["formula"], dict):
        return _walk(node["formula"])

    return _unknown(node)


def _operation(op: str, args: list[Any]) -> dict[str, Any]:
    return {
        "kind": "operation",
        "op": op,
        "args": [_walk(a) for a in args],
    }


def _metric_ref(metric_id: str, label: str) -> dict[str, Any]:
    return {"kind": "metric_ref", "metric_id": metric_id, "label": label}


def _unknown(node: Any) -> dict[str, Any]:
    func = None
    if isinstance(node, dict):
        func = node.get("func")
    return {
        "kind": "unknown",
        "func": str(func) if func else None,
        "raw_keys": sorted(node.keys()) if isinstance(node, dict) else [],
    }


def collect_metric_refs(tree: dict[str, Any]) -> list[str]:
    """Flatten a formula tree to the list of metric ids it references."""
    refs: list[str] = []
    seen: set[str] = set()

    def visit(node: dict[str, Any]) -> None:
        kind = node.get("kind")
        if kind == "metric_ref":
            mid = node.get("metric_id")
            if mid and mid not in seen:
                seen.add(mid)
                refs.append(mid)
        elif kind == "operation":
            for arg in node.get("args", []):
                if isinstance(arg, dict):
                    visit(arg)
        elif kind == "segment_scope":
            child = node.get("child")
            if isinstance(child, dict):
                visit(child)

    visit(tree)
    return refs
