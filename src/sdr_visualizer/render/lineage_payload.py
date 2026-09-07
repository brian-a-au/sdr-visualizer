"""Build the private, source-faithful payload for the CJA lineage POC."""

from __future__ import annotations

from typing import Any

from sdr_visualizer.analysis.lineage_layout import (
    FULL_GRAPH_EDGE_LIMIT,
    FULL_GRAPH_NODE_LIMIT,
    LayoutCanvas,
    LineageLayout,
    build_lineage_layout,
    validate_lineage_layout,
)
from sdr_visualizer.core.lineage import (
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
    LineageTopology,
    ReportedValue,
)
from sdr_visualizer.core.structure_limits import validate_unicode_scalars


def build_payload(
    topology: LineageTopology, *, layout: LineageLayout | None = None
) -> dict[str, Any]:
    """Return deterministic browser data without source-record provenance."""
    if layout is None:
        prepared = build_lineage_layout(topology)
    else:
        prepared = layout
        validate_lineage_layout(topology, prepared)
    validate_unicode_scalars(topology.scope_label, label="CJA lineage scope label")

    datasets = [
        {
            "id": item.id,
            "name": item.name,
            "kind": "dataset",
            "shape": "rounded-rectangle",
            "search_text": _search_text(item.name, item.id),
        }
        for item in topology.datasets
    ]
    connections = [
        {
            "id": item.id,
            "name": item.name,
            "display_name": item.name or "Connection details unavailable",
            "kind": "connection",
            "shape": "hexagon",
            "detail_availability": item.detail_availability.value,
            "dataset_availability": item.dataset_availability.value,
            "search_text": _search_text(item.name or "", item.id),
        }
        for item in topology.connections
    ]
    data_views = [
        {
            "id": item.id,
            "name": item.name,
            "kind": "data-view",
            "shape": "rectangle",
            "connection_id": item.connection_id,
            "connection_detail_availability": item.connection_detail_availability.value,
            "dataset_availability": item.dataset_availability.value,
            "search_text": _search_text(item.name, item.id),
        }
        for item in topology.data_views
    ]
    edges = [
        _dataset_connection_payload(item, index)
        for index, item in enumerate(topology.dataset_connections)
    ]
    edges.extend(
        {
            "id": f"connection-data-view:{index}",
            "kind": "connection-data-view",
            "source_id": item.connection_id,
            "target_id": item.data_view_id,
        }
        for index, item in enumerate(topology.connection_data_views)
    )
    dataset_ids_by_connection = {item.id: list(item.dataset_ids) for item in topology.connections}
    data_view_ids_by_connection: dict[str, list[str]] = {
        item.id: [] for item in topology.connections
    }
    for item in topology.connection_data_views:
        data_view_ids_by_connection[item.connection_id].append(item.data_view_id)

    node_count = len(datasets) + len(connections) + len(data_views)
    edge_count = len(edges)
    empty = node_count == 0
    return {
        "schema": "cja-lineage-poc/1",
        "scope_label": topology.scope_label,
        "coverage": _coverage(topology.coverage),
        "counts": {
            "datasets": len(datasets),
            "connections": len(connections),
            "data_views": len(data_views),
            "edges": edge_count,
        },
        "empty": empty,
        "entities": {
            "datasets": datasets,
            "connections": connections,
            "data_views": data_views,
        },
        "edges": edges,
        "adjacency": {
            "dataset_ids_by_connection": dataset_ids_by_connection,
            "data_view_ids_by_connection": data_view_ids_by_connection,
        },
        "geometry": {
            "global": _canvas_payload(prepared.global_layout),
            "local_by_connection": [
                {
                    "connection_id": item.connection_id,
                    **_canvas_payload(item.canvas),
                }
                for item in prepared.local_layouts
            ],
        },
        "gating": {
            "node_limit": FULL_GRAPH_NODE_LIMIT,
            "edge_limit": FULL_GRAPH_EDGE_LIMIT,
            "full_graph_gated": prepared.full_graph_gated,
            "full_graph_requires_opt_in": not empty,
            "default_overview": "static-inert",
        },
    }


def _coverage(coverage: Coverage) -> dict[str, str]:
    if coverage is Coverage.PERMISSION_DEGRADED:
        return {
            "state": coverage.value,
            "label": "Permission-degraded discovery",
            "detail": "Some accessible connection or dataset details are unavailable.",
        }
    return {
        "state": coverage.value,
        "label": "Accessible scope; completeness unknown",
        "detail": "This report describes only the scope accessible to this discovery source.",
    }


def _search_text(name: str, entity_id: str) -> str:
    # Keep the source text intact. The browser applies one shared normalization
    # function to both this value and the user's query, while names/identifiers
    # remain available for exact display.
    return f"{name} {entity_id}"


def _dataset_connection_payload(item: DatasetConnection, index: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": f"dataset-connection:{index}",
        "kind": "dataset-connection",
        "source_id": item.dataset_id,
        "target_id": item.connection_id,
    }
    if item.connection_metadata is not None:
        payload["connection_metadata"] = _connection_metadata_payload(item.connection_metadata)
    return payload


def _connection_metadata_payload(value: DatasetConnectionMetadata) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    _put_reported(payload, "role", value.role)
    _put_reported(payload, "schema", value.schema, _schema_payload)
    _put_reported(payload, "identity", value.identity, _identity_payload)
    _put_reported(payload, "lookup", value.lookup, _lookup_payload)
    _put_reported(payload, "ingestion", value.ingestion, _ingestion_payload)
    _put_reported(payload, "dataSource", value.data_source, _data_source_payload)
    return payload


def _schema_payload(value: DatasetSchema) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    _put_reported(payload, "id", value.id)
    _put_reported(payload, "name", value.name)
    _put_reported(payload, "ref", value.ref, _schema_ref_payload)
    return payload


def _schema_ref_payload(value: DatasetSchemaRef) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    _put_reported(payload, "id", value.id)
    _put_reported(payload, "contentType", value.content_type)
    return payload


def _identity_payload(value: DatasetIdentity) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    _put_reported(payload, "timestampId", value.timestamp_id)
    _put_reported(payload, "visitorId", value.visitor_id)
    _put_reported(payload, "namespace", value.namespace)
    _put_reported(payload, "usePrimaryIdNamespace", value.use_primary_id_namespace)
    _put_reported(payload, "identityMap", value.identity_map)
    _put_reported(payload, "namespaceColumn", value.namespace_column)
    return payload


def _lookup_payload(value: DatasetLookup) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    _put_reported(payload, "keyField", value.key_field)
    _put_reported(payload, "parentFields", value.parent_fields, list)
    _put_reported(payload, "parentDatasetId", value.parent_dataset_id)
    _put_reported(payload, "parentDatasetType", value.parent_dataset_type)
    return payload


def _backfill_summary_payload(value: DatasetBackfillSummary) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    _put_reported(payload, "total", value.total)
    _put_reported(payload, "failed", value.failed)
    _put_reported(payload, "inProgress", value.in_progress)
    _put_reported(payload, "completed", value.completed)
    _put_reported(payload, "invalid", value.invalid)
    return payload


def _ingestion_payload(value: DatasetIngestion) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    _put_reported(payload, "streaming", value.streaming)
    _put_reported(
        payload,
        "backfillSummary",
        value.backfill_summary,
        _backfill_summary_payload,
    )
    _put_reported(payload, "lastIngestedTime", value.last_ingested_time)
    _put_reported(payload, "streamingEnabledAt", value.streaming_enabled_at)
    return payload


def _data_source_payload(value: DatasetDataSource) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    _put_reported(payload, "id", value.id)
    _put_reported(payload, "type", value.type)
    _put_reported(payload, "description", value.description)
    return payload


def _put_reported(
    target: dict[str, Any], key: str, reported: ReportedValue | None, serializer=None
) -> None:
    if reported is None:
        return
    if reported.value is None:
        target[key] = None
    elif serializer is None:
        target[key] = reported.value
    else:
        target[key] = serializer(reported.value)


def _canvas_payload(canvas: LayoutCanvas) -> dict[str, Any]:
    return {
        "width": canvas.width,
        "height": canvas.height,
        "columns": [
            {
                "kind": item.kind,
                "x": item.x,
                "width": item.width,
                "top": item.top,
                "bottom": item.bottom,
            }
            for item in canvas.columns
        ],
        "nodes": [
            {
                "ref": item.ref,
                "kind": item.kind,
                "entity_id": item.entity_id,
                "x": item.x,
                "y": item.y,
                "width": item.width,
                "height": item.height,
            }
            for item in canvas.nodes
        ],
        "edges": [
            {
                "id": item.id,
                "kind": item.kind,
                "source_ref": item.source_ref,
                "target_ref": item.target_ref,
                "points": [list(point) for point in item.points],
            }
            for item in canvas.edges
        ],
    }


__all__ = ["build_payload"]
