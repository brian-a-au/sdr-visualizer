"""Snapshot-to-snapshot diff (0.4.0 comparative view).

Compares two normalized Implementations and returns the payload-shaped
`changes` section that lands under `payload["changes"]`. Works only on the
normalized model, so it is platform agnostic and touches no vendored file.

Rules (see .superpowers/specs/2026-07-11-0.4.0-comparative-view.md):
  - identity is the component id: added / removed / modified by id
  - a type change on the same id reports as removed + added
  - scalar fields diff as {field, old, new}
  - list fields diff as set membership: {field, added, removed}
  - volatile / derived fields are never compared: modified_at, created_at,
    in/out degree, platform_specific, complexity_score, raw definitions
  - duplicate ids within one snapshot are last-writer-wins, matching the
    payload builder's rule
  - output lists sort by (type, id) so reports are deterministic
"""

from __future__ import annotations

from typing import Any

from sdr_visualizer.core.models import Implementation

_SCALAR_FIELDS = {
    "component": ("name", "description", "data_type", "polarity", "owner"),
    "segment": ("name", "description", "nesting_depth", "owner"),
    "calculated_metric": (
        "name",
        "description",
        "formula_text",
        "attribution_model",
        "allocation",
        "owner",
    ),
}
_LIST_FIELDS = {
    "component": ("tags",),
    "segment": ("references", "container_types"),
    "calculated_metric": ("references",),
}
_KIND_BY_TYPE = {
    "metric": "component",
    "dimension": "component",
    "derived_field": "component",
    "segment": "segment",
    "calculated_metric": "calculated_metric",
}


def diff_implementations(old: Implementation, new: Implementation) -> dict[str, Any]:
    """Return the payload `changes` section for old -> new."""
    old_index = _index(old)
    new_index = _index(new)

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []

    for cid, (ctype, entity) in new_index.items():
        if cid not in old_index:
            added.append(_summary(cid, ctype, entity))
    for cid, (ctype, entity) in old_index.items():
        if cid not in new_index:
            removed.append(_summary(cid, ctype, entity))
    for cid in old_index.keys() & new_index.keys():
        old_type, old_entity = old_index[cid]
        new_type, new_entity = new_index[cid]
        if old_type != new_type:
            removed.append(_summary(cid, old_type, old_entity))
            added.append(_summary(cid, new_type, new_entity))
            continue
        fields = _diff_fields(old_entity, new_entity, _KIND_BY_TYPE[new_type])
        if fields:
            entry = _summary(cid, new_type, new_entity)
            entry["fields"] = fields
            modified.append(entry)

    return {
        "baseline": {
            "source": old.snapshot_source,
            "taken_at": old.snapshot_taken_at,
            "instance_id": old.instance_id,
        },
        "added": sorted(added, key=_order),
        "removed": sorted(removed, key=_order),
        "modified": sorted(modified, key=_order),
    }


def _order(entry: dict[str, Any]) -> tuple[str, str]:
    return (entry["type"], entry["id"])


def _index(impl: Implementation) -> dict[str, tuple[str, Any]]:
    """id -> (payload type, entity). Later entries win on duplicate ids."""
    index: dict[str, tuple[str, Any]] = {}
    for entity in impl.metrics:
        index[entity.id] = ("metric", entity)
    for entity in impl.dimensions:
        index[entity.id] = ("dimension", entity)
    for entity in impl.derived_fields:
        index[entity.id] = ("derived_field", entity)
    for entity in impl.segments:
        index[entity.id] = ("segment", entity)
    for entity in impl.calculated_metrics:
        index[entity.id] = ("calculated_metric", entity)
    return index


def _summary(cid: str, ctype: str, entity: Any) -> dict[str, Any]:
    return {"id": cid, "type": ctype, "name": entity.name}


def _diff_fields(old: Any, new: Any, kind: str) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for name in _SCALAR_FIELDS[kind]:
        old_value = getattr(old, name)
        new_value = getattr(new, name)
        if old_value != new_value:
            fields.append({"field": name, "old": old_value, "new": new_value})
    for name in _LIST_FIELDS[kind]:
        old_set = set(getattr(old, name) or [])
        new_set = set(getattr(new, name) or [])
        if old_set != new_set:
            fields.append(
                {
                    "field": name,
                    "added": sorted(new_set - old_set),
                    "removed": sorted(old_set - new_set),
                }
            )
    return fields
