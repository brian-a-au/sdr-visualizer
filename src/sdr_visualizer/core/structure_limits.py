"""Iterative structure budgets for untrusted snapshot and definition JSON."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sdr_visualizer.core.exceptions import InvalidSnapshotError

MAX_STRUCTURE_DEPTH = 100
MAX_STRUCTURE_NODES = 250_000
MAX_DEFINITION_NODES = 10_000


def _iter_structure(value: Any) -> Iterator[tuple[Any, int]]:
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        yield node, depth
        if isinstance(node, dict):
            stack.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            stack.extend((child, depth + 1) for child in node)


def measure_structure(value: Any) -> tuple[int, int]:
    """Return ``(node_count, maximum_depth)`` without recursive Python calls.

    Container keys are labels rather than child values and therefore do not
    consume nodes. The root is depth zero.
    """
    nodes = 0
    maximum_depth = 0
    for _node, depth in _iter_structure(value):
        nodes += 1
        maximum_depth = max(maximum_depth, depth)
    return nodes, maximum_depth


def validate_snapshot_structure(value: Any, *, label: str) -> None:
    """Reject a snapshot that exceeds the public input structure budget."""
    _validate_structure(
        value,
        label=label,
        max_depth=MAX_STRUCTURE_DEPTH,
        max_nodes=MAX_STRUCTURE_NODES,
    )


def validate_decoded_structure(value: Any, *, label: str) -> None:
    """Reject decoded embedded JSON outside the tighter structure budget."""
    _validate_structure(
        value,
        label=label,
        max_depth=MAX_STRUCTURE_DEPTH,
        max_nodes=MAX_DEFINITION_NODES,
    )


def validate_definition_structure(value: Any, *, label: str) -> None:
    """Compatibility wrapper for decoded formula and segment definitions."""
    validate_decoded_structure(value, label=label)


def validate_unicode_scalars(value: Any, *, label: str) -> None:
    """Reject surrogate code points in JSON-like string values and mapping keys.

    This walk intentionally adds no size or depth budget. It is used for
    embedded JSON that has already passed the outer snapshot budget and for
    defensive direct callers such as the renderer.
    """
    active_containers: set[int] = set()
    validated_containers: set[int] = set()
    stack: list[tuple[Any, bool]] = [(value, False)]
    while stack:
        node, exiting = stack.pop()
        is_container = isinstance(node, (dict, list))
        if not is_container:
            _validate_string(node, label=label)
            continue

        identity = id(node)
        if exiting:
            active_containers.remove(identity)
            validated_containers.add(identity)
            continue
        if identity in validated_containers:
            continue
        if identity in active_containers:
            raise InvalidSnapshotError(f"{label} contains a circular container reference")

        active_containers.add(identity)
        stack.append((node, True))
        _validate_string(node, label=label)
        if isinstance(node, dict):
            for key in node:
                _validate_string(key, label=label)
            stack.extend((child, False) for child in node.values())
        else:
            stack.extend((child, False) for child in node)


def _validate_string(value: Any, *, label: str) -> None:
    if isinstance(value, str) and any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise InvalidSnapshotError(f"{label} contains a Unicode surrogate code point")


def _validate_structure(
    value: Any,
    *,
    label: str,
    max_depth: int,
    max_nodes: int,
) -> None:
    for nodes, (node, depth) in enumerate(_iter_structure(value), start=1):
        if depth > max_depth:
            raise InvalidSnapshotError(
                f"{label} exceeds the maximum structure depth of {max_depth}"
            )
        if nodes > max_nodes:
            raise InvalidSnapshotError(f"{label} exceeds the maximum of {max_nodes:,} nodes")
        _validate_string(node, label=label)
        if isinstance(node, dict):
            for key in node:
                _validate_string(key, label=label)
