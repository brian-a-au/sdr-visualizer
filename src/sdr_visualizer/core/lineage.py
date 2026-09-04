"""Normalized, source-traceable CJA dataset lineage model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

T = TypeVar("T")


class Coverage(StrEnum):
    """What discovery can safely claim about the represented scope."""

    ACCESSIBLE_SCOPE = "accessible-scope-completeness-unknown"
    PERMISSION_DEGRADED = "permission-degraded"


class Availability(StrEnum):
    """Whether source details are known, explicitly empty, or unavailable."""

    AVAILABLE = "available"
    REPORTED_EMPTY = "reported-empty"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ReportedValue(Generic[T]):
    """A source field that was present, including explicit null or empty values."""

    value: T | None


@dataclass(frozen=True, slots=True)
class DatasetSchemaRef:
    id: ReportedValue[str] | None = None
    content_type: ReportedValue[str] | None = None


@dataclass(frozen=True, slots=True)
class DatasetSchema:
    id: ReportedValue[str] | None = None
    name: ReportedValue[str] | None = None
    ref: ReportedValue[DatasetSchemaRef] | None = None


@dataclass(frozen=True, slots=True)
class DatasetIdentity:
    timestamp_id: ReportedValue[str] | None = None
    visitor_id: ReportedValue[str] | None = None
    namespace: ReportedValue[str] | None = None
    use_primary_id_namespace: ReportedValue[bool] | None = None
    identity_map: ReportedValue[bool] | None = None
    namespace_column: ReportedValue[str] | None = None


@dataclass(frozen=True, slots=True)
class DatasetLookup:
    key_field: ReportedValue[str] | None = None
    parent_fields: ReportedValue[tuple[str, ...]] | None = None
    parent_dataset_id: ReportedValue[str] | None = None
    parent_dataset_type: ReportedValue[str] | None = None


@dataclass(frozen=True, slots=True)
class DatasetBackfillSummary:
    total: ReportedValue[int] | None = None
    failed: ReportedValue[int] | None = None
    in_progress: ReportedValue[int] | None = None
    completed: ReportedValue[int] | None = None
    invalid: ReportedValue[bool] | None = None


@dataclass(frozen=True, slots=True)
class DatasetIngestion:
    streaming: ReportedValue[bool] | None = None
    backfill_summary: ReportedValue[DatasetBackfillSummary] | None = None
    last_ingested_time: ReportedValue[str] | None = None
    streaming_enabled_at: ReportedValue[str] | None = None


@dataclass(frozen=True, slots=True)
class DatasetDataSource:
    id: ReportedValue[str] | None = None
    type: ReportedValue[str] | None = None
    description: ReportedValue[str] | None = None


@dataclass(frozen=True, slots=True)
class DatasetConnectionMetadata:
    """CJA configuration reported for one dataset-to-Connection relationship."""

    role: ReportedValue[str] | None = None
    schema: ReportedValue[DatasetSchema] | None = None
    identity: ReportedValue[DatasetIdentity] | None = None
    lookup: ReportedValue[DatasetLookup] | None = None
    ingestion: ReportedValue[DatasetIngestion] | None = None
    data_source: ReportedValue[DatasetDataSource] | None = None


@dataclass(frozen=True, slots=True)
class LineageDataset:
    id: str
    name: str
    source_record_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class LineageConnection:
    id: str
    name: str | None
    detail_availability: Availability
    dataset_availability: Availability
    dataset_ids: tuple[str, ...]
    source_record_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class LineageDataView:
    id: str
    name: str
    connection_id: str | None
    connection_detail_availability: Availability
    dataset_availability: Availability
    source_record_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DatasetConnection:
    dataset_id: str
    connection_id: str
    source_record_indexes: tuple[int, ...]
    connection_metadata: DatasetConnectionMetadata | None = None


@dataclass(frozen=True, slots=True)
class ConnectionDataView:
    connection_id: str
    data_view_id: str
    source_record_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class LineageTopology:
    """Validated topology independent of rendering and geometry."""

    scope_label: str
    coverage: Coverage
    datasets: tuple[LineageDataset, ...]
    connections: tuple[LineageConnection, ...]
    data_views: tuple[LineageDataView, ...]
    dataset_connections: tuple[DatasetConnection, ...]
    connection_data_views: tuple[ConnectionDataView, ...]


__all__ = [
    "Availability",
    "ConnectionDataView",
    "Coverage",
    "DatasetBackfillSummary",
    "DatasetConnection",
    "DatasetConnectionMetadata",
    "DatasetDataSource",
    "DatasetIdentity",
    "DatasetIngestion",
    "DatasetLookup",
    "DatasetSchema",
    "DatasetSchemaRef",
    "LineageConnection",
    "LineageDataset",
    "LineageDataView",
    "LineageTopology",
    "ReportedValue",
]
