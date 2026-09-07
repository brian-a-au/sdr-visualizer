"""Deterministic, build-side geometry for the CJA lineage POC."""

from __future__ import annotations

import math
from dataclasses import dataclass

from sdr_visualizer.core.exceptions import SdrVisualizerError
from sdr_visualizer.core.lineage import LineageTopology

FULL_GRAPH_NODE_LIMIT = 1_000
FULL_GRAPH_EDGE_LIMIT = 8_000

_CANVAS_WIDTH = 1_320.0
_NODE_WIDTH = 280.0
_NODE_HEIGHT = 64.0
_TOP = 72.0
_BOTTOM = 40.0
_GAP = 24.0
_COLUMN_X = {"dataset": 40.0, "connection": 520.0, "data-view": 1_000.0}


class LineageLayoutError(SdrVisualizerError):
    """A controlled, content-free lineage geometry failure."""


@dataclass(frozen=True, slots=True)
class LayoutNode:
    ref: str
    kind: str
    entity_id: str
    x: float
    y: float
    width: float = _NODE_WIDTH
    height: float = _NODE_HEIGHT


@dataclass(frozen=True, slots=True)
class LayoutEdge:
    id: str
    kind: str
    source_ref: str
    target_ref: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class LayoutColumn:
    kind: str
    x: float
    width: float
    top: float
    bottom: float


@dataclass(frozen=True, slots=True)
class LayoutCanvas:
    width: float
    height: float
    columns: tuple[LayoutColumn, ...]
    nodes: tuple[LayoutNode, ...]
    edges: tuple[LayoutEdge, ...]


@dataclass(frozen=True, slots=True)
class LocalConnectionLayout:
    connection_id: str
    canvas: LayoutCanvas


@dataclass(frozen=True, slots=True)
class LineageLayout:
    global_layout: LayoutCanvas
    local_layouts: tuple[LocalConnectionLayout, ...]
    full_graph_gated: bool


def _ref(kind: str, entity_id: str) -> str:
    return f"{kind}:{entity_id}"


def build_lineage_layout(topology: LineageTopology) -> LineageLayout:
    """Build stable full and connection-local descriptors in O(V + E) space."""
    dataset_ids = tuple(item.id for item in topology.datasets)
    connection_ids = tuple(item.id for item in topology.connections)
    data_view_ids = tuple(item.id for item in topology.data_views)
    edge_specs = (
        *(
            (
                f"dataset-connection:{index}",
                "dataset-connection",
                _ref("dataset", edge.dataset_id),
                _ref("connection", edge.connection_id),
            )
            for index, edge in enumerate(topology.dataset_connections)
        ),
        *(
            (
                f"connection-data-view:{index}",
                "connection-data-view",
                _ref("connection", edge.connection_id),
                _ref("data-view", edge.data_view_id),
            )
            for index, edge in enumerate(topology.connection_data_views)
        ),
    )
    global_layout = _build_canvas(dataset_ids, connection_ids, data_view_ids, edge_specs)

    datasets_by_connection: dict[str, list[str]] = {item.id: [] for item in topology.connections}
    views_by_connection: dict[str, list[str]] = {item.id: [] for item in topology.connections}
    edges_by_connection: dict[str, list[tuple[str, str, str, str]]] = {
        item.id: [] for item in topology.connections
    }
    for index, edge in enumerate(topology.dataset_connections):
        datasets_by_connection[edge.connection_id].append(edge.dataset_id)
        edges_by_connection[edge.connection_id].append(
            (
                f"dataset-connection:{index}",
                "dataset-connection",
                _ref("dataset", edge.dataset_id),
                _ref("connection", edge.connection_id),
            )
        )
    for index, edge in enumerate(topology.connection_data_views):
        views_by_connection[edge.connection_id].append(edge.data_view_id)
        edges_by_connection[edge.connection_id].append(
            (
                f"connection-data-view:{index}",
                "connection-data-view",
                _ref("connection", edge.connection_id),
                _ref("data-view", edge.data_view_id),
            )
        )
    local_layouts = tuple(
        LocalConnectionLayout(
            connection_id,
            _build_canvas(
                tuple(datasets_by_connection[connection_id]),
                (connection_id,),
                tuple(views_by_connection[connection_id]),
                tuple(edges_by_connection[connection_id]),
            ),
        )
        for connection_id in connection_ids
    )
    node_count = len(dataset_ids) + len(connection_ids) + len(data_view_ids)
    layout = LineageLayout(
        global_layout,
        local_layouts,
        node_count > FULL_GRAPH_NODE_LIMIT or len(edge_specs) > FULL_GRAPH_EDGE_LIMIT,
    )
    validate_lineage_layout(topology, layout)
    return layout


def _build_canvas(
    dataset_ids: tuple[str, ...],
    connection_ids: tuple[str, ...],
    data_view_ids: tuple[str, ...],
    edge_specs: tuple[tuple[str, str, str, str], ...],
) -> LayoutCanvas:
    ids_by_kind = {
        "dataset": dataset_ids,
        "connection": connection_ids,
        "data-view": data_view_ids,
    }
    largest = max((len(values) for values in ids_by_kind.values()), default=0)
    height = max(200.0, _TOP + largest * (_NODE_HEIGHT + _GAP) - (_GAP if largest else 0) + _BOTTOM)
    nodes = tuple(
        LayoutNode(
            _ref(kind, entity_id),
            kind,
            entity_id,
            _COLUMN_X[kind],
            _TOP + index * (_NODE_HEIGHT + _GAP),
        )
        for kind in ("dataset", "connection", "data-view")
        for index, entity_id in enumerate(ids_by_kind[kind])
    )
    by_ref = {node.ref: node for node in nodes}
    edges = tuple(_layout_edge(spec, by_ref) for spec in edge_specs)
    columns = tuple(
        LayoutColumn(kind, _COLUMN_X[kind], _NODE_WIDTH, _TOP, height - _BOTTOM)
        for kind in ("dataset", "connection", "data-view")
    )
    return LayoutCanvas(_CANVAS_WIDTH, height, columns, nodes, edges)


def _layout_edge(spec: tuple[str, str, str, str], by_ref: dict[str, LayoutNode]) -> LayoutEdge:
    edge_id, kind, source_ref, target_ref = spec
    try:
        source = by_ref[source_ref]
        target = by_ref[target_ref]
    except KeyError:
        raise LineageLayoutError("CJA lineage layout validation failed") from None
    start = (source.x + source.width, source.y + source.height / 2)
    end = (target.x, target.y + target.height / 2)
    lane_x = (start[0] + end[0]) / 2
    return LayoutEdge(
        edge_id, kind, source_ref, target_ref, (start, (lane_x, start[1]), (lane_x, end[1]), end)
    )


def validate_lineage_layout(topology: LineageTopology, layout: LineageLayout) -> None:
    """Prove bounds, containment, overlap, endpoints, lanes, and source fidelity."""
    try:
        connection_ids = tuple(item.id for item in topology.connections)
        expected_refs = {
            *(_ref("dataset", item.id) for item in topology.datasets),
            *(_ref("connection", item.id) for item in topology.connections),
            *(_ref("data-view", item.id) for item in topology.data_views),
        }
        if {node.ref for node in layout.global_layout.nodes} != expected_refs:
            raise ValueError
        expected_edges = {
            *(
                (_ref("dataset", edge.dataset_id), _ref("connection", edge.connection_id))
                for edge in topology.dataset_connections
            ),
            *(
                (_ref("connection", edge.connection_id), _ref("data-view", edge.data_view_id))
                for edge in topology.connection_data_views
            ),
        }
        actual_edges = {(edge.source_ref, edge.target_ref) for edge in layout.global_layout.edges}
        if actual_edges != expected_edges or len(actual_edges) != len(layout.global_layout.edges):
            raise ValueError
        if tuple(item.connection_id for item in layout.local_layouts) != connection_ids:
            raise ValueError

        expected_local_refs = {
            connection_id: {_ref("connection", connection_id)} for connection_id in connection_ids
        }
        expected_local_edges: dict[str, set[tuple[str, str]]] = {
            connection_id: set() for connection_id in connection_ids
        }
        for edge in topology.dataset_connections:
            source_ref = _ref("dataset", edge.dataset_id)
            target_ref = _ref("connection", edge.connection_id)
            expected_local_refs[edge.connection_id].add(source_ref)
            expected_local_edges[edge.connection_id].add((source_ref, target_ref))
        for edge in topology.connection_data_views:
            source_ref = _ref("connection", edge.connection_id)
            target_ref = _ref("data-view", edge.data_view_id)
            expected_local_refs[edge.connection_id].add(target_ref)
            expected_local_edges[edge.connection_id].add((source_ref, target_ref))

        for canvas in (
            layout.global_layout,
            *(item.canvas for item in layout.local_layouts),
        ):
            _validate_canvas(canvas)
        for item in layout.local_layouts:
            actual_refs = {node.ref for node in item.canvas.nodes}
            actual_edges = {(edge.source_ref, edge.target_ref) for edge in item.canvas.edges}
            if (
                actual_refs != expected_local_refs[item.connection_id]
                or len(actual_refs) != len(item.canvas.nodes)
                or actual_edges != expected_local_edges[item.connection_id]
                or len(actual_edges) != len(item.canvas.edges)
            ):
                raise ValueError

        node_count = len(topology.datasets) + len(topology.connections) + len(topology.data_views)
        edge_count = len(topology.dataset_connections) + len(topology.connection_data_views)
        expected_full_graph_gated = (
            node_count > FULL_GRAPH_NODE_LIMIT or edge_count > FULL_GRAPH_EDGE_LIMIT
        )
        if layout.full_graph_gated is not expected_full_graph_gated:
            raise ValueError
    except (ArithmeticError, KeyError, TypeError, ValueError):
        raise LineageLayoutError("CJA lineage layout validation failed") from None


def _validate_canvas(canvas: LayoutCanvas) -> None:
    numeric = [canvas.width, canvas.height]
    numeric.extend(
        value
        for column in canvas.columns
        for value in (column.x, column.width, column.top, column.bottom)
    )
    numeric.extend(
        value for node in canvas.nodes for value in (node.x, node.y, node.width, node.height)
    )
    numeric.extend(value for edge in canvas.edges for point in edge.points for value in point)
    if (
        not all(math.isfinite(value) for value in numeric)
        or canvas.width <= 0
        or canvas.height <= 0
    ):
        raise ValueError
    columns = {column.kind: column for column in canvas.columns}
    by_ref = {node.ref: node for node in canvas.nodes}
    if len(by_ref) != len(canvas.nodes):
        raise ValueError
    for node in canvas.nodes:
        column = columns[node.kind]
        if node.width <= 0 or node.height <= 0:
            raise ValueError
        if not (
            node.x >= 0
            and node.y >= 0
            and node.x + node.width <= canvas.width
            and node.y + node.height <= canvas.height
        ):
            raise ValueError
        if not (
            column.x <= node.x
            and node.x + node.width <= column.x + column.width
            and column.top <= node.y
            and node.y + node.height <= column.bottom
        ):
            raise ValueError
    for kind in columns:
        ordered = sorted(
            (node for node in canvas.nodes if node.kind == kind), key=lambda item: item.y
        )
        if any(
            first.y + first.height > second.y
            for first, second in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError
    for edge in canvas.edges:
        if len(edge.points) != 4:
            raise ValueError
        source = by_ref[edge.source_ref]
        target = by_ref[edge.target_ref]
        start = (source.x + source.width, source.y + source.height / 2)
        end = (target.x, target.y + target.height / 2)
        if edge.points[0] != start or edge.points[-1] != end:
            raise ValueError
        lane_a, lane_b = edge.points[1:3]
        if not (start[0] < lane_a[0] == lane_b[0] < end[0]):
            raise ValueError
        if lane_a[1] != start[1] or lane_b[1] != end[1]:
            raise ValueError


__all__ = [
    "FULL_GRAPH_EDGE_LIMIT",
    "FULL_GRAPH_NODE_LIMIT",
    "LayoutCanvas",
    "LayoutColumn",
    "LayoutEdge",
    "LayoutNode",
    "LineageLayout",
    "LineageLayoutError",
    "LocalConnectionLayout",
    "build_lineage_layout",
    "validate_lineage_layout",
]
