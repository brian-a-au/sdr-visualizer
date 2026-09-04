"""Focused browser contracts for the private CJA lineage POC."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")

from sdr_visualizer.adapters.cja_lineage import adapt  # noqa: E402
from sdr_visualizer.core.lineage import (  # noqa: E402
    Availability,
    ConnectionDataView,
    Coverage,
    DatasetConnection,
    LineageConnection,
    LineageDataset,
    LineageDataView,
    LineageTopology,
)
from sdr_visualizer.render.color_packs import COLOR_PACK_CODES, resolve_color_pack  # noqa: E402
from sdr_visualizer.render.lineage_renderer import render  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module", params=["chromium", "webkit"])
def lineage_page(request):
    with playwright_sync.sync_playwright() as pw:
        try:
            browser = getattr(pw, request.param).launch(headless=True)
        except Exception as exc:
            system_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            if request.param != "chromium" or not system_chrome.is_file():
                pytest.skip(f"{request.param} not available: {exc}")
            try:
                browser = pw.chromium.launch(headless=True, executable_path=str(system_chrome))
            except Exception as system_exc:
                pytest.skip(f"chromium not available: {system_exc}")
        try:
            yield browser.new_page()
        finally:
            browser.close()


@pytest.fixture(autouse=True)
def reset_lineage_media(lineage_page):
    lineage_page.emulate_media(media="screen", reduced_motion="no-preference")
    yield
    lineage_page.emulate_media(media="screen", reduced_motion="no-preference")


def _render_to(tmp_path: Path, fixture: str, name: str = "lineage.html") -> Path:
    source = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    return _render_source(tmp_path, source, name)


def _render_source(tmp_path: Path, source: dict, name: str) -> Path:
    path = tmp_path / name
    path.write_text(
        render(adapt(source, scope_label="Synthetic scope")),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("color_pack", COLOR_PACK_CODES)
def test_visualizer_shell_color_packs_and_mobile_width(lineage_page, tmp_path, color_pack):
    source = json.loads((FIXTURES / "cja_lineage_shared.json").read_text(encoding="utf-8"))
    path = tmp_path / f"lineage-{color_pack}.html"
    path.write_text(
        render(adapt(source, scope_label="Synthetic scope"), color_pack=color_pack),
        encoding="utf-8",
    )
    lineage_page.set_viewport_size({"width": 390, "height": 844})
    lineage_page.goto(path.as_uri())

    assert lineage_page.locator("html").get_attribute("data-color-pack") == color_pack
    assert lineage_page.locator(".header").is_visible()
    assert (
        lineage_page.locator(".view-nav .view-button").evaluate("element => element.tagName")
        == "SPAN"
    )
    assert f"Color pack: {color_pack}" in lineage_page.locator(".footer").inner_text()
    assert (
        lineage_page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--sdr-accent-primary').trim()"
        )
        == resolve_color_pack(color_pack).roles["accent-primary"]
    )
    lineage_page.locator("#lineage-full-graph").click()
    assert lineage_page.locator("#lineage-stage-toolbar").is_visible()
    assert lineage_page.locator("#lineage-theme-toggle").is_visible()
    lineage_page.locator("#lineage-theme-toggle").click()
    assert lineage_page.locator("html").get_attribute("data-theme") == "dark"
    assert (
        lineage_page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--sdr-surface-page').trim()"
        )
        == "#0B1013"
    )
    assert (
        lineage_page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--sdr-accent-primary').trim()"
        )
        == resolve_color_pack(color_pack).roles["accent-primary"]
    )
    assert lineage_page.evaluate("document.documentElement.scrollWidth") == lineage_page.evaluate(
        "document.documentElement.clientWidth"
    )


def test_live_scale_role_overview_is_immediately_discoverable(lineage_page, tmp_path):
    source = {
        "dataViews": [
            {
                "id": "dv-commerce",
                "name": "Commerce view",
                "connection": {"id": "conn-commerce", "name": "Commerce connection"},
                "datasets": [
                    {
                        "id": "ds-event",
                        "name": "Event dataset",
                        "connectionMetadata": {"role": "event"},
                    },
                    {
                        "id": "ds-lookup",
                        "name": "Lookup dataset",
                        "connectionMetadata": {"role": "lookup"},
                    },
                    {
                        "id": "ds-adhoc",
                        "name": "Ad hoc dataset",
                        "connectionMetadata": {"role": "adhoc"},
                    },
                ],
            },
            {
                "id": "dv-customer",
                "name": "Customer view",
                "connection": {"id": "conn-customer", "name": "Customer connection"},
                "datasets": [
                    {
                        "id": "ds-profile",
                        "name": "Profile dataset",
                        "connectionMetadata": {"role": "profile"},
                    },
                    {
                        "id": "ds-summary",
                        "name": "Summary dataset",
                        "connectionMetadata": {"role": "summary"},
                    },
                ],
            },
        ],
        "count": 2,
    }
    path = _render_source(tmp_path, source, "live-scale-overview.html")
    lineage_page.goto(path.as_uri())

    coverage = lineage_page.locator("#lineage-role-coverage")
    assert coverage.is_visible()
    assert "5 of 5 dataset relationships include Connection metadata" in coverage.inner_text()
    assert "2 of 2 Connections have accessible backing datasets" in coverage.inner_text()
    filters = lineage_page.locator("#lineage-global-role-filters button")
    assert filters.all_text_contents() == [
        "All 5",
        "Event 1",
        "Profile 1",
        "Lookup 1",
        "Summary 1",
        "adhoc 1",
        "Not reported 0",
        "Reported null 0",
        "Reported empty string 0",
    ]
    for key in ["missing", "null", "empty"]:
        assert lineage_page.locator(f'[data-global-role-key="{key}"]').is_disabled()

    assert lineage_page.locator("#lineage-stage").get_attribute("data-state") == "overview"
    assert lineage_page.locator("#lineage-connection-overview-heading").inner_text() == (
        "Connection overview"
    )
    assert lineage_page.locator("#lineage-connection-overview-summary").inner_text() == (
        "2 of 2 Connections shown."
    )
    assert lineage_page.locator(".connection-overview-card").count() == 2
    commerce_card = lineage_page.locator('[data-connection-id="conn-commerce"]')
    assert (
        commerce_card.locator(".connection-overview-role-band").get_attribute("aria-label")
        == "Role mix: Event 1, Lookup 1, adhoc 1"
    )
    assert commerce_card.locator(".connection-overview-role-segment").count() == 3

    lineage_page.locator('[data-global-role-key="event"]').click()
    assert (
        lineage_page.locator('[data-global-role-key="event"]').get_attribute("aria-pressed")
        == "true"
    )
    assert lineage_page.locator('[data-global-role-key="event"]').evaluate(
        "element => element === document.activeElement"
    )
    assert lineage_page.locator("#lineage-connection-overview-summary").inner_text() == (
        "1 of 2 Connections shown for Event."
    )
    cards = lineage_page.locator(".connection-overview-card")
    assert cards.count() == 1
    assert "Commerce connection" in cards.first.inner_text()

    lineage_page.locator("#lineage-full-graph").click()
    assert (
        lineage_page.locator(".lineage-edge--dataset-connection.is-global-role-match").count() == 1
    )
    assert (
        lineage_page.locator(".lineage-edge--dataset-connection.is-global-role-muted").count() == 4
    )

    lineage_page.locator('[data-global-role-key="all"]').click()
    lineage_page.locator("#lineage-show-overview").click()
    assert lineage_page.locator(".connection-overview-card").count() == 2
    lineage_page.locator('[data-connection-id="conn-commerce"]').click()
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().selectedConnectionId") == (
        "conn-commerce"
    )
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().selectedDataViewId") is None
    assert lineage_page.locator("#lineage-stage svg").count() == 0
    inspector = lineage_page.locator("#lineage-connection-inspector")
    assert inspector.is_visible()
    assert "Commerce connection" in inspector.inner_text()
    assert "3 backing datasets" in inspector.inner_text()
    assert "1 accessible data view" in inspector.inner_text()
    assert (
        lineage_page.locator('[data-connection-id="conn-commerce"]').get_attribute("aria-pressed")
        == "true"
    )
    assert lineage_page.locator("#lineage-connection-inspector-heading").evaluate(
        "element => element === document.activeElement"
    )

    inspector.locator('[data-data-view-id="dv-commerce"]').click()
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().selectedDataViewId") == (
        "dv-commerce"
    )
    assert lineage_page.locator("#lineage-stage svg").count() == 1


def test_connection_overview_selection_is_keyboard_reversible(lineage_page, tmp_path):
    path = _render_to(tmp_path, "cja_lineage_shared.json", "connection-selection.html")
    lineage_page.set_viewport_size({"width": 390, "height": 844})
    lineage_page.goto(path.as_uri())

    connection = lineage_page.locator(".connection-overview-card").first
    connection_id = connection.get_attribute("data-connection-id")
    connection.click()
    assert lineage_page.locator("#lineage-connection-inspector").is_visible()
    assert lineage_page.evaluate("document.documentElement.scrollWidth") == lineage_page.evaluate(
        "document.documentElement.clientWidth"
    )

    lineage_page.keyboard.press("Escape")
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().selectedConnectionId") is None
    assert lineage_page.locator("#lineage-connection-inspector").count() == 0
    replacement = lineage_page.locator(f'[data-connection-id="{connection_id}"]')
    assert replacement.evaluate("element => element === document.activeElement")


def test_entity_search_and_return_to_connection(lineage_page, tmp_path):
    source = json.loads((FIXTURES / "cja_lineage_shared.json").read_text())
    source["dataViews"].append(
        {
            "id": "dv-other",
            "name": "Other",
            "connection": {"id": "conn-other", "name": "Other connection"},
            "datasets": [{"id": "ds-web", "name": "Web events"}],
        }
    )
    source["count"] = 3
    path = _render_source(tmp_path, source, "entity-search.html")
    lineage_page.set_viewport_size({"width": 390, "height": 844})
    lineage_page.goto(path.as_uri())
    assert lineage_page.locator("#lineage-theme-toggle").is_visible()
    lineage_page.locator("#lineage-search-kind").select_option("dataset")
    lineage_page.locator("#lineage-search").fill("ds-web")
    lineage_page.locator('#lineage-results [data-search-dataset-id="ds-web"]').click()
    connections = lineage_page.locator("#lineage-results [data-search-connection-id]")
    assert connections.count() == 2
    connections.first.click()
    inspector = lineage_page.locator("#lineage-connection-inspector")
    assert inspector.is_visible()
    inspector.locator("[data-data-view-id]").first.click()
    assert lineage_page.locator("#lineage-back-connection").is_visible()
    lineage_page.locator("#lineage-back-connection").click()
    assert inspector.is_visible()
    assert lineage_page.locator("#lineage-connection-inspector-heading").evaluate(
        "element => element === document.activeElement"
    )
    assert lineage_page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    lineage_page.locator("#lineage-search-kind").select_option("connection")
    lineage_page.locator("#lineage-search").fill("conn-shared")
    assert lineage_page.locator("#lineage-results [data-search-connection-id]").count() == 1


def test_inert_search_selection_and_private_reload(lineage_page, tmp_path):
    path = _render_to(tmp_path, "cja_lineage_shared.json")
    requests: list[str] = []
    lineage_page.on("request", lambda request: requests.append(request.url))
    lineage_page.goto(path.as_uri())
    initial_url = lineage_page.url
    assert lineage_page.locator("svg").count() == 0

    lineage_page.fill("#lineage-search", "production")
    result = lineage_page.locator("#lineage-results button").first
    assert "dv-production" in result.inner_text()
    result.click()
    assert lineage_page.locator("#lineage-stage svg").count() == 1
    assert "Shared connection" in lineage_page.locator("#lineage-details").inner_text()
    assert "Web events" in lineage_page.locator("#lineage-details").inner_text()
    assert lineage_page.url == initial_url

    lineage_page.reload()
    assert lineage_page.locator("svg").count() == 0
    assert lineage_page.locator("#lineage-details").is_hidden()
    assert lineage_page.url == initial_url
    assert requests == [path.as_uri(), path.as_uri()]


def test_rendered_metadata_markup_is_inert_and_makes_no_outbound_request(lineage_page, tmp_path):
    hostile = '<img src="https://example.invalid/lineage-probe">'
    source = {
        "dataViews": [
            {
                "id": "dv-hostile-metadata",
                "name": "Hostile metadata view",
                "connection": {"id": "conn-hostile", "name": "Hostile connection"},
                "datasets": [
                    {
                        "id": "ds-hostile",
                        "name": "Hostile dataset",
                        "connectionMetadata": {
                            "role": hostile,
                            "schema": {"name": hostile},
                            "dataSource": {"description": hostile},
                        },
                    }
                ],
            }
        ],
        "count": 1,
    }
    path = _render_source(tmp_path, source, "hostile-metadata.html")
    requests: list[str] = []
    lineage_page.on("request", lambda request: requests.append(request.url))
    lineage_page.goto(path.as_uri())
    lineage_page.fill("#lineage-search", "hostile metadata")
    lineage_page.locator("#lineage-results button").first.click()
    lineage_page.locator("#lineage-datasets button").first.click()
    assert hostile in lineage_page.locator("#lineage-relationship-details").inner_text()
    assert lineage_page.locator("#lineage-relationship-details img").count() == 0
    assert requests == [path.as_uri()]


def test_route_pause_clear_and_escape_focus(lineage_page, tmp_path):
    path = _render_to(tmp_path, "cja_lineage_shared.json", "route.html")
    lineage_page.goto(path.as_uri())
    lineage_page.fill("#lineage-search", "production")
    result = lineage_page.locator("#lineage-results button").first
    result.click()
    assert lineage_page.locator(".route-marker").count() == 0

    dataset = lineage_page.locator("#lineage-datasets button").first
    dataset.click()
    assert lineage_page.locator(".lineage-edge.is-route").count() == 2
    assert lineage_page.locator(".route-marker").count() == 1
    assert (
        "No connection-scoped dataset metadata was reported"
        in lineage_page.locator("#lineage-relationship-details").inner_text()
    )
    pause = lineage_page.locator("#lineage-flow-pause")
    assert pause.evaluate("node => node.closest('.stage-shell') !== null")
    assert pause.evaluate("node => node.closest('#lineage-stage') === null")
    pause.click()
    assert pause.get_attribute("aria-pressed") == "true"
    lineage_page.keyboard.press("Escape")
    assert lineage_page.locator(".route-marker").count() == 0
    assert lineage_page.locator("#lineage-details").is_visible()
    assert lineage_page.evaluate("document.activeElement.dataset.datasetId") == "ds-mobile"
    lineage_page.keyboard.press("Escape")
    assert lineage_page.locator("#lineage-details").is_hidden()
    assert lineage_page.evaluate("document.activeElement.dataset.dataViewId") == "dv-production"


def test_relationship_metadata_inspector_is_scoped_to_selected_connection(lineage_page, tmp_path):
    path = _render_to(tmp_path, "cja_lineage_enriched.json", "metadata.html")
    lineage_page.goto(path.as_uri())

    role_legend = lineage_page.locator("#lineage-role-legend")
    assert role_legend.is_visible()
    legend_text = role_legend.inner_text()
    assert "CONNECTION-CONFIGURED ROLE" in legend_text
    assert "Event 1" in legend_text
    assert "Profile 1" in legend_text
    assert "Lookup 1" in legend_text
    assert "Summary 1" in legend_text

    lineage_page.locator("#lineage-full-graph").click()
    for role in ("event", "profile", "lookup", "summary"):
        edge = lineage_page.locator(f".lineage-edge-role--{role}")
        assert edge.count() == 1
        assert f"Connection role: {role.title()}" in edge.locator("title").text_content()

    lineage_page.fill("#lineage-search", "event view")
    lineage_page.locator("#lineage-results button").first.click()
    dataset = lineage_page.locator("#lineage-datasets button").first
    assert "EVENT ROLE" in dataset.inner_text()
    dataset.click()
    inspector = lineage_page.locator("#lineage-relationship-details")
    assert inspector.is_visible()
    event_text = inspector.inner_text()
    assert "Event" in event_text
    assert "Web Event Schema" in event_text
    assert "Use primary ID namespace\nFalse" in event_text
    assert "Last ingested\n2026-08-29T12:34:56Z" in event_text
    assert "do not establish end-to-end CJA reporting readiness" in event_text
    summary_text = lineage_page.locator("#lineage-relationship-summary").inner_text()
    assert "Event role" in summary_text
    assert "Schema: Web Event Schema" in summary_text
    assert "Identity: ECID" in summary_text
    assert "Streaming: True" in summary_text
    assert "Backfill: 2 of 2 completed" in summary_text
    assert "Source: Web Data" in summary_text

    lineage_page.fill("#lineage-search", "profile view")
    lineage_page.locator("#lineage-results button").first.click()
    profile_dataset = lineage_page.locator("#lineage-datasets button").first
    assert "PROFILE ROLE" in profile_dataset.inner_text()
    profile_dataset.click()
    profile_text = inspector.inner_text()
    assert "Profile" in profile_text
    assert "Reported null" in profile_text
    assert "Reported empty string" in profile_text
    assert "Web Event Schema" not in profile_text

    lineage_page.fill("#lineage-search", "lookup view")
    lineage_page.locator("#lineage-results button").first.click()
    lineage_page.locator("#lineage-datasets button").first.click()
    assert (
        "Lookup key: accountId"
        in lineage_page.locator("#lineage-relationship-summary").inner_text()
    )
    lookup_context = lineage_page.locator("#lineage-relationship-context").inner_text()
    assert "Lookup parent" in lookup_context
    assert "Shared dataset" in lookup_context
    assert "not in this Connection's accessible backing set" in lookup_context


def test_backing_datasets_filter_by_connection_role_and_clear_hidden_route(lineage_page, tmp_path):
    source = {
        "dataViews": [
            {
                "id": "dv-role-filter",
                "name": "Role filter view",
                "connection": {"id": "conn-role-filter", "name": "Role filter connection"},
                "datasets": [
                    {
                        "id": "ds-event",
                        "name": "Event dataset",
                        "connectionMetadata": {"role": "event"},
                    },
                    {
                        "id": "ds-lookup",
                        "name": "Lookup dataset",
                        "connectionMetadata": {
                            "role": "lookup",
                            "lookup": {"parentDatasetId": "ds-event"},
                        },
                    },
                    {"id": "ds-unreported", "name": "Unreported dataset"},
                ],
            }
        ],
        "count": 1,
    }
    path = _render_source(tmp_path, source, "role-filter.html")
    lineage_page.goto(path.as_uri())
    lineage_page.fill("#lineage-search", "role filter view")
    lineage_page.locator("#lineage-results button").first.click()

    role_filter = lineage_page.locator("#lineage-role-filter")
    assert role_filter.is_visible()
    assert role_filter.locator("option").all_text_contents() == [
        "All roles (3)",
        "Event (1)",
        "Lookup (1)",
        "Not reported (1)",
    ]
    role_filter.select_option("lookup")
    dataset_buttons = lineage_page.locator("#lineage-datasets [data-dataset-id]")
    assert dataset_buttons.count() == 1
    assert "Lookup dataset" in dataset_buttons.first.inner_text()
    assert (
        "1 of 3 backing datasets match Lookup"
        in lineage_page.locator("#lineage-datasets").inner_text()
    )

    dataset_buttons.first.click()
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().activeDatasetId") == "ds-lookup"
    lookup_context = lineage_page.locator("#lineage-relationship-context").inner_text()
    assert "Event dataset (ds-event)" in lookup_context
    assert "present in this Connection's accessible backing set" in lookup_context
    role_filter = lineage_page.locator("#lineage-role-filter")
    role_filter.select_option("event")
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().activeDatasetId") is None
    assert lineage_page.locator("#lineage-relationship-details").is_hidden()
    assert lineage_page.locator("#lineage-datasets [data-dataset-id]").count() == 1
    assert (
        "Event dataset"
        in lineage_page.locator("#lineage-datasets [data-dataset-id]").first.inner_text()
    )


def test_relationship_inspector_preserves_explicit_empty_metadata_values(lineage_page, tmp_path):
    source = {
        "dataViews": [
            {
                "id": "dv-empty-metadata",
                "name": "Empty metadata view",
                "connection": {"id": "conn-empty", "name": "Empty metadata connection"},
                "datasets": [
                    {
                        "id": "ds-empty",
                        "name": "Empty metadata dataset",
                        "connectionMetadata": {
                            "role": "",
                            "lookup": {"parentFields": []},
                            "dataSource": {},
                        },
                    }
                ],
            }
        ],
        "count": 1,
    }
    path = _render_source(tmp_path, source, "empty-metadata.html")
    lineage_page.goto(path.as_uri())
    lineage_page.fill("#lineage-search", "empty metadata view")
    lineage_page.locator("#lineage-results button").first.click()
    dataset = lineage_page.locator("#lineage-datasets button").first
    assert dataset.locator(".relationship-role").count() == 0
    dataset.click()

    inspector_text = lineage_page.locator("#lineage-relationship-details").inner_text()
    assert "Reported role\nReported empty string" in inspector_text
    assert "Parent fields\nReported empty list" in inspector_text
    assert "Reported object has no recognized fields." in inspector_text


def test_role_states_custom_role_nested_sentinels_and_neutral_summary(lineage_page, tmp_path):
    source = {
        "dataViews": [
            {
                "id": "dv-role-states",
                "name": "Role states view",
                "connection": {"id": "conn-role-states", "name": "Role states connection"},
                "datasets": [
                    {"id": "ds-missing", "name": "Missing role"},
                    {
                        "id": "ds-empty-object",
                        "name": "Empty metadata object",
                        "connectionMetadata": {},
                    },
                    {
                        "id": "ds-null",
                        "name": "Null role and groups",
                        "connectionMetadata": {
                            "role": None,
                            "schema": {"ref": None},
                            "ingestion": {"backfillSummary": None},
                        },
                    },
                    {
                        "id": "ds-empty",
                        "name": "Empty role and groups",
                        "connectionMetadata": {
                            "role": "",
                            "schema": {"ref": {}},
                            "ingestion": {"backfillSummary": {}},
                        },
                    },
                    {
                        "id": "ds-event",
                        "name": "Known event role",
                        "connectionMetadata": {"role": "event"},
                    },
                    {
                        "id": "ds-custom",
                        "name": "Custom hybrid role",
                        "connectionMetadata": {"role": "Hybrid audience"},
                    },
                ],
            }
        ],
        "count": 1,
    }
    path = _render_source(tmp_path, source, "role-states.html")
    lineage_page.goto(path.as_uri())
    lineage_page.fill("#lineage-search", "role states")
    lineage_page.locator("#lineage-results button").first.click()

    assert (
        "5 of 6 dataset relationships include Connection metadata"
        in lineage_page.locator("#lineage-role-coverage-copy").inner_text()
    )
    assert lineage_page.locator('[data-global-role-key="missing"]').inner_text() == (
        "Not reported 2"
    )
    assert lineage_page.locator('[data-global-role-key="null"]').inner_text() == ("Reported null 1")
    assert lineage_page.locator('[data-global-role-key="empty"]').inner_text() == (
        "Reported empty string 1"
    )

    role_filter = lineage_page.locator("#lineage-role-filter")
    assert role_filter.locator("option").all_text_contents() == [
        "All roles (6)",
        "Event (1)",
        "Hybrid audience (1)",
        "Not reported (2)",
        "Reported empty string (1)",
        "Reported null (1)",
    ]
    role_filter.select_option("missing")
    assert set(
        lineage_page.locator("#lineage-datasets [data-dataset-id]").evaluate_all(
            "nodes => nodes.map(node => node.dataset.datasetId)"
        )
    ) == {"ds-missing", "ds-empty-object"}
    role_filter = lineage_page.locator("#lineage-role-filter")
    for value, dataset_id in [
        ("null", "ds-null"),
        ("empty", "ds-empty"),
        ("event", "ds-event"),
        ("custom:Hybrid audience", "ds-custom"),
    ]:
        role_filter.select_option(value)
        assert (
            lineage_page.locator("#lineage-datasets [data-dataset-id]").first.get_attribute(
                "data-dataset-id"
            )
            == dataset_id
        )
        role_filter = lineage_page.locator("#lineage-role-filter")

    role_filter.select_option("custom:Hybrid audience")
    custom_dataset = lineage_page.locator('[data-dataset-id="ds-custom"]')
    assert "HYBRID AUDIENCE ROLE" in custom_dataset.inner_text()
    assert "relationship-role--other" in custom_dataset.locator(".relationship-role").get_attribute(
        "class"
    )
    custom_dataset.click()
    lineage_page.locator("#lineage-full-graph").click()
    custom_edge = lineage_page.locator(
        '.lineage-edge-role--other[data-connection-role="Hybrid audience"]'
    )
    assert custom_edge.count() == 1
    assert "Connection role: Hybrid audience" in custom_edge.locator("title").text_content()

    lineage_page.locator("#lineage-clear-route").click()
    role_filter = lineage_page.locator("#lineage-role-filter")
    role_filter.select_option("null")
    lineage_page.locator('[data-dataset-id="ds-null"]').click()
    inspector = lineage_page.locator("#lineage-relationship-details")
    assert "Schema reference\nReported null" in inspector.inner_text()
    assert "Backfill summary\nReported null" in inspector.inner_text()
    summary_chips = lineage_page.locator("#lineage-relationship-summary > span")
    assert summary_chips.count() == 1
    assert "relationship-role--" not in summary_chips.first.get_attribute("class")
    light_style = summary_chips.first.evaluate(
        "node => [getComputedStyle(node).borderColor, getComputedStyle(node).backgroundColor]"
    )
    lineage_page.locator("#lineage-theme-toggle").click()
    dark_style = summary_chips.first.evaluate(
        "node => [getComputedStyle(node).borderColor, getComputedStyle(node).backgroundColor]"
    )
    assert light_style != dark_style
    assert "relationship-role--" not in summary_chips.first.get_attribute("class")

    lineage_page.locator("#lineage-clear-route").click()
    role_filter = lineage_page.locator("#lineage-role-filter")
    role_filter.select_option("empty")
    lineage_page.locator('[data-dataset-id="ds-empty"]').click()
    inspector_text = inspector.inner_text()
    assert "Schema reference\nReported empty object" in inspector_text
    assert "Backfill summary\nReported empty object" in inspector_text

    lineage_page.locator("#lineage-clear-route").click()
    role_filter = lineage_page.locator("#lineage-role-filter")
    role_filter.select_option("missing")
    lineage_page.locator('[data-dataset-id="ds-empty-object"]').click()
    assert "Reported connection metadata object has no recognized fields" in inspector.inner_text()


def test_sibling_filter_keeps_input_mounted_during_composition(lineage_page, tmp_path):
    path = _render_to(tmp_path, "cja_lineage_shared.json", "sibling-ime.html")
    lineage_page.goto(path.as_uri())
    lineage_page.fill("#lineage-search", "production")
    lineage_page.locator("#lineage-results button").first.click()
    lineage_page.evaluate(
        "window.__siblingFilterBefore = document.querySelector('#lineage-sibling-filter')"
    )
    lineage_page.dispatch_event("#lineage-sibling-filter", "compositionstart")
    lineage_page.locator("#lineage-sibling-filter").evaluate(
        """
        node => {
          node.value = 'exploration';
          node.dispatchEvent(new InputEvent('input', {
            bubbles: true,
            data: 'exploration',
            inputType: 'insertCompositionText',
            isComposing: true,
          }));
        }
        """
    )
    assert lineage_page.evaluate(
        "window.__siblingFilterBefore === document.querySelector('#lineage-sibling-filter')"
    )
    lineage_page.dispatch_event("#lineage-sibling-filter", "compositionend")
    assert "Exploration" in lineage_page.locator("#lineage-sibling-results").inner_text()


def test_degraded_states_are_distinct(lineage_page, tmp_path):
    path = _render_to(tmp_path, "cja_lineage_degraded.json", "degraded.html")
    lineage_page.goto(path.as_uri())
    lineage_page.fill("#lineage-search", "known")
    lineage_page.locator("#lineage-results button").first.click()
    assert "Connection name unavailable" in lineage_page.locator("#lineage-details").inner_text()
    assert "Backing datasets unavailable" in lineage_page.locator("#lineage-details").inner_text()

    lineage_page.fill("#lineage-search", "missing")
    lineage_page.locator("#lineage-results button").first.click()
    assert "Parent connection unavailable" in lineage_page.locator("#lineage-details").inner_text()

    reported_empty = {
        "dataViews": [
            {
                "id": "dv-empty",
                "name": "Reported empty",
                "connection": {"id": "conn-empty", "name": "Empty connection"},
                "datasets": [],
            }
        ],
        "count": 1,
    }
    empty_path = _render_source(tmp_path, reported_empty, "reported-empty.html")
    lineage_page.goto(empty_path.as_uri())
    lineage_page.fill("#lineage-search", "reported")
    lineage_page.locator("#lineage-results button").first.click()
    details = lineage_page.locator("#lineage-details").inner_text()
    assert "No backing datasets were reported" in details
    assert "Backing datasets unavailable" not in details


def test_reduced_motion_keeps_static_route(lineage_page, tmp_path):
    path = _render_to(tmp_path, "cja_lineage_shared.json", "reduced.html")
    lineage_page.emulate_media(reduced_motion="reduce")
    lineage_page.goto(path.as_uri())
    lineage_page.fill("#lineage-search", "production")
    lineage_page.locator("#lineage-results button").first.click()
    lineage_page.locator("#lineage-datasets button").first.click()
    assert lineage_page.locator(".lineage-edge.is-route").count() == 2
    assert lineage_page.locator(".route-marker").count() == 0
    assert lineage_page.locator("#lineage-flow-pause").is_hidden()
    assert "Static route selected" in lineage_page.locator("#lineage-status").inner_text()
    lineage_page.emulate_media(reduced_motion="no-preference")
    lineage_page.locator(".route-marker").wait_for(state="attached")
    assert lineage_page.locator(".route-marker").count() == 1
    assert lineage_page.locator("#lineage-flow-pause").is_visible()
    lineage_page.locator("#lineage-full-graph").click()
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().fullGraph") is True
    assert lineage_page.locator("#lineage-full-graph").get_attribute("aria-pressed") == "true"
    assert lineage_page.locator(".route-marker").count() == 0
    assert lineage_page.locator(".journey-guide").count() == 1
    assert lineage_page.locator(".journey-comet").count() == 4
    assert lineage_page.locator("#lineage-flow-pause").is_visible()
    lineage_page.locator("#lineage-clear-route").click()
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().fullGraph") is False
    assert lineage_page.locator("#lineage-full-graph").get_attribute("aria-pressed") == "false"
    assert lineage_page.locator("#lineage-route-controls").is_hidden()
    lineage_page.locator("#lineage-datasets button").first.click()
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().fullGraph") is False
    assert lineage_page.locator("#lineage-full-graph").get_attribute("aria-pressed") == "false"
    assert lineage_page.locator("#lineage-flow-pause").is_visible()
    assert lineage_page.locator(".route-marker").count() == 1
    lineage_page.locator("#lineage-full-graph").click()
    stage = lineage_page.locator("#lineage-stage")
    stage.scroll_into_view_if_needed()
    box = stage.bounding_box()
    assert box is not None
    lineage_page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    lineage_page.mouse.down()
    assert stage.evaluate("node => node.classList.contains('is-panning')") is True
    lineage_page.emulate_media(reduced_motion="reduce")
    lineage_page.wait_for_function(
        "window.__cjaLineagePoc.getState().fullGraph && document.querySelectorAll('.journey-comet').length === 0"
    )
    assert stage.evaluate("node => node.classList.contains('is-panning')") is False
    lineage_page.mouse.up()
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().fullGraph") is True
    assert lineage_page.locator("#lineage-full-graph").get_attribute("aria-pressed") == "true"
    assert lineage_page.locator(".route-marker").count() == 0
    assert lineage_page.locator(".journey-guide").count() == 1
    assert lineage_page.locator(".journey-comet").count() == 0
    assert lineage_page.locator("#lineage-flow-pause").is_hidden()
    assert "statically highlighted" in lineage_page.locator("#lineage-motion-copy").inner_text()
    lineage_page.emulate_media(reduced_motion="no-preference")
    lineage_page.locator(".journey-comet").first.wait_for(state="attached")
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().fullGraph") is True
    assert lineage_page.locator(".route-marker").count() == 0
    assert lineage_page.locator(".journey-comet").count() == 4
    assert lineage_page.locator("#lineage-flow-pause").is_visible()
    lineage_page.locator("#lineage-clear-route").click()
    lineage_page.locator("#lineage-datasets button").first.click()
    lineage_page.locator(".route-marker").wait_for(state="attached")
    assert lineage_page.locator("#lineage-flow-pause").is_visible()
    lineage_page.emulate_media(media="print", reduced_motion="no-preference")
    assert not lineage_page.locator(".route-marker").is_visible()
    assert lineage_page.locator(".lineage-edge.is-route").count() == 2
    lineage_page.emulate_media(media="screen", reduced_motion="no-preference")


def test_duplicate_results_preserve_selection_and_new_selection_clears_route(
    lineage_page, tmp_path
):
    source = {
        "dataViews": [
            {
                "id": "dv-one",
                "name": "Duplicate",
                "connection": {"id": "conn", "name": "Shared"},
                "datasets": [{"id": "ds", "name": "Dataset"}],
            },
            {
                "id": "dv-two",
                "name": "Duplicate",
                "connection": {"id": "conn", "name": "Shared"},
                "datasets": [{"id": "ds", "name": "Dataset"}],
            },
        ],
        "count": 2,
    }
    path = _render_source(tmp_path, source, "duplicates.html")
    lineage_page.goto(path.as_uri())
    lineage_page.fill("#lineage-search", "duplicate")
    results = lineage_page.locator("#lineage-results button")
    assert results.count() == 2
    assert "dv-one" in results.nth(0).inner_text()
    assert "dv-two" in results.nth(1).inner_text()
    results.nth(0).click()
    lineage_page.locator("#lineage-datasets button").first.click()
    lineage_page.locator("#lineage-flow-pause").click()

    lineage_page.fill("#lineage-search", "dv-two")
    state = lineage_page.evaluate("window.__cjaLineagePoc.getState()")
    assert state["selectedDataViewId"] == "dv-one"
    assert state["activeDatasetId"] == "ds"
    assert state["paused"] is True
    lineage_page.locator("#lineage-results button").first.click()
    state = lineage_page.evaluate("window.__cjaLineagePoc.getState()")
    assert state["selectedDataViewId"] == "dv-two"
    assert state["activeDatasetId"] is None
    assert state["paused"] is False


def test_unicode_search_is_shared_and_labels_preserve_code_points(lineage_page, tmp_path):
    long_dataset_name = "A" * 30 + "😀😀😀😀😀"
    source = {
        "dataViews": [
            {
                "id": "dv-strasse",
                "name": "Straße 🧪 Overview",
                "connection": {"id": "conn-unicode", "name": "Unicode connection"},
                "datasets": [{"id": "ds-emoji", "name": long_dataset_name}],
            },
            {
                "id": "dv-sibling",
                "name": "Sibling Straße 🔬",
                "connection": {"id": "conn-unicode", "name": "Unicode connection"},
                "datasets": [{"id": "ds-emoji", "name": long_dataset_name}],
            },
        ],
        "count": 2,
    }
    path = _render_source(tmp_path, source, "unicode-search.html")
    lineage_page.goto(path.as_uri())

    lineage_page.fill("#lineage-search", "STRASSE 🧪")
    result = lineage_page.locator("#lineage-results button").first
    assert "Straße 🧪 Overview" in result.inner_text()
    result.click()
    assert lineage_page.locator("#lineage-selection-heading").inner_text() == "Straße 🧪 Overview"

    lineage_page.fill("#lineage-sibling-filter", "STRASSE 🔬")
    sibling = lineage_page.locator("#lineage-siblings li").first
    assert sibling.inner_text().splitlines()[0] == "Sibling Straße 🔬"

    svg_label = lineage_page.locator(
        '[data-ref="dataset:ds-emoji"] .lineage-node-label'
    ).text_content()
    assert svg_label.endswith("…")
    assert len(svg_label) <= 24
    assert "�" not in svg_label
    node = lineage_page.locator('[data-ref="dataset:ds-emoji"]')
    assert long_dataset_name in node.get_attribute("aria-label")
    assert long_dataset_name in node.locator("title").text_content()
    assert (
        node.locator(".lineage-node-label")
        .get_attribute("clip-path")
        .startswith("url(#lineage-label-clip-")
    )


def test_high_fanout_local_svg_is_capped_and_full_graph_is_lazy(lineage_page, tmp_path):
    dataset_count = 120
    view_count = 180
    topology = LineageTopology(
        "Synthetic fanout",
        Coverage.ACCESSIBLE_SCOPE,
        tuple(LineageDataset(f"ds-{i:03d}", f"Dataset {i}", (0,)) for i in range(dataset_count)),
        (
            LineageConnection(
                "conn",
                "Shared",
                Availability.AVAILABLE,
                Availability.AVAILABLE,
                tuple(f"ds-{i:03d}" for i in range(dataset_count)),
                (0,),
            ),
        ),
        tuple(
            LineageDataView(
                f"dv-{i:03d}",
                f"View {i}",
                "conn",
                Availability.AVAILABLE,
                Availability.AVAILABLE,
                (i,),
            )
            for i in range(view_count)
        ),
        tuple(DatasetConnection(f"ds-{i:03d}", "conn", (0,)) for i in range(dataset_count)),
        tuple(ConnectionDataView("conn", f"dv-{i:03d}", (i,)) for i in range(view_count)),
    )
    path = tmp_path / "fanout.html"
    path.write_text(render(topology), encoding="utf-8")
    lineage_page.goto(path.as_uri())
    assert lineage_page.locator("svg").count() == 0
    lineage_page.locator('[data-connection-id="conn"]').click()
    inspector = lineage_page.locator("#lineage-connection-inspector")
    assert inspector.locator("[data-data-view-id]").count() == 100
    assert "showing 100" in inspector.inner_text()
    inspector.locator(".load-more").click()
    assert inspector.locator("[data-data-view-id]").count() == view_count
    lineage_page.keyboard.press("Escape")
    lineage_page.fill("#lineage-search", "View")
    assert lineage_page.locator("#lineage-results [data-data-view-id]").count() == 100
    lineage_page.locator("#lineage-results .load-more").click()
    assert lineage_page.locator("#lineage-results [data-data-view-id]").count() == view_count
    lineage_page.fill("#lineage-search", "dv-179")
    lineage_page.locator("#lineage-results button").first.click()
    state = lineage_page.evaluate("window.__cjaLineagePoc.getState()")
    assert state["svgNodeCount"] <= 100
    assert state["svgEdgeCount"] <= 100
    assert lineage_page.locator('[data-ref="data-view:dv-179"]').count() == 1
    assert lineage_page.locator("#lineage-datasets [data-dataset-id]").count() == 100
    assert (
        "120 backing datasets; showing 100"
        in lineage_page.locator("#lineage-datasets").inner_text()
    )
    dataset_more = lineage_page.locator("#lineage-datasets .load-more")
    assert dataset_more.get_attribute("aria-label") == "Show next 20 of 120 backing datasets"
    dataset_more.click()
    assert lineage_page.locator("#lineage-datasets [data-dataset-id]").count() == dataset_count
    assert lineage_page.locator("#lineage-siblings li").count() == 100
    lineage_page.fill("#lineage-sibling-filter", "View 178")
    assert lineage_page.locator("#lineage-siblings li").count() == 1
    assert "dv-178" in lineage_page.locator("#lineage-siblings li").first.inner_text()
    lineage_page.set_viewport_size({"width": 390, "height": 844})
    lineage_page.locator("#lineage-datasets button").last.click()
    state = lineage_page.evaluate("window.__cjaLineagePoc.getState()")
    assert state["svgNodeCount"] <= 100
    assert state["svgEdgeCount"] <= 100
    assert lineage_page.locator('[data-ref="dataset:ds-119"]').count() == 1
    assert lineage_page.locator(".lineage-edge.is-route").count() == 2
    assert lineage_page.locator("#lineage-datasets [data-dataset-id]").count() == dataset_count
    assert lineage_page.locator('[data-dataset-id="ds-119"]').count() == 1
    assert (
        lineage_page.locator('[data-dataset-id="ds-119"]').get_attribute("aria-pressed") == "true"
    )
    selected_center = lineage_page.evaluate(
        """
        () => {
          const payload = JSON.parse(document.querySelector('#sdr-lineage-data').textContent);
          const node = payload.geometry.local_by_connection[0].nodes.find(
            item => item.ref === 'dataset:ds-119'
          );
          return node.x + node.width / 2;
        }
        """
    )
    camera = lineage_page.evaluate("window.__cjaLineagePoc.getState().camera")
    assert abs(camera["x"] + camera["width"] / 2 - selected_center) < 120
    lineage_page.locator("#lineage-clear-route").click()
    assert lineage_page.evaluate("document.activeElement.dataset.datasetId") == "ds-119"
    assert lineage_page.locator("#lineage-datasets [data-dataset-id]").count() == dataset_count
    lineage_page.locator('[data-dataset-id="ds-119"]').click()
    lineage_page.set_viewport_size({"width": 1280, "height": 900})
    lineage_page.locator("#lineage-full-graph").click()
    state = lineage_page.evaluate("window.__cjaLineagePoc.getState()")
    assert state["fullGraph"] is True
    assert state["svgNodeCount"] == dataset_count + view_count + 1
    assert state["journeyCount"] == 1
    assert state["cometCount"] == 4
    assert state["ambientJourneyComparisons"] <= dataset_count + view_count
    assert lineage_page.locator(".lineage-column-band").count() == 3
    assert lineage_page.locator(".lineage-edge").evaluate_all(
        "nodes => nodes.some(node => node.getAttribute('d').includes('Q'))"
    )
    assert (
        lineage_page.locator(".lineage-edge")
        .first.get_attribute("marker-end")
        .startswith("url(#lineage-arrow-")
    )
    assert lineage_page.locator(".lineage-node-shape").first.get_attribute("rx") in {
        "12",
        "18",
    }
    dataset_stroke = lineage_page.locator(
        ".lineage-node--dataset .lineage-node-shape"
    ).first.evaluate("node => getComputedStyle(node).stroke")
    view_stroke = lineage_page.locator(
        ".lineage-node--data-view .lineage-node-shape"
    ).first.evaluate("node => getComputedStyle(node).stroke")
    assert dataset_stroke != view_stroke
    assert lineage_page.locator("#lineage-camera-controls").is_visible()
    assert lineage_page.locator("#lineage-stage-key").is_visible()
    assert lineage_page.locator("#lineage-flow-pause").is_visible()
    spacing = lineage_page.evaluate(
        """
        () => {
          const key = document.querySelector('#lineage-stage-key').getBoundingClientRect();
          const stage = document.querySelector('#lineage-stage').getBoundingClientRect();
          const toolbar = document.querySelector('#lineage-stage-toolbar').getBoundingClientRect();
          return {
            above: stage.top - key.bottom,
            below: toolbar.top - stage.bottom,
            keyOverCanvas: document.querySelector('#lineage-stage').contains(document.querySelector('#lineage-stage-key')),
            controlsOverCanvas: document.querySelector('#lineage-stage').contains(document.querySelector('#lineage-stage-toolbar')),
          };
        }
        """
    )
    assert spacing["above"] >= 8
    assert spacing["below"] >= 8
    assert spacing["keyOverCanvas"] is False
    assert spacing["controlsOverCanvas"] is False
    canvas_height = lineage_page.evaluate(
        "JSON.parse(document.querySelector('#sdr-lineage-data').textContent).geometry.global.height"
    )
    assert state["camera"]["height"] < canvas_height / 2
    rendered_font_size = lineage_page.locator(".lineage-node-label").first.evaluate(
        "node => parseFloat(getComputedStyle(node).fontSize) * node.getScreenCTM().a"
    )
    assert rendered_font_size >= 12
    initial_width = state["camera"]["width"]
    lineage_page.locator("#lineage-zoom-in").click()
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().camera.width") < initial_width
    lineage_page.locator("#lineage-reset-camera").click()
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().camera.width") == pytest.approx(
        initial_width
    )
    lineage_page.locator("#lineage-stage").focus()
    initial_y = lineage_page.evaluate("window.__cjaLineagePoc.getState().camera.y")
    lineage_page.keyboard.press("ArrowDown")
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().camera.y") > initial_y
    lineage_page.keyboard.press("0")
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().camera.y") == pytest.approx(
        initial_y
    )
    lineage_page.locator("#lineage-flow-pause").click()
    assert lineage_page.locator("#lineage-flow-pause").get_attribute("aria-pressed") == "true"
    assert lineage_page.evaluate("window.__cjaLineagePoc.getState().flowPaused") is True
    lineage_page.set_viewport_size({"width": 800, "height": 900})
    assert (
        lineage_page.evaluate(
            "getComputedStyle(document.querySelector('.detail-grid')).gridTemplateColumns.split(' ').length"
        )
        == 1
    )


def test_over_gate_local_graph_compacts_late_selection(lineage_page, tmp_path):
    dataset_count = 4_001
    view_count = 4_001
    topology = LineageTopology(
        "Over edge gate",
        Coverage.ACCESSIBLE_SCOPE,
        tuple(LineageDataset(f"ds-{i:04d}", f"Dataset {i}", (0,)) for i in range(dataset_count)),
        (
            LineageConnection(
                "conn",
                "Shared",
                Availability.AVAILABLE,
                Availability.AVAILABLE,
                tuple(f"ds-{i:04d}" for i in range(dataset_count)),
                (0,),
            ),
        ),
        tuple(
            LineageDataView(
                f"dv-{i:04d}",
                f"View {i}",
                "conn",
                Availability.AVAILABLE,
                Availability.AVAILABLE,
                (i,),
            )
            for i in range(view_count)
        ),
        tuple(DatasetConnection(f"ds-{i:04d}", "conn", (0,)) for i in range(dataset_count)),
        tuple(ConnectionDataView("conn", f"dv-{i:04d}", (i,)) for i in range(view_count)),
    )
    path = tmp_path / "over-edge-gate.html"
    path.write_text(render(topology), encoding="utf-8")
    lineage_page.goto(path.as_uri())
    assert lineage_page.locator("#lineage-stage svg").count() == 0
    assert lineage_page.locator("#lineage-stage").get_attribute("data-full-graph-gated") == "true"

    lineage_page.fill("#lineage-search", "dv-4000")
    lineage_page.locator("#lineage-results button").first.click()

    state = lineage_page.evaluate("window.__cjaLineagePoc.getState()")
    assert state["svgNodeCount"] == 100
    assert state["svgEdgeCount"] <= 100
    assert (
        lineage_page.locator('[data-ref="data-view:dv-4000"]').get_attribute("transform")
        == "translate(1000 72)"
    )
    view_box = lineage_page.locator("#lineage-stage svg").get_attribute("viewBox")
    assert float(view_box.split()[-1]) < 10_000
    assert lineage_page.locator("#lineage-stage .lineage-node").count() == 100


@pytest.mark.parametrize("color_pack", COLOR_PACK_CODES)
def test_lineage_role_text_contrast_in_both_themes(lineage_page, tmp_path, color_pack):
    source = json.loads((FIXTURES / "cja_lineage_enriched.json").read_text())
    path = tmp_path / "contrast.html"
    path.write_text(render(adapt(source, scope_label="Synthetic"), color_pack=color_pack))
    lineage_page.goto(path.as_uri())
    lineage_page.locator(".connection-overview-card").first.click()
    for theme in ("light", "dark"):
        if lineage_page.locator("html").get_attribute("data-theme") != theme:
            lineage_page.locator("#lineage-theme-toggle").click()
        failures = lineage_page.evaluate("""() => {
          const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
          const ctx = canvas.getContext('2d', {willReadFrequently:true});
          const pixel = () => Array.from(ctx.getImageData(0,0,1,1).data).slice(0,3);
          const luminance = rgb => rgb.map(n => {const c=n/255; return c<=.04045 ? c/12.92 : ((c+.055)/1.055)**2.4;}).reduce((sum,n,i)=>sum+n*[.2126,.7152,.0722][i],0);
          return Array.from(document.querySelectorAll('.connection-overview-role, .global-role-filter:not(:disabled), .connection-overview-selected')).flatMap(el => {
            ctx.fillStyle='#fff'; ctx.fillRect(0,0,1,1);
            const ancestors=[]; for(let n=el;n;n=n.parentElement) ancestors.push(n);
            for(const n of ancestors.reverse()) {ctx.fillStyle=getComputedStyle(n).backgroundColor;ctx.fillRect(0,0,1,1);}
            const bg=luminance(pixel());
            ctx.fillStyle=getComputedStyle(el).color;ctx.fillRect(0,0,1,1);
            const fg=luminance(pixel()); const ratio=(Math.max(fg,bg)+.05)/(Math.min(fg,bg)+.05);
            return ratio>=4.5 ? [] : [{text:el.textContent,ratio}];
          });
        }""")
        assert failures == [], (color_pack, theme, failures)


def test_initial_dark_theme_and_reported_empty_connection(lineage_page, tmp_path):
    source = {
        "dataViews": [
            {
                "id": "dv-empty",
                "name": "Empty",
                "connection": {"id": "conn-empty", "name": "Empty connection"},
                "datasets": [],
            }
        ],
        "count": 1,
    }
    path = _render_source(tmp_path, source, "reported-empty.html")
    lineage_page.emulate_media(color_scheme="dark")
    try:
        lineage_page.goto(path.as_uri())
        assert lineage_page.locator("#lineage-theme-toggle").get_attribute("aria-pressed") == "true"
        assert lineage_page.locator("#lineage-theme-toggle").inner_text() == "Light mode"
        card = lineage_page.locator(".connection-overview-card")
        assert "No backing datasets reported" in card.inner_text()
        card.click()
        assert (
            "No backing datasets reported"
            in lineage_page.locator("#lineage-connection-inspector").inner_text()
        )
    finally:
        lineage_page.emulate_media(color_scheme="light")
