"""Segment definition -> renderable tree.

Both CJA and AA segment definitions share a common spine: a nested chain of
`container` nodes (each with a `context` like "event"/"session" or
"hits"/"visits"/"visitors") that bottoms out at a predicate. Predicates can
be logical combinators (`and`/`or`/`not`), comparison leaves (`streq`/`eq`/
`gt`/...), or references to other segments.

The output is a single root node, encoded as a plain dict so it serializes
directly into the HTML payload. Each node carries a `kind` discriminator the
client renderer switches on:

  - container : a nesting box scoped to a specific context
  - logical   : and / or / not over child nodes
  - criterion : a leaf comparison ("dimension X equals Y")
  - segment_ref : an inline reference to another segment
  - unknown   : fallback for shapes we don't understand yet, with the raw
                func name preserved so the renderer can show *something*
                instead of silently dropping the node
"""

from __future__ import annotations

from typing import Any

from sdr_visualizer.core.models import Segment

LOGICAL_OPS = {"and", "or", "not", "without"}
COMPARISON_OPS = {
    "eq",
    "ne",
    "neq",
    "streq",
    "strne",
    "contains",
    "not-contains",
    "starts-with",
    "ends-with",
    "lt",
    "le",
    "lte",
    "gt",
    "ge",
    "gte",
    "between",
    "exists",
    "dne",
    "not-exists",
    "exists-attr",
}


def parse_segment_tree(segment: Segment) -> dict[str, Any]:
    """Return a tree dict suitable for embedding in the HTML payload."""
    return _walk(segment.definition or {})


def _walk(node: Any) -> dict[str, Any]:
    if not isinstance(node, dict):
        return _unknown(node)

    func = node.get("func")

    if func == "container":
        return _container(node)
    if func in LOGICAL_OPS:
        return _logical(node, func)
    if func == "segment" and not any(
        isinstance(node.get(k), dict) for k in ("container", "pred", "definition")
    ):
        return {
            "kind": "segment_ref",
            "segment_id": node.get("name") or node.get("id") or "",
        }
    if func in COMPARISON_OPS:
        return _criterion(node, func)

    # Some definitions wrap the real tree in an extra layer (e.g. an AA
    # `definition` dict whose `container` key holds the actual root). Unwrap
    # if exactly one well-known child key is present.
    for wrapper_key in ("container", "pred", "definition"):
        if wrapper_key in node and isinstance(node[wrapper_key], dict):
            inner = _walk(node[wrapper_key])
            # Don't lose context info from the wrapper node itself if it had a
            # `context`. Wrap it in a container so the visual hierarchy stays.
            if node.get("context") and inner.get("kind") != "container":
                return {
                    "kind": "container",
                    "context": str(node["context"]),
                    "child": inner,
                }
            return inner

    return _unknown(node)


def _container(node: dict[str, Any]) -> dict[str, Any]:
    context = node.get("context") or "unspecified"
    pred = node.get("pred")
    child = _walk(pred) if pred is not None else _unknown({})
    return {
        "kind": "container",
        "context": str(context),
        "child": child,
    }


def _logical(node: dict[str, Any], op: str) -> dict[str, Any]:
    raw_children = node.get("args") or node.get("preds") or []
    if not isinstance(raw_children, list):
        raw_children = [raw_children]
    # CJA's `not` shape often nests a single `pred` rather than `args`.
    if not raw_children and "pred" in node:
        raw_children = [node["pred"]]
    children = [_walk(c) for c in raw_children]
    return {
        "kind": "logical",
        "op": op,
        "children": children,
    }


def _criterion(node: dict[str, Any], op: str) -> dict[str, Any]:
    """A leaf comparison. Tries both the CJA shape (`val` is a dict that
    points to an attr) and the AA shape (`val` is a literal string)."""
    target_id, target_label = _criterion_target(node)
    value = _criterion_value(node)
    refs = [target_id] if target_id else []
    return {
        "kind": "criterion",
        "op": op,
        "target_id": target_id,
        "target_label": target_label,
        "value": value,
        "refs": refs,
        "summary": _criterion_summary(op, target_label, value),
    }


def _criterion_target(node: dict[str, Any]) -> tuple[str | None, str]:
    """Pull the dimension/metric reference out of a criterion node."""
    val = node.get("val")
    if isinstance(val, dict):
        if val.get("func") == "attr":
            return val.get("name"), str(val.get("name") or "attribute")
        if val.get("func") == "metric":
            return val.get("name"), str(val.get("name") or "metric")
    # AA criteria sometimes carry the dimension via the parent container's
    # context; if we get here we don't have a known target.
    return None, "value"


def _criterion_value(node: dict[str, Any]) -> Any:
    if "str" in node:
        return node["str"]
    if "num" in node:
        return node["num"]
    val = node.get("val")
    if not isinstance(val, dict):
        return val
    return None


def _criterion_summary(op: str, target_label: str, value: Any) -> str:
    op_label = {
        "eq": "equals",
        "neq": "≠",
        "ne": "≠",
        "streq": "equals",
        "strne": "≠",
        "lt": "<",
        "le": "≤",
        "lte": "≤",
        "gt": ">",
        "ge": "≥",
        "gte": "≥",
        "contains": "contains",
        "starts-with": "starts with",
        "ends-with": "ends with",
        "exists": "exists",
        "dne": "does not exist",
        "not-exists": "does not exist",
        "between": "between",
    }.get(op, op)
    if value is None:
        return f"{target_label} {op_label}"
    return f"{target_label} {op_label} {value!r}"


def _unknown(node: Any) -> dict[str, Any]:
    func = None
    if isinstance(node, dict):
        func = node.get("func")
    return {
        "kind": "unknown",
        "func": str(func) if func else None,
        "raw_keys": sorted(node.keys()) if isinstance(node, dict) else [],
    }
