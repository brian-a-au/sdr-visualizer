"""CJA adapter: cja_auto_sdr JSON output -> normalized Implementation.

Reads the JSON shape produced by `cja_auto_sdr ... --format json`. Maps
platform vocabulary into the model in core/models.py. Validates the input
shape and raises InvalidSnapshotError with an explicit message on failure.

See SPEC-VISUALIZER §8 (model contract) and the upstream cja_auto_sdr repo
for the authoritative output shape.
"""

from __future__ import annotations

import json
from typing import Any

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.models import (
    CalculatedMetric,
    Component,
    Implementation,
    Segment,
)


def adapt(snapshot: dict[str, Any], *, source: str = "<unknown>") -> Implementation:
    """Convert a parsed cja_auto_sdr JSON snapshot into an Implementation."""
    if not isinstance(snapshot, dict):
        raise InvalidSnapshotError(f"expected top-level JSON object, got {type(snapshot).__name__}")

    metadata = _require_dict(snapshot, "metadata")
    metrics_raw = _require_list(snapshot, "metrics")
    dimensions_raw = _require_list(snapshot, "dimensions")

    instance_id = (
        metadata.get("Data View ID") or metadata.get("data_view_id") or metadata.get("dataViewId")
    )
    if not instance_id:
        raise InvalidSnapshotError(
            "snapshot metadata is missing 'Data View ID'; not a CJA snapshot?"
        )

    instance_name = (
        metadata.get("Data View Name")
        or metadata.get("data_view_name")
        or metadata.get("dataViewName")
        or instance_id
    )
    snapshot_taken_at = (
        metadata.get("Generation Timestamp")
        or metadata.get("generation_timestamp")
        or metadata.get("generated_at")
        # The key real cja_auto_sdr exports actually carry (value like
        # "2026-05-20 10:56:29 PDT"; consumed as an opaque string, never
        # date-parsed). Found via the private corpus, 2026-07-17.
        or metadata.get("Generated Date & timestamp and timezone")
    )
    if isinstance(snapshot_taken_at, str):
        snapshot_taken_at = snapshot_taken_at.strip() or None

    adapter_version = metadata.get("Tool Version") or metadata.get("tool_version") or "unknown"

    metrics = [_component_from_record(r, "metric") for r in metrics_raw]
    dimensions = [_component_from_record(r, "dimension") for r in dimensions_raw]
    derived_fields = _adapt_derived_fields(snapshot.get("derived_fields"))
    calculated_metrics = _adapt_calculated_metrics(snapshot.get("calculated_metrics"))
    segments = _adapt_segments(snapshot.get("segments"))

    return Implementation(
        platform="cja",
        instance_id=str(instance_id),
        instance_name=str(instance_name),
        snapshot_taken_at=snapshot_taken_at,
        snapshot_source=source,
        adapter_version=str(adapter_version),
        metrics=metrics,
        dimensions=dimensions,
        segments=segments,
        calculated_metrics=calculated_metrics,
        derived_fields=derived_fields,
        raw=snapshot,
    )


# ---------------------------------------------------------------------------
# Component mapping (metrics, dimensions)
# ---------------------------------------------------------------------------


def _component_from_record(record: dict[str, Any], component_type: str) -> Component:
    if not isinstance(record, dict):
        raise InvalidSnapshotError(
            f"expected {component_type} record to be an object, got {type(record).__name__}"
        )

    component_id = record.get("id") or record.get("component_id") or record.get("metric_id")
    if not component_id:
        raise InvalidSnapshotError(f"{component_type} record is missing 'id': {record!r}")

    name = record.get("name") or record.get("title") or component_id
    description = _normalize_description(record.get("description"))
    data_type = record.get("dataType") or record.get("type")
    polarity = _normalize_polarity(record.get("polarity"))

    handled = {
        "id",
        "name",
        "title",
        "description",
        "dataType",
        "type",
        "polarity",
        "tags",
        "owner",
        "created",
        "modified",
        "created_at",
        "modified_at",
    }
    platform_specific = {k: v for k, v in record.items() if k not in handled}

    return Component(
        id=str(component_id),
        name=str(name),
        description=description,
        component_type=component_type,  # type: ignore[arg-type]
        data_type=_optional_str(data_type),
        polarity=polarity,
        created_at=_optional_timestamp(record.get("created") or record.get("created_at")),
        modified_at=_optional_timestamp(record.get("modified") or record.get("modified_at")),
        owner=_optional_str(record.get("owner")),
        tags=_parse_tag_list(record.get("tags")),
        platform_specific=platform_specific,
    )


# ---------------------------------------------------------------------------
# Derived fields
# ---------------------------------------------------------------------------


def _adapt_derived_fields(section: Any) -> list[Component]:
    if section is None:
        return []
    fields = _section_records(section, "fields")
    return [_derived_field_from_record(r) for r in fields]


def _derived_field_from_record(record: dict[str, Any]) -> Component:
    if not isinstance(record, dict):
        raise InvalidSnapshotError(
            f"expected derived field record to be an object, got {type(record).__name__}"
        )
    component_id = record.get("component_id") or record.get("id")
    if not component_id:
        raise InvalidSnapshotError(f"derived field record is missing 'component_id': {record!r}")

    name = record.get("component_name") or record.get("name") or component_id
    description = _normalize_description(record.get("description"))
    handled = {
        "component_id",
        "component_name",
        "id",
        "name",
        "description",
        "tags",
        "owner",
        "created",
        "modified",
        "created_at",
        "modified_at",
    }
    platform_specific = {k: v for k, v in record.items() if k not in handled}

    return Component(
        id=str(component_id),
        name=str(name),
        description=description,
        component_type="derived_field",
        data_type=_optional_str(record.get("output_type") or record.get("inferred_output_type")),
        polarity=None,
        created_at=_optional_timestamp(record.get("created") or record.get("created_at")),
        modified_at=_optional_timestamp(record.get("modified") or record.get("modified_at")),
        owner=_optional_str(record.get("owner")),
        tags=_parse_tag_list(record.get("tags")),
        platform_specific=platform_specific,
    )


# ---------------------------------------------------------------------------
# Calculated metrics
# ---------------------------------------------------------------------------


def _adapt_calculated_metrics(section: Any) -> list[CalculatedMetric]:
    if section is None:
        return []
    records = _section_records(section, "metrics")
    return [_calc_metric_from_record(r) for r in records]


def _calc_metric_from_record(record: dict[str, Any]) -> CalculatedMetric:
    if not isinstance(record, dict):
        raise InvalidSnapshotError(
            f"expected calculated metric record to be an object, got {type(record).__name__}"
        )
    metric_id = record.get("metric_id") or record.get("id")
    if not metric_id:
        raise InvalidSnapshotError(f"calculated metric record is missing 'metric_id': {record!r}")

    name = record.get("metric_name") or record.get("name") or metric_id
    description = _normalize_description(record.get("description"))
    formula = _parse_definition_json(record.get("definition_json"))
    formula_text = record.get("formula_summary") or record.get("definition_summary") or ""
    references = list(
        dict.fromkeys(
            [
                *_parse_ref_list(record.get("metric_references")),
                *_parse_ref_list(record.get("segment_references")),
            ]
        )
    )
    complexity = _as_float(record.get("complexity_score"))

    attribution_model, allocation = _extract_attribution(formula)

    return CalculatedMetric(
        id=str(metric_id),
        name=str(name),
        description=description,
        formula=formula,
        formula_text=str(formula_text),
        attribution_model=attribution_model,
        allocation=allocation,
        complexity_score=complexity,
        references=references,
        created_at=_optional_timestamp(record.get("created") or record.get("created_at")),
        modified_at=_optional_timestamp(record.get("modified") or record.get("modified_at")),
        owner=_optional_str(record.get("owner")),
    )


def _extract_attribution(formula: dict[str, Any]) -> tuple[str | None, str | None]:
    """Extract attribution model and allocation from a parsed CJA formula.

    cja_auto_sdr nests these inside `definition_json` in two shapes we've
    seen — a flat top level (`{attribution, allocation, func: 'divide', ...}`)
    or under a func dict. Try both. Consumers that need richer attribution
    analysis can re-parse the raw formula via Implementation.raw.
    """
    if not isinstance(formula, dict):
        return None, None
    attribution_model = (
        formula.get("attribution") or formula.get("attribution_model") or formula.get("model")
    )
    allocation = formula.get("allocation")
    func = formula.get("func")
    if isinstance(func, dict):
        attribution_model = attribution_model or func.get("attribution") or func.get("model")
        allocation = allocation or func.get("allocation")
    return (
        str(attribution_model) if attribution_model else None,
        str(allocation) if allocation else None,
    )


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------


def _adapt_segments(section: Any) -> list[Segment]:
    if section is None:
        return []
    records = _section_records(section, "segments")
    return [_segment_from_record(r) for r in records]


def _segment_from_record(record: dict[str, Any]) -> Segment:
    if not isinstance(record, dict):
        raise InvalidSnapshotError(
            f"expected segment record to be an object, got {type(record).__name__}"
        )
    segment_id = record.get("segment_id") or record.get("id")
    if not segment_id:
        raise InvalidSnapshotError(f"segment record is missing 'segment_id': {record!r}")

    name = record.get("segment_name") or record.get("name") or segment_id
    description = _normalize_description(record.get("description"))
    definition = _parse_definition_json(record.get("definition_json"))
    nesting_depth = _as_int(record.get("nesting_depth"))
    container_types = _extract_container_types(record.get("container_type"), definition)
    references = list(
        dict.fromkeys(
            [
                *_parse_ref_list(record.get("dimension_references")),
                *_parse_ref_list(record.get("metric_references")),
                *_parse_ref_list(record.get("other_segment_references")),
            ]
        )
    )

    return Segment(
        id=str(segment_id),
        name=str(name),
        description=description,
        definition=definition,
        nesting_depth=nesting_depth,
        container_types=container_types,
        references=references,
        created_at=_optional_timestamp(record.get("created") or record.get("created_at")),
        modified_at=_optional_timestamp(record.get("modified") or record.get("modified_at")),
        owner=_optional_str(record.get("owner")),
    )


def _extract_container_types(declared_container: Any, definition: dict[str, Any]) -> list[str]:
    """Collect distinct container 'context' values from a CJA segment definition.

    Falls back to the upstream-declared container_type if the definition shape
    doesn't expose nested containers (e.g. records-only output).
    """
    found: list[str] = []
    _walk_for_contexts(definition, found)
    if not found and declared_container:
        found = [str(declared_container)]
    seen: set[str] = set()
    ordered: list[str] = []
    for ctx in found:
        if ctx not in seen:
            seen.add(ctx)
            ordered.append(ctx)
    return ordered


def _walk_for_contexts(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("func") == "container" and node.get("context"):
            out.append(str(node["context"]))
        for value in node.values():
            _walk_for_contexts(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk_for_contexts(item, out)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# The newest cja_auto_sdr version this release was validated against
# (bundled fixtures + the private real corpus; re-derive at each release:
# grep -rho '"Tool Version": "[^"]*"|"tool_version": "[^"]*"' over corpus
# and fixtures, take the max). Q5 (SPEC §14): warn only — never refuse.
TESTED_THROUGH_GENERATOR_VERSION = "3.5.17"


def generator_version_warning(adapter_version: str) -> str | None:
    """Return warning text when the snapshot's generator is newer than the
    newest version this release was tested against, else None. Unparseable
    versions ("unknown", empty, suffixed builds) never warn. Vendored
    parity: behavior-identical copy in sdr-grader (SPEC §11/§15); the
    per-platform constant value is the one deliberate difference."""
    tested = _version_tuple(TESTED_THROUGH_GENERATOR_VERSION)
    seen = _version_tuple(adapter_version)
    if tested is None or seen is None or seen <= tested:
        return None
    return (
        f"snapshot generator version {adapter_version} is newer than the "
        f"newest version this release was tested against "
        f"({TESTED_THROUGH_GENERATOR_VERSION}); newer snapshot fields may "
        "not be represented"
    )


def _version_tuple(value: str) -> tuple[int, ...] | None:
    parts = str(value).strip().split(".")
    try:
        return tuple(int(p) for p in parts)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    """Coerce an optional scalar (owner, data_type) to a string, or None.

    cja_auto_sdr's owner/dataType/output_type fields are declared str|None
    in the internal model but the raw export can carry a numeric Adobe user
    id or an int dataType; a bare passthrough leaks that shape straight into
    the payload (fuzz-surfaced: $.components[*].owner,
    $.components[*].data_type). Falsy input (including 0) stays None rather
    than becoming the string "0" — matching the pre-existing
    `str(x) if x else None` pattern this helper replaces."""
    return str(value) if value else None


def _optional_timestamp(value: Any) -> str | None:
    """Keep created_at/modified_at only if they're already a non-empty string.

    A non-string timestamp (e.g. an epoch int) is treated as *missing*
    rather than coerced to a numeric string: `_compact` then drops the key,
    and the client renders the em-dash it already shows for a genuinely
    absent timestamp — which beats both a stringified epoch and the
    1970-date bug a raw int would cause downstream (fuzz-surfaced:
    $.components[*].modified_at)."""
    return value if isinstance(value, str) and value else None


def _parse_tag_list(value: Any) -> list[str]:
    """cja_auto_sdr ships `tags` as a JSON-encoded list string (e.g. `'["a"]'`).

    The naive `list(record.get("tags") or [])` iterates that string as
    characters — producing fake tags like `'['`, `'"'`, `'c'` — so this
    helper handles both the stringified and native-list shapes and falls back
    to `[]` for anything unparseable. Kept behavior-identical to sdr-grader's
    copy so the vendored adapters stay comparable (SPEC §11/§15)."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(t) for t in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(t) for t in parsed]
        return []
    return []


def _parse_ref_list(value: Any) -> list[str]:
    """Reference lists arrive as native lists or (like tags) as JSON-encoded
    list strings; anything else contributes nothing. Behavior-identical to
    sdr-grader's copy."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(t) for t in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(t) for t in parsed]
    return []


def _as_float(value: Any) -> float:
    """The visualizer's variant of sdr-grader's `_safe_float` (SPEC §11/§15).
    Two intentional deltas from the grader, both driven by visualizer-only
    behavior — do NOT reconcile them away to match the sibling:

    1. A present but unconvertible value RAISES InvalidSnapshotError (the
       grader returns a default). Trend mode relies on the raise to skip a
       malformed snapshot; a single snapshot exits 3.
    2. NaN/Infinity pass through unchanged (the grader coerces them to a
       default). The renderer's allow_nan=False guard then rejects the
       snapshot loudly (audit H2) — a report that cannot boot in a browser is
       worse than a rejected one.

    Falsy input keeps the old `value or 0.0` default."""
    if not value:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidSnapshotError(f"expected a number, got {value!r}") from exc


def _as_int(value: Any) -> int:
    """The visualizer's variant of sdr-grader's `_safe_int`; see _as_float for
    the intentional raise-on-unconvertible delta. Falsy input keeps the old
    `value or 0` default."""
    if not value:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidSnapshotError(f"expected an integer, got {value!r}") from exc


def _require_dict(snapshot: dict[str, Any], key: str) -> dict[str, Any]:
    value = snapshot.get(key)
    if not isinstance(value, dict):
        raise InvalidSnapshotError(
            f"snapshot is missing required object '{key}'"
            f"{' (got null)' if value is None else f' (got {type(value).__name__})'}"
        )
    return value


def _require_list(snapshot: dict[str, Any], key: str) -> list[Any]:
    value = snapshot.get(key)
    if not isinstance(value, list):
        raise InvalidSnapshotError(
            f"snapshot is missing required array '{key}'"
            f"{' (got null)' if value is None else f' (got {type(value).__name__})'}"
        )
    return value


def _section_records(section: Any, records_key: str) -> list[dict[str, Any]]:
    """Pull the records list out of a cja_auto_sdr section.

    cja_auto_sdr writes either { records_key: [...] } (records-only mode) or
    { "summary": {...}, records_key: [...] } (inventory mode). Bare arrays are
    also accepted for forward-compat.
    """
    if isinstance(section, list):
        return list(section)
    if isinstance(section, dict):
        records = section.get(records_key)
        if records is None:
            return []
        if not isinstance(records, list):
            raise InvalidSnapshotError(
                f"section '{records_key}' must be a list, got {type(records).__name__}"
            )
        return records
    raise InvalidSnapshotError(f"section must be object or list, got {type(section).__name__}")


def _parse_definition_json(value: Any) -> dict[str, Any]:
    """cja_auto_sdr ships definitions as JSON-encoded strings; tolerate dicts too."""
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _normalize_description(value: Any) -> str | None:
    """cja_auto_sdr writes '-' for missing descriptions; treat that as None."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped == "-":
        return None
    return stripped


def _normalize_polarity(value: Any):
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    if lowered in {"positive", "negative", "neutral"}:
        return lowered  # type: ignore[return-value]
    return None
