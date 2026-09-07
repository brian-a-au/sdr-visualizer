"""Validate and normalize ``cja_auto_sdr --list-datasets`` discovery JSON."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from typing import Any

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.lineage import (
    Availability,
    ConnectionDataView,
    Coverage,
    DatasetBackfillSummary,
    DatasetConnection,
    DatasetConnectionMetadata,
    DatasetDataSource,
    DatasetIdentity,
    DatasetIngestion,
    DatasetLookup,
    DatasetSchema,
    DatasetSchemaRef,
    LineageConnection,
    LineageDataset,
    LineageDataView,
    LineageTopology,
    ReportedValue,
)
from sdr_visualizer.core.structure_limits import (
    validate_snapshot_structure,
    validate_unicode_scalars,
)

MAX_ID_LENGTH = 512
MAX_NAME_LENGTH = 2_048
MAX_SCOPE_LABEL_LENGTH = 512
MAX_WARNING_LENGTH = 4_096

_SENTINELS = {"", "n/a", "na", "null", "none"}
_BIDI_CONTROLS = frozenset(
    {
        "\u061c",  # Arabic letter mark
        "\u200e",  # Left-to-right mark
        "\u200f",  # Right-to-left mark
        "\u202a",  # Left-to-right embedding
        "\u202b",  # Right-to-left embedding
        "\u202c",  # Pop directional formatting
        "\u202d",  # Left-to-right override
        "\u202e",  # Right-to-left override
        "\u2066",  # Left-to-right isolate
        "\u2067",  # Right-to-left isolate
        "\u2068",  # First strong isolate
        "\u2069",  # Pop directional isolate
    }
)


def adapt(snapshot: Mapping[str, Any], *, scope_label: str) -> LineageTopology:
    """Return a deterministic topology from verified CJA discovery data.

    Validation messages identify only controlled field labels and record
    indexes. External values are never copied into an exception.
    """
    if not isinstance(snapshot, dict):
        raise InvalidSnapshotError(f"expected top-level JSON object, got {type(snapshot).__name__}")
    validate_snapshot_structure(snapshot, label="CJA lineage discovery")
    normalized_scope = _required_text(
        scope_label,
        label="scope label",
        maximum=MAX_SCOPE_LABEL_LENGTH,
    )

    records = snapshot.get("dataViews")
    if not isinstance(records, list):
        raise InvalidSnapshotError("CJA lineage discovery dataViews must be a list")
    count = snapshot.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise InvalidSnapshotError("CJA lineage discovery count must be a non-negative integer")
    if count != len(records):
        raise InvalidSnapshotError("CJA lineage discovery count does not match dataViews length")

    warning_present = "warning" in snapshot
    if warning_present:
        _required_text(snapshot["warning"], label="warning", maximum=MAX_WARNING_LENGTH)

    dataset_names: dict[str, str] = {}
    dataset_sources: dict[str, set[int]] = {}
    connection_names: dict[str, str | None] = {}
    connection_dataset_ids: dict[str, frozenset[str]] = {}
    connection_sources: dict[str, set[int]] = {}
    data_view_names: dict[str, str] = {}
    data_view_claims: dict[str, tuple[str | None, Availability, Availability]] = {}
    data_view_sources: dict[str, set[int]] = {}
    dataset_connection_sources: dict[tuple[str, str], set[int]] = {}
    dataset_connection_metadata: dict[tuple[str, str], list[DatasetConnectionMetadata]] = {}
    connection_data_view_sources: dict[tuple[str, str], set[int]] = {}

    has_unavailable_real_connection = False
    for index, raw_record in enumerate(records):
        if not isinstance(raw_record, dict):
            raise InvalidSnapshotError(f"CJA lineage record {index} must be an object")

        data_view_id = _required_id(raw_record.get("id"), label=f"record {index} dataView.id")
        data_view_name = _required_text(
            raw_record.get("name"),
            label=f"record {index} dataView.name",
            maximum=MAX_NAME_LENGTH,
        )
        _merge_name(
            data_view_names,
            data_view_id,
            data_view_name,
            entity="data view",
        )

        raw_connection = raw_record.get("connection")
        if not isinstance(raw_connection, dict):
            raise InvalidSnapshotError(f"CJA lineage record {index} connection must be an object")
        if "id" not in raw_connection:
            raise InvalidSnapshotError(f"CJA lineage record {index} connection.id is required")
        if "name" not in raw_connection:
            raise InvalidSnapshotError(f"CJA lineage record {index} connection.name is required")
        connection_id = _optional_parent_id(
            raw_connection.get("id"),
            label=f"record {index} connection.id",
        )

        raw_datasets = raw_record.get("datasets")
        if connection_id is None:
            if raw_datasets is None:
                raw_datasets = []
            if not isinstance(raw_datasets, list):
                raise InvalidSnapshotError(f"CJA lineage record {index} datasets must be a list")
            if raw_datasets:
                raise InvalidSnapshotError(
                    f"CJA lineage record {index} datasets cannot reference a missing parent"
                )
            detail_availability = Availability.UNAVAILABLE
            dataset_availability = Availability.UNAVAILABLE
            dataset_ids: frozenset[str] = frozenset()
        else:
            connection_name = _optional_connection_name(
                raw_connection.get("name"),
                label=f"record {index} connection.name",
            )
            if connection_name is None:
                has_unavailable_real_connection = True
                if raw_datasets is None:
                    raw_datasets = []
                if not isinstance(raw_datasets, list):
                    raise InvalidSnapshotError(
                        f"CJA lineage record {index} datasets must be a list"
                    )
                if raw_datasets:
                    raise InvalidSnapshotError(
                        f"CJA lineage record {index} datasets cannot claim an unavailable connection"
                    )
                detail_availability = Availability.UNAVAILABLE
                dataset_availability = Availability.UNAVAILABLE
                dataset_ids = frozenset()
            else:
                if not isinstance(raw_datasets, list):
                    raise InvalidSnapshotError(
                        f"CJA lineage record {index} datasets must be a list"
                    )
                detail_availability = Availability.AVAILABLE
                dataset_availability = (
                    Availability.AVAILABLE if raw_datasets else Availability.REPORTED_EMPTY
                )
                current_dataset_ids: set[str] = set()
                for dataset_index, raw_dataset in enumerate(raw_datasets):
                    if not isinstance(raw_dataset, dict):
                        raise InvalidSnapshotError(
                            f"CJA lineage record {index} dataset {dataset_index} must be an object"
                        )
                    dataset_id = _required_id(
                        raw_dataset.get("id"),
                        label=f"record {index} dataset.id",
                    )
                    dataset_name = _required_text(
                        raw_dataset.get("name"),
                        label=f"record {index} dataset.name",
                        maximum=MAX_NAME_LENGTH,
                    )
                    _merge_dataset_name(dataset_names, dataset_id, dataset_name)
                    dataset_sources.setdefault(dataset_id, set()).add(index)
                    current_dataset_ids.add(dataset_id)
                    dataset_connection_sources.setdefault((dataset_id, connection_id), set()).add(
                        index
                    )
                    relationship = (dataset_id, connection_id)
                    parsed_metadata = _parse_connection_metadata(
                        raw_dataset.get("connectionMetadata", _MISSING)
                    )
                    if parsed_metadata is not None:
                        dataset_connection_metadata.setdefault(relationship, []).append(
                            parsed_metadata
                        )
                dataset_ids = frozenset(current_dataset_ids)

            if connection_id in connection_names:
                if connection_names[connection_id] != connection_name:
                    raise InvalidSnapshotError("conflicting connection name for repeated ID")
                if connection_dataset_ids[connection_id] != dataset_ids:
                    raise InvalidSnapshotError(
                        "conflicting dataset relationships for repeated connection ID"
                    )
            else:
                connection_names[connection_id] = connection_name
                connection_dataset_ids[connection_id] = dataset_ids
            connection_sources.setdefault(connection_id, set()).add(index)
            connection_data_view_sources.setdefault((connection_id, data_view_id), set()).add(index)

        claim = (connection_id, detail_availability, dataset_availability)
        if data_view_id in data_view_claims and data_view_claims[data_view_id] != claim:
            raise InvalidSnapshotError("conflicting parent relationship for repeated data view ID")
        data_view_claims[data_view_id] = claim
        data_view_sources.setdefault(data_view_id, set()).add(index)

    datasets = tuple(
        LineageDataset(dataset_id, dataset_names[dataset_id], tuple(sorted(source_indexes)))
        for dataset_id, source_indexes in sorted(dataset_sources.items())
    )
    connections = tuple(
        LineageConnection(
            connection_id,
            connection_names[connection_id],
            (
                Availability.AVAILABLE
                if connection_names[connection_id] is not None
                else Availability.UNAVAILABLE
            ),
            (
                Availability.UNAVAILABLE
                if connection_names[connection_id] is None
                else (
                    Availability.AVAILABLE
                    if connection_dataset_ids[connection_id]
                    else Availability.REPORTED_EMPTY
                )
            ),
            tuple(sorted(connection_dataset_ids[connection_id])),
            tuple(sorted(source_indexes)),
        )
        for connection_id, source_indexes in sorted(connection_sources.items())
    )
    data_views = tuple(
        LineageDataView(
            data_view_id,
            data_view_names[data_view_id],
            data_view_claims[data_view_id][0],
            data_view_claims[data_view_id][1],
            data_view_claims[data_view_id][2],
            tuple(sorted(source_indexes)),
        )
        for data_view_id, source_indexes in sorted(data_view_sources.items())
    )
    dataset_connections = tuple(
        DatasetConnection(
            dataset_id,
            connection_id,
            tuple(sorted(source_indexes)),
            _merge_metadata_groups(
                *dataset_connection_metadata.get((dataset_id, connection_id), ())
            ),
        )
        for (dataset_id, connection_id), source_indexes in sorted(
            dataset_connection_sources.items()
        )
    )
    connection_data_views = tuple(
        ConnectionDataView(connection_id, data_view_id, tuple(sorted(source_indexes)))
        for (connection_id, data_view_id), source_indexes in sorted(
            connection_data_view_sources.items()
        )
    )
    coverage = (
        Coverage.PERMISSION_DEGRADED
        if warning_present or has_unavailable_real_connection
        else Coverage.ACCESSIBLE_SCOPE
    )
    return LineageTopology(
        scope_label=normalized_scope,
        coverage=coverage,
        datasets=datasets,
        connections=connections,
        data_views=data_views,
        dataset_connections=dataset_connections,
        connection_data_views=connection_data_views,
    )


def _merge_name(names: dict[str, str], entity_id: str, name: str, *, entity: str) -> None:
    if entity_id in names and names[entity_id] != name:
        raise InvalidSnapshotError(f"conflicting {entity} name for repeated ID")
    names[entity_id] = name


def _merge_dataset_name(names: dict[str, str], dataset_id: str, name: str) -> None:
    """Keep one stable node when CJA reports aliases for the same dataset ID."""
    existing = names.get(dataset_id)
    names[dataset_id] = (
        name
        if existing is None
        else min(existing, name, key=lambda value: (value.casefold(), value))
    )


_MISSING = object()


def _parse_connection_metadata(value: Any) -> DatasetConnectionMetadata | None:
    """Best-effort normalization of optional, relationship-scoped enrichment."""
    if value is _MISSING or not isinstance(value, dict):
        return None
    return DatasetConnectionMetadata(
        role=_metadata_text(value, "role", maximum=MAX_NAME_LENGTH),
        schema=_metadata_group(value, "schema", _parse_schema),
        identity=_metadata_group(value, "identity", _parse_identity),
        lookup=_metadata_group(value, "lookup", _parse_lookup),
        ingestion=_metadata_group(value, "ingestion", _parse_ingestion),
        data_source=_metadata_group(value, "dataSource", _parse_data_source),
    )


def _parse_schema(value: dict[str, Any]) -> DatasetSchema:
    return DatasetSchema(
        id=_metadata_text(value, "id", maximum=MAX_ID_LENGTH),
        name=_metadata_text(value, "name", maximum=MAX_NAME_LENGTH),
        ref=_metadata_group(value, "ref", _parse_schema_ref),
    )


def _parse_schema_ref(value: dict[str, Any]) -> DatasetSchemaRef:
    return DatasetSchemaRef(
        id=_metadata_text(value, "id", maximum=MAX_NAME_LENGTH),
        content_type=_metadata_text(value, "contentType", maximum=MAX_NAME_LENGTH),
    )


def _parse_identity(value: dict[str, Any]) -> DatasetIdentity:
    return DatasetIdentity(
        timestamp_id=_metadata_text(value, "timestampId", maximum=MAX_ID_LENGTH),
        visitor_id=_metadata_text(value, "visitorId", maximum=MAX_ID_LENGTH),
        namespace=_metadata_text(value, "namespace", maximum=MAX_NAME_LENGTH),
        use_primary_id_namespace=_metadata_bool(value, "usePrimaryIdNamespace"),
        identity_map=_metadata_bool(value, "identityMap"),
        namespace_column=_metadata_text(value, "namespaceColumn", maximum=MAX_ID_LENGTH),
    )


def _parse_lookup(value: dict[str, Any]) -> DatasetLookup:
    return DatasetLookup(
        key_field=_metadata_text(value, "keyField", maximum=MAX_ID_LENGTH),
        parent_fields=_metadata_string_tuple(value, "parentFields"),
        parent_dataset_id=_metadata_text(value, "parentDatasetId", maximum=MAX_ID_LENGTH),
        parent_dataset_type=_metadata_text(value, "parentDatasetType", maximum=MAX_NAME_LENGTH),
    )


def _parse_backfill_summary(value: dict[str, Any]) -> DatasetBackfillSummary:
    return DatasetBackfillSummary(
        total=_metadata_nonnegative_int(value, "total"),
        failed=_metadata_nonnegative_int(value, "failed"),
        in_progress=_metadata_nonnegative_int(value, "inProgress"),
        completed=_metadata_nonnegative_int(value, "completed"),
        invalid=_metadata_bool(value, "invalid"),
    )


def _parse_ingestion(value: dict[str, Any]) -> DatasetIngestion:
    return DatasetIngestion(
        streaming=_metadata_bool(value, "streaming"),
        backfill_summary=_metadata_group(value, "backfillSummary", _parse_backfill_summary),
        last_ingested_time=_metadata_text(value, "lastIngestedTime", maximum=MAX_NAME_LENGTH),
        streaming_enabled_at=_metadata_text(value, "streamingEnabledAt", maximum=MAX_NAME_LENGTH),
    )


def _parse_data_source(value: dict[str, Any]) -> DatasetDataSource:
    return DatasetDataSource(
        id=_metadata_text(value, "id", maximum=MAX_ID_LENGTH),
        type=_metadata_text(value, "type", maximum=MAX_NAME_LENGTH),
        description=_metadata_text(value, "description", maximum=MAX_NAME_LENGTH),
    )


def _metadata_group(value: dict[str, Any], key: str, parser) -> ReportedValue | None:
    if key not in value:
        return None
    raw = value[key]
    if raw is None:
        return ReportedValue(None)
    if not isinstance(raw, dict):
        return None
    return ReportedValue(parser(raw))


def _metadata_text(value: dict[str, Any], key: str, *, maximum: int) -> ReportedValue[str] | None:
    if key not in value:
        return None
    raw = value[key]
    if raw is None:
        return ReportedValue(None)
    if not isinstance(raw, str):
        return None
    try:
        _validate_text(raw, label="CJA connection metadata text", maximum=maximum)
    except InvalidSnapshotError:
        return None
    return ReportedValue(raw)


def _metadata_bool(value: dict[str, Any], key: str) -> ReportedValue[bool] | None:
    if key not in value:
        return None
    raw = value[key]
    if raw is None:
        return ReportedValue(None)
    return ReportedValue(raw) if isinstance(raw, bool) else None


def _metadata_nonnegative_int(value: dict[str, Any], key: str) -> ReportedValue[int] | None:
    if key not in value:
        return None
    raw = value[key]
    if raw is None:
        return ReportedValue(None)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return None
    return ReportedValue(raw)


def _metadata_string_tuple(
    value: dict[str, Any], key: str
) -> ReportedValue[tuple[str, ...]] | None:
    if key not in value:
        return None
    raw = value[key]
    if raw is None:
        return ReportedValue(None)
    if not isinstance(raw, list):
        return None
    normalized: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            return None
        try:
            _validate_text(item, label="CJA connection metadata field", maximum=MAX_ID_LENGTH)
        except InvalidSnapshotError:
            return None
        normalized.append(item)
    return ReportedValue(tuple(normalized))


def _merge_metadata_groups(*groups):
    """Merge all repeated observations; conflicting optional values become unknown."""
    if not groups:
        return None
    first = groups[0]
    if not all(is_dataclass(group) and type(group) is type(first) for group in groups):
        return first if all(group == first for group in groups[1:]) else None
    values = {
        field.name: _merge_reported_values(*(getattr(group, field.name) for group in groups))
        for field in fields(first)
    }
    return replace(first, **values)


def _merge_reported_values(*values):
    reported = tuple(value for value in values if value is not None)
    if not reported:
        return None
    first = reported[0]
    if all(value == first for value in reported[1:]):
        return first
    if (
        all(isinstance(value, ReportedValue) for value in reported)
        and all(value.value is not None for value in reported)
        and all(is_dataclass(value.value) for value in reported)
        and all(type(value.value) is type(first.value) for value in reported)
    ):
        return ReportedValue(_merge_metadata_groups(*(value.value for value in reported)))
    return None


def _required_id(value: Any, *, label: str) -> str:
    text = _required_text(value, label=label, maximum=MAX_ID_LENGTH)
    if text.casefold() in _SENTINELS:
        raise InvalidSnapshotError(f"{label} must be a valid non-sentinel ID")
    return text


def _optional_parent_id(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidSnapshotError(f"{label} must be a string, null, or N/A")
    _validate_text(value, label=label, maximum=MAX_ID_LENGTH)
    if value.strip().casefold() in _SENTINELS:
        return None
    if value != value.strip():
        raise InvalidSnapshotError(f"{label} must not contain surrounding whitespace")
    return value


def _optional_connection_name(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidSnapshotError(f"{label} must be a string or null")
    _validate_text(value, label=label, maximum=MAX_NAME_LENGTH)
    if value.strip().casefold() in _SENTINELS:
        return None
    if value != value.strip():
        raise InvalidSnapshotError(f"{label} must not contain surrounding whitespace")
    return value


def _required_text(value: Any, *, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidSnapshotError(f"{label} must be a string")
    _validate_text(value, label=label, maximum=maximum)
    if not value or not value.strip():
        raise InvalidSnapshotError(f"{label} must not be empty")
    if value != value.strip():
        raise InvalidSnapshotError(f"{label} must not contain surrounding whitespace")
    return value


def _validate_text(value: str, *, label: str, maximum: int) -> None:
    validate_unicode_scalars(value, label=label)
    if len(value) > maximum:
        raise InvalidSnapshotError(f"{label} exceeds the maximum length of {maximum:,}")
    if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value):
        raise InvalidSnapshotError(f"{label} contains a control character")
    if any(character in _BIDI_CONTROLS for character in value):
        raise InvalidSnapshotError(f"{label} contains a bidirectional control character")


__all__ = [
    "MAX_ID_LENGTH",
    "MAX_NAME_LENGTH",
    "MAX_SCOPE_LABEL_LENGTH",
    "MAX_WARNING_LENGTH",
    "adapt",
]
