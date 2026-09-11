"""Contracts for the standalone CJA lineage layout and renderer."""

from __future__ import annotations

import json
import math
import re
from dataclasses import replace
from pathlib import Path

import pytest

from sdr_visualizer.adapters.cja_lineage import adapt
from sdr_visualizer.analysis.lineage_layout import (
    FULL_GRAPH_EDGE_LIMIT,
    FULL_GRAPH_NODE_LIMIT,
    LineageLayoutError,
    build_lineage_layout,
    validate_lineage_layout,
)
from sdr_visualizer.core.lineage import (
    Availability,
    ConnectionDataView,
    Coverage,
    DatasetConnection,
    LineageConnection,
    LineageDataset,
    LineageDataView,
    LineageTopology,
)
from sdr_visualizer.render.color_packs import (
    COLOR_PACK_CODES,
    InvalidColorPackError,
    resolve_color_pack,
    serialize_color_pack_css,
)
from sdr_visualizer.render.lineage_payload import build_payload
from sdr_visualizer.render.lineage_renderer import render, render_payload

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str, *, scope: str = "Synthetic scope") -> LineageTopology:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return adapt(value, scope_label=scope)


def _empty() -> LineageTopology:
    return LineageTopology("Empty scope", Coverage.ACCESSIBLE_SCOPE, (), (), (), (), ())


def _embedded_payload(html: str) -> dict:
    match = re.search(
        r'<script id="sdr-lineage-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def _two_connection_topology() -> LineageTopology:
    return LineageTopology(
        "Two connections",
        Coverage.ACCESSIBLE_SCOPE,
        (
            LineageDataset("ds-a", "Dataset A", (0,)),
            LineageDataset("ds-b", "Dataset B", (1,)),
        ),
        (
            LineageConnection(
                "conn-a",
                "Connection A",
                Availability.AVAILABLE,
                Availability.AVAILABLE,
                ("ds-a",),
                (0,),
            ),
            LineageConnection(
                "conn-b",
                "Connection B",
                Availability.AVAILABLE,
                Availability.AVAILABLE,
                ("ds-b",),
                (1,),
            ),
        ),
        (
            LineageDataView(
                "dv-a",
                "Data view A",
                "conn-a",
                Availability.AVAILABLE,
                Availability.AVAILABLE,
                (0,),
            ),
            LineageDataView(
                "dv-b",
                "Data view B",
                "conn-b",
                Availability.AVAILABLE,
                Availability.AVAILABLE,
                (1,),
            ),
        ),
        (
            DatasetConnection("ds-a", "conn-a", (0,)),
            DatasetConnection("ds-b", "conn-b", (1,)),
        ),
        (
            ConnectionDataView("conn-a", "dv-a", (0,)),
            ConnectionDataView("conn-b", "dv-b", (1,)),
        ),
    )


def test_layout_is_deterministic_and_satisfies_geometry_invariants() -> None:
    topology = _fixture("cja_lineage_shared.json")

    first = build_lineage_layout(topology)
    second = build_lineage_layout(topology)

    assert first == second
    validate_lineage_layout(topology, first)
    assert {node.kind for node in first.global_layout.nodes} == {
        "dataset",
        "connection",
        "data-view",
    }
    assert len(first.local_layouts) == len(topology.connections)
    for node in first.global_layout.nodes:
        assert all(math.isfinite(value) for value in (node.x, node.y, node.width, node.height))
        assert 0 <= node.x < first.global_layout.width
        assert 0 <= node.y < first.global_layout.height
        assert node.x + node.width <= first.global_layout.width
        assert node.y + node.height <= first.global_layout.height
    for edge in first.global_layout.edges:
        source = next(node for node in first.global_layout.nodes if node.ref == edge.source_ref)
        target = next(node for node in first.global_layout.nodes if node.ref == edge.target_ref)
        assert edge.points[0] == (source.x + source.width, source.y + source.height / 2)
        assert edge.points[-1] == (target.x, target.y + target.height / 2)


def test_local_layout_canvas_must_match_its_declared_connection() -> None:
    topology = _two_connection_topology()
    layout = build_lineage_layout(topology)
    first, second = layout.local_layouts
    swapped = replace(
        layout,
        local_layouts=(
            replace(first, canvas=second.canvas),
            replace(second, canvas=first.canvas),
        ),
    )

    with pytest.raises(LineageLayoutError, match=r"^CJA lineage layout validation failed$"):
        validate_lineage_layout(topology, swapped)


def test_full_graph_gate_must_match_topology_thresholds() -> None:
    topology = _empty()
    layout = build_lineage_layout(topology)

    with pytest.raises(LineageLayoutError, match=r"^CJA lineage layout validation failed$"):
        validate_lineage_layout(topology, replace(layout, full_graph_gated=True))


def test_invalid_numeric_layout_is_a_controlled_content_free_failure() -> None:
    topology = _fixture("cja_lineage_shared.json")
    layout = build_lineage_layout(topology)
    bad_node = replace(layout.global_layout.nodes[0], x=float("nan"))
    bad_global = replace(
        layout.global_layout,
        nodes=(bad_node, *layout.global_layout.nodes[1:]),
    )

    with pytest.raises(LineageLayoutError, match=r"^CJA lineage layout validation failed$") as exc:
        validate_lineage_layout(topology, replace(layout, global_layout=bad_global))

    assert topology.datasets[0].id not in str(exc.value)


def test_payload_is_source_faithful_and_omits_provenance() -> None:
    topology = _fixture("cja_lineage_shared.json")
    html = render(topology)
    match = re.search(
        r'<script id="sdr-lineage-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))

    assert {item["id"] for item in payload["entities"]["datasets"]} == {
        item.id for item in topology.datasets
    }
    assert {item["id"] for item in payload["entities"]["connections"]} == {
        item.id for item in topology.connections
    }
    assert {item["id"] for item in payload["entities"]["data_views"]} == {
        item.id for item in topology.data_views
    }
    assert len(payload["edges"]) == len(topology.dataset_connections) + len(
        topology.connection_data_views
    )
    serialized = json.dumps(payload)
    assert "source_record" not in serialized
    assert "provenance" not in serialized


def test_payload_serializes_optional_relationship_metadata_without_fabricated_defaults() -> None:
    payload = build_payload(_fixture("cja_lineage_enriched.json"))
    edges = {
        (edge["source_id"], edge["target_id"]): edge
        for edge in payload["edges"]
        if edge["kind"] == "dataset-connection"
    }

    event = edges[("ds-shared", "conn-event")]["connection_metadata"]
    profile = edges[("ds-shared", "conn-profile")]["connection_metadata"]
    assert event["role"] == "event"
    assert event["schema"]["ref"]["contentType"].endswith("version=1")
    assert event["identity"]["usePrimaryIdNamespace"] is False
    assert event["ingestion"]["backfillSummary"]["failed"] == 0
    assert event["ingestion"]["backfillSummary"]["invalid"] is False
    assert "futureField" not in event
    assert profile == {
        "role": "profile",
        "identity": {
            "namespace": None,
            "usePrimaryIdNamespace": False,
            "namespaceColumn": "",
        },
        "dataSource": {},
    }
    assert edges[("ds-summary", "conn-summary")]["connection_metadata"]["lookup"] == {
        "parentFields": []
    }

    legacy = build_payload(_fixture("cja_lineage_shared.json"))
    assert all("connection_metadata" not in edge for edge in legacy["edges"])


def test_payload_keeps_unicode_search_source_text_unfolded() -> None:
    topology = LineageTopology(
        "Unicode search",
        Coverage.ACCESSIBLE_SCOPE,
        (),
        (),
        (
            LineageDataView(
                "dv-strasse",
                "Straße 🧪",
                None,
                Availability.UNAVAILABLE,
                Availability.UNAVAILABLE,
                (0,),
            ),
        ),
        (),
        (),
    )

    item = build_payload(topology)["entities"]["data_views"][0]

    assert item["search_text"] == "Straße 🧪 dv-strasse"
    assert item["name"] == "Straße 🧪"


def test_shared_topology_prepared_data_grows_linearly() -> None:
    dataset_count = 120
    data_view_count = 180
    connection = LineageConnection(
        "conn",
        "Shared",
        Availability.AVAILABLE,
        Availability.AVAILABLE,
        tuple(f"ds-{index:03d}" for index in range(dataset_count)),
        (0,),
    )
    topology = LineageTopology(
        "Scale",
        Coverage.ACCESSIBLE_SCOPE,
        tuple(
            LineageDataset(f"ds-{index:03d}", f"Dataset {index}", (0,))
            for index in range(dataset_count)
        ),
        (connection,),
        tuple(
            LineageDataView(
                f"dv-{index:03d}",
                f"View {index}",
                "conn",
                Availability.AVAILABLE,
                Availability.AVAILABLE,
                (index,),
            )
            for index in range(data_view_count)
        ),
        tuple(DatasetConnection(f"ds-{index:03d}", "conn", (0,)) for index in range(dataset_count)),
        tuple(
            ConnectionDataView("conn", f"dv-{index:03d}", (index,))
            for index in range(data_view_count)
        ),
    )
    payload = build_payload(topology)
    entity_count = dataset_count + data_view_count + 1
    edge_count = dataset_count + data_view_count
    global_entries = len(payload["geometry"]["global"]["nodes"]) + len(
        payload["geometry"]["global"]["edges"]
    )
    local_entries = sum(
        len(item["nodes"]) + len(item["edges"])
        for item in payload["geometry"]["local_by_connection"]
    )

    assert global_entries == entity_count + edge_count
    assert local_entries == entity_count + edge_count
    assert len(payload["adjacency"]["dataset_ids_by_connection"]["conn"]) == dataset_count
    assert len(payload["adjacency"]["data_view_ids_by_connection"]["conn"]) == data_view_count


def test_full_graph_gate_is_explicit_at_provisional_limits() -> None:
    payload = build_payload(_empty())
    assert payload["gating"]["node_limit"] == FULL_GRAPH_NODE_LIMIT == 1000
    assert payload["gating"]["edge_limit"] == FULL_GRAPH_EDGE_LIMIT == 8000

    large = replace(
        _empty(),
        data_views=tuple(
            LineageDataView(
                f"dv-{index:04d}",
                f"View {index}",
                None,
                Availability.UNAVAILABLE,
                Availability.UNAVAILABLE,
                (index,),
            )
            for index in range(FULL_GRAPH_NODE_LIMIT + 1)
        ),
    )
    gated_payload = build_payload(large)
    assert gated_payload["gating"]["full_graph_gated"] is True
    gated_payload["gating"]["node_limit"] = 1_234
    gated_payload["gating"]["edge_limit"] = 5_678
    gated_html = render_payload(gated_payload)
    assert "Large graph warning: 1001 nodes and 0 relationships" in gated_html
    assert "exceed the provisional 1234-node or 5678-relationship gate" in gated_html
    assert "<svg" not in gated_html.casefold()


def test_hostile_names_are_inert_and_valid_non_bmp_text_round_trips() -> None:
    topology = _fixture("cja_lineage_hostile.json", scope="Scope </script> 😀")
    html = render(topology, title="Lineage </title><script>alert(9)</script> 😀")
    payload_match = re.search(
        r'<script id="sdr-lineage-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )

    assert payload_match is not None
    payload = json.loads(payload_match.group(1))
    assert payload["scope_label"] == "Scope </script> 😀"
    assert payload["entities"]["data_views"][0]["name"].endswith("😀")
    assert "<img src=x" not in html
    assert "</title><script>" not in html
    assert "\\u003c/script>" in payload_match.group(1)


def test_renderer_is_byte_stable_self_contained_and_has_no_runtime_targets() -> None:
    topology = _fixture("cja_lineage_shared.json")
    first = render(topology)
    second = render(topology)

    assert first == second
    assert _embedded_payload(first) == build_payload(topology)
    assert first.index("window.SdrCjaLineageGraph") < first.index("window.SdrCjaLineageRoles")
    assert first.index("window.SdrCjaLineageRoles") < first.index("window.__cjaLineagePoc")
    assert first.lstrip().startswith("<!doctype html>")
    assert "<style>" in first and "<script>" in first
    assert re.search(r"<(?:script|img|link)[^>]+(?:src|href)\s*=", first, re.I) is None
    assert re.search(r"https?://|@import|\bfetch\s*\(", first, re.I) is None
    assert 'data-color-pack="default"' in first
    assert "throughput" not in first.casefold()
    assert "activity" not in first.casefold()


@pytest.mark.parametrize("code", COLOR_PACK_CODES)
def test_lineage_renderer_uses_visualizer_shell_and_color_pack_contract(code: str) -> None:
    topology = _fixture("cja_lineage_shared.json")

    html = render(topology, color_pack=code)
    css = serialize_color_pack_css(resolve_color_pack(code))

    assert f'<html lang="en" data-color-pack="{code}">' in html
    assert f"Color pack: {code}" in html
    assert 'class="header"' in html
    assert 'class="header-inner"' in html
    assert 'class="meta-strip ui"' in html
    assert 'class="view-nav ui"' in html
    assert 'class="footer ui"' in html
    assert html.index("/* ---------- Reset & base ---------- */") < html.index(css)
    assert html.index(css) < html.index("</style>")


def test_lineage_color_pack_is_presentation_only_and_does_not_leak_state() -> None:
    topology = _fixture("cja_lineage_shared.json")
    default = render(topology)
    blue = render(topology, color_pack="BLUE")

    assert _embedded_payload(default) == _embedded_payload(blue)
    assert default == render(topology, color_pack="default")
    assert resolve_color_pack("BLUE").roles["accent-primary"] not in default


@pytest.mark.parametrize("entrypoint", [render, render_payload])
def test_lineage_renderer_rejects_unknown_color_pack(entrypoint) -> None:
    topology = _fixture("cja_lineage_shared.json")
    value = topology if entrypoint is render else build_payload(topology)

    with pytest.raises(InvalidColorPackError, match="available color packs"):
        entrypoint(value, color_pack="blue")


def test_default_and_empty_overviews_are_inert_without_svg() -> None:
    populated = render(_fixture("cja_lineage_shared.json"))
    empty = render(_empty())
    empty_payload = build_payload(_empty())

    assert "<svg" not in populated.casefold()
    assert "<svg" not in empty.casefold()
    assert "No accessible lineage records were reported" in empty
    assert 'id="lineage-search"' in empty and "disabled" in empty
    assert empty_payload["counts"] == {
        "datasets": 0,
        "connections": 0,
        "data_views": 0,
        "edges": 0,
    }
    assert empty_payload["coverage"]["state"] == "accessible-scope-completeness-unknown"


def test_interaction_shell_exposes_semantic_lazy_controls() -> None:
    html = render(_fixture("cja_lineage_shared.json"))

    assert 'id="lineage-results"' in html
    assert 'id="lineage-details"' in html
    assert 'id="lineage-relationship-details"' in html
    assert 'id="lineage-full-graph"' in html
    assert 'aria-controls="lineage-results"' in html
    assert "window.__cjaLineagePoc" in html
    assert "createElementNS" in html
    assert "innerHTML" not in html
    assert "history.pushState" not in html
    assert "history.replaceState" not in html
    assert "No backing datasets were reported" in html
    assert "Backing datasets unavailable" in html


def test_render_payload_rejects_non_finite_values_before_json_embedding() -> None:
    payload = build_payload(_empty())
    payload["geometry"]["global"]["width"] = float("inf")

    with pytest.raises(LineageLayoutError, match="CJA lineage render failed"):
        render_payload(payload)


@pytest.mark.parametrize(
    "title",
    ["", " surrounding ", "bad\x00title", "\ud800", "report\u202etitle", "report\u2067title"],
)
def test_title_validation_fails_with_a_controlled_message(title: str) -> None:
    with pytest.raises(LineageLayoutError, match=r"^CJA lineage render failed$"):
        render(_empty(), title=title)


@pytest.mark.parametrize(
    "corruption",
    [
        "missing-node",
        "missing-edge",
        "duplicate-edge",
        "missing-local",
        "duplicate-node",
        "zero-width",
        "outside-canvas",
        "outside-column",
        "overlap",
        "short-edge",
        "endpoint",
        "lane-x",
        "lane-y",
    ],
)
def test_corrupt_geometry_is_rejected_without_content(corruption):
    topology = _fixture("cja_lineage_shared.json")
    layout = build_lineage_layout(topology)
    canvas = layout.global_layout
    nodes, edges = list(canvas.nodes), list(canvas.edges)
    if corruption == "missing-node":
        nodes.pop()
    elif corruption == "missing-edge":
        edges.pop()
    elif corruption == "duplicate-edge":
        edges.append(edges[0])
    elif corruption == "missing-local":
        layout = replace(layout, local_layouts=())
    elif corruption == "duplicate-node":
        nodes.append(nodes[0])
    elif corruption == "zero-width":
        nodes[0] = replace(nodes[0], width=0)
    elif corruption == "outside-canvas":
        nodes[0] = replace(nodes[0], x=-1)
    elif corruption == "outside-column":
        nodes[0] = replace(nodes[0], x=nodes[0].x + 1)
    elif corruption == "overlap":
        nodes[1] = replace(nodes[1], y=nodes[0].y)
    else:
        points = list(edges[0].points)
        if corruption == "short-edge":
            points.pop()
        elif corruption == "endpoint":
            points[0] = (0, 0)
        elif corruption == "lane-x":
            points[1] = (0, points[1][1])
        elif corruption == "lane-y":
            points[1] = (points[1][0], points[1][1] + 1)
        edges[0] = replace(edges[0], points=tuple(points))
    layout = replace(layout, global_layout=replace(canvas, nodes=tuple(nodes), edges=tuple(edges)))
    with pytest.raises(LineageLayoutError, match="^CJA lineage layout validation failed$"):
        validate_lineage_layout(topology, layout)


def test_supplied_layout_is_validated_and_dangling_relationship_rejected():
    topology = _fixture("cja_lineage_shared.json")
    layout = build_lineage_layout(topology)
    assert build_payload(topology, layout=layout) == build_payload(topology)
    with pytest.raises(LineageLayoutError):
        build_payload(topology, layout=replace(layout, full_graph_gated=True))
    broken = replace(topology, datasets=())
    with pytest.raises(LineageLayoutError):
        build_lineage_layout(broken)
