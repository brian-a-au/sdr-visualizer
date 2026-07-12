"""Browser-level functional tests (Playwright + headless Chromium).

These verify behavior pytest can't see from the Python side: script
injection actually not executing, URL state restoring, and the radial
layout positioning nodes. Skipped automatically when playwright isn't
installed (`uv sync --group browser` + `uv run playwright install chromium`).
CI runs them in the browser-perf job.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")

from sdr_visualizer.adapters.cja import adapt as cja_adapt  # noqa: E402
from sdr_visualizer.analysis.diff import diff_implementations  # noqa: E402
from sdr_visualizer.analysis.trend import build_trend  # noqa: E402
from sdr_visualizer.render.renderer import (  # noqa: E402
    build_payload_with_options,
    render,
    render_payload,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def browser_page():
    with playwright_sync.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        yield page
        browser.close()


def _render_to(tmp_path: Path, fixture_name: str, name: str = "out.html") -> Path:
    snap = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    out = tmp_path / name
    out.write_text(render(cja_adapt(snap)), encoding="utf-8")
    return out


def test_hostile_snapshot_does_not_execute(browser_page, tmp_path):
    """XSS probes in snapshot text must render as text, never execute."""
    out = _render_to(tmp_path, "cja_snapshot_hostile.json")
    dialogs = []

    def _dialog_handler(d):
        dialogs.append(d.message)
        d.dismiss()

    # browser_page is module-scoped — detach the listener so it can't leak
    # into (and silently auto-dismiss dialogs for) later tests.
    browser_page.on("dialog", _dialog_handler)
    try:
        browser_page.goto(out.as_uri())
        browser_page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)

        for flag in ["__xssEscape", "__xssFired", "__xssOwner", "__xssSeg", "__xssCrit"]:
            assert browser_page.evaluate(f"window.{flag}") is None, f"{flag} executed"
        assert dialogs == []
    finally:
        browser_page.remove_listener("dialog", _dialog_handler)
    # The hostile strings render as visible text, not as elements.
    assert browser_page.evaluate("document.querySelectorAll('img[src=x]').length") == 0
    body_text = browser_page.evaluate("document.body.innerText")
    assert "window.__xssEscape=true" in body_text  # description shown as text


def test_url_hash_restores_catalog_state(browser_page, tmp_path):
    # q=metric matches "Metric 001"..".Metric 038" (all have missing descriptions).
    # types=metric + desc=missing + sort=name + dir=desc exercises all restore paths
    # and yields 38 rows (empirically verified against cja_snapshot_messy.json).
    out = _render_to(tmp_path, "cja_snapshot_messy.json", "state.html")
    browser_page.goto(out.as_uri() + "#q=metric&types=metric&desc=missing&sort=name&dir=desc")
    browser_page.wait_for_selector("#search-input", state="attached", timeout=10_000)
    assert browser_page.evaluate("document.getElementById('search-input').value") == "metric"
    checked = browser_page.evaluate(
        "Array.from(document.querySelectorAll('#type-filter input:checked')).map(i => i.value)"
    )
    assert checked == ["metric"]
    assert browser_page.evaluate("document.getElementById('description-filter').value") == "missing"
    assert (
        browser_page.evaluate("document.querySelector('th.is-sorted').getAttribute('data-sort')")
        == "name"
    )
    assert "dir=desc" in browser_page.evaluate("location.hash")
    assert browser_page.evaluate("window.__sdrPerf.rowCount()") > 0


def test_url_hash_written_on_filter_change(browser_page, tmp_path):
    out = _render_to(tmp_path, "cja_snapshot_messy.json", "write.html")
    browser_page.goto(out.as_uri())
    browser_page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    browser_page.fill("#search-input", "revenue")
    browser_page.wait_for_timeout(300)  # debounce (120ms) + slack
    assert "q=revenue" in browser_page.evaluate("location.hash")
    browser_page.fill("#search-input", "")
    browser_page.wait_for_timeout(300)
    assert "q=" not in browser_page.evaluate("location.hash")


def test_url_hash_restores_open_detail(browser_page, tmp_path):
    snap = json.loads((FIXTURES / "cja_snapshot_messy.json").read_text(encoding="utf-8"))
    known_id = snap["metrics"][0]["id"]
    out = _render_to(tmp_path, "cja_snapshot_messy.json", "detail.html")
    # Navigate directly with a known fixture id encoded in the hash so the
    # deferred restore runs on initial load (not a fragment-only navigation).
    browser_page.goto(out.as_uri() + "#detail=" + quote(known_id, safe=""))
    browser_page.wait_for_selector("#detail-panel.is-open", state="attached", timeout=10_000)
    assert "detail=" in browser_page.evaluate("location.hash")
    assert known_id in browser_page.evaluate("document.getElementById('detail-body').innerText")


def test_url_hash_ignores_bogus_params(browser_page, tmp_path):
    out = _render_to(tmp_path, "cja_snapshot_messy.json", "bogus.html")
    browser_page.goto(out.as_uri() + "#types=bogus&sort=__proto__&detail=nope&mod=bogus&desc=nope")
    browser_page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    # Unknown type tokens are ignored — all boxes stay checked, rows render.
    checked = browser_page.evaluate(
        "document.querySelectorAll('#type-filter input:checked').length"
    )
    assert checked == 5
    # Bogus sort key rejected — default type sort indicator remains.
    assert (
        browser_page.evaluate("document.querySelector('th.is-sorted').getAttribute('data-sort')")
        == "type"
    )
    # Unknown detail id — panel stays closed.
    assert browser_page.evaluate("document.querySelector('#detail-panel.is-open')") is None
    # Invalid select params ignored — catalog still renders rows.
    assert browser_page.evaluate("window.__sdrPerf.rowCount()") > 0
    assert browser_page.evaluate("document.getElementById('modified-filter').value") == "all"


def _tiny_snapshot() -> dict:
    """8 components with edges — under the 20-node radial threshold."""
    return {
        "metadata": {
            "Data View ID": "dv_tiny",
            "Data View Name": "Tiny",
            "Generation Timestamp": "2026-06-01 00:00:00",
            "Tool Version": "3.5.17",
        },
        "data_view": {"id": "dv_tiny"},
        "metrics": [
            {"id": f"metrics/m{i}", "name": f"Metric {i}", "description": "d", "type": "integer"}
            for i in range(1, 4)
        ],
        "dimensions": [
            {"id": f"variables/evar{i}", "name": f"Dim {i}", "description": "d", "type": "string"}
            for i in range(1, 4)
        ],
        "segments": {
            "segments": [
                {
                    "segment_id": "segments/s1",
                    "segment_name": "Seg 1",
                    "description": "d",
                    "container_type": "event",
                    "nesting_depth": 1,
                    "definition_json": "{}",
                    "dimension_references": ["variables/evar1"],
                    "metric_references": ["metrics/m1"],
                    "other_segment_references": [],
                }
            ]
        },
        "calculated_metrics": {
            "metrics": [
                {
                    "metric_id": "calculatedMetrics/c1",
                    "metric_name": "Calc 1",
                    "description": "d",
                    "formula_summary": "m1 / m2",
                    "definition_json": "{}",
                    "metric_references": ["metrics/m1", "metrics/m2"],
                    "segment_references": [],
                    "complexity_score": 1.0,
                }
            ]
        },
    }


def _open_tiny_graph(browser_page, tmp_path, name: str):
    out = tmp_path / name
    out.write_text(render(cja_adapt(_tiny_snapshot())), encoding="utf-8")
    browser_page.goto(out.as_uri())
    browser_page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    browser_page.click('[data-view="graph"]')
    browser_page.wait_for_selector(".graph-node", state="attached", timeout=10_000)


def _hover_node(browser_page, label: str):
    """Dispatch mouseover on the graph node with the given label and wait
    for the (rAF-coalesced) hover paint to land."""
    found = browser_page.evaluate(
        """(label) => {
          for (const n of document.querySelectorAll('#graph-canvas g.graph-node')) {
            if (n.textContent === label) {
              n.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
              return true;
            }
          }
          return false;
        }""",
        label,
    )
    assert found, f"no graph node labeled {label!r} to hover"
    browser_page.wait_for_selector(".graph-node.is-hover", state="attached", timeout=2_000)


def _node_labels(browser_page, css_class: str) -> list[str]:
    """Sorted labels of the graph nodes carrying the given class."""
    return browser_page.evaluate(
        f"""Array.from(document.querySelectorAll('#graph-canvas g.graph-node.{css_class}'))
             .map(n => n.textContent).sort()"""
    )


def test_graph_hover_highlights_neighbors(browser_page, tmp_path):
    """Hovering a node fades non-neighbors; mouseout restores the filter state.

    Paint is coalesced to animation frames, so assertions wait for the class
    to appear rather than checking synchronously after the event.
    """
    _open_tiny_graph(browser_page, tmp_path, "hover.html")
    # Metric 1 is referenced by both Seg 1 and Calc 1 — its only neighbors.
    _hover_node(browser_page, "Metric 1")
    unfaded = browser_page.evaluate(
        """Array.from(document.querySelectorAll('#graph-canvas g.graph-node'))
             .filter(n => !n.classList.contains('is-faded'))
             .map(n => n.textContent).sort()"""
    )
    assert unfaded == ["Calc 1", "Metric 1", "Seg 1"]
    # Hovered node's edges highlight; unrelated edges fade.
    assert (
        browser_page.evaluate(
            "document.querySelectorAll('#graph-canvas line.is-highlighted').length"
        )
        == 2
    )
    browser_page.evaluate(
        """document.querySelector('.graph-node.is-hover')
             .dispatchEvent(new MouseEvent('mouseout', {bubbles: true}))"""
    )
    browser_page.wait_for_selector(".graph-node.is-hover", state="detached", timeout=2_000)
    # Back to the default filter view: connected-only fades the 3 orphans.
    assert _node_labels(browser_page, "is-faded") == ["Dim 2", "Dim 3", "Metric 3"]


def test_graph_search_highlights_matches(browser_page, tmp_path):
    """The graph search (debounced) highlights matches and fades the rest."""
    _open_tiny_graph(browser_page, tmp_path, "graphsearch.html")
    browser_page.fill("#graph-search", "metric 1")
    browser_page.wait_for_selector(".graph-node.is-highlighted", state="attached", timeout=2_000)
    assert _node_labels(browser_page, "is-highlighted") == ["Metric 1"]
    # Non-matching connected nodes fade alongside the orphans.
    assert (
        browser_page.evaluate(
            """document.querySelectorAll('#graph-canvas g.graph-node.is-faded').length"""
        )
        == 7
    )


def test_graph_filter_change_cancels_hover(browser_page, tmp_path):
    """A filter/search change cancels an active hover and repaints on the
    next frame; search-match highlights then persist through later hovers."""
    _open_tiny_graph(browser_page, tmp_path, "hovercancel.html")
    _hover_node(browser_page, "Metric 1")
    # The debounced search lands while the hover is active — it must win:
    # hover cleared, matches highlighted, without waiting for a mouseout.
    browser_page.fill("#graph-search", "dim")
    browser_page.wait_for_selector(".graph-node.is-highlighted", state="attached", timeout=2_000)
    assert browser_page.evaluate("document.querySelector('.graph-node.is-hover')") is None
    # Dim 2/3 match but are orphans (connected-only default).
    assert _node_labels(browser_page, "is-highlighted") == ["Dim 1"]
    # Hovering another node keeps the search-match highlight visible.
    _hover_node(browser_page, "Seg 1")
    assert _node_labels(browser_page, "is-highlighted") == ["Dim 1"]


def test_small_graph_uses_radial_layout(browser_page, tmp_path):
    _open_tiny_graph(browser_page, tmp_path, "tiny.html")
    positions = browser_page.evaluate(
        """Array.from(document.querySelectorAll('.graph-node')).map(g => {
             const m = /translate\\(([-\\d.]+),([-\\d.]+)\\)/.exec(g.getAttribute('transform'));
             return [parseFloat(m[1]), parseFloat(m[2])];
           })"""
    )
    assert len(positions) == 8
    cx = sum(p[0] for p in positions) / len(positions)
    cy = sum(p[1] for p in positions) / len(positions)
    radii = [((p[0] - cx) ** 2 + (p[1] - cy) ** 2) ** 0.5 for p in positions]
    # Radial layout: every node equidistant from the centroid (loose tolerance).
    assert max(radii) - min(radii) < 1.0, f"not a circle: {radii}"


def test_naive_space_timestamp_renders_date_prefix(browser_page, tmp_path):
    snapshot = {
        "metadata": {"Data View ID": "dv_dates", "Data View Name": "Dates"},
        "data_view": {"id": "dv_dates"},
        "metrics": [
            {
                "id": "metrics/m1",
                "name": "Metric One",
                "description": "d",
                "modified_at": "2026-01-15 18:00:00",
            }
        ],
        "dimensions": [],
    }
    out = tmp_path / "dates.html"
    out.write_text(render(cja_adapt(snapshot)), encoding="utf-8")
    # Reuse the module browser (a second sync_playwright() in one thread
    # conflicts) but a fresh context pinned to UTC-8: pre-fix, Chrome parses
    # the naive string as local time and getUTCDate() lands on Jan 16 — a day
    # off from modified_ts (UTC).
    context = browser_page.context.browser.new_context(timezone_id="America/Los_Angeles")
    try:
        page = context.new_page()
        page.goto(out.as_uri())
        page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
        cell = page.evaluate("document.querySelector('#catalog-body td.col-modified').innerText")
    finally:
        context.close()
    assert cell.strip() == "2026-01-15"


def test_url_hash_zero_types_round_trips(browser_page, tmp_path):
    out = _render_to(tmp_path, "cja_snapshot_messy.json", "zerotypes.html")
    # Writing side already emits "#...types=" when nothing is checked;
    # the restore side must honor it instead of showing everything.
    browser_page.goto(out.as_uri() + "#types=")
    browser_page.wait_for_selector("#search-input", state="attached", timeout=10_000)
    checked = browser_page.evaluate(
        "document.querySelectorAll('#type-filter input:checked').length"
    )
    assert checked == 0
    assert browser_page.evaluate("window.__sdrPerf.rowCount()") == 0


def _compare_pair():
    def snap(metrics):
        return {
            "metadata": {"Data View ID": "dv_cmp", "Data View Name": "Compare"},
            "data_view": {"id": "dv_cmp"},
            "metrics": metrics,
            "dimensions": [],
            "segments": {"segments": []},
            "calculated_metrics": {"metrics": []},
        }

    old = snap(
        [
            {"id": "metrics/m1", "name": "Metric One", "description": "d"},
            {"id": "metrics/m3", "name": "Metric Three", "description": "d"},
        ]
    )
    new = snap(
        [
            {"id": "metrics/m1", "name": "Metric One (renamed)", "description": "d"},
            {"id": "metrics/m2", "name": "Metric Two", "description": "d"},
        ]
    )
    return old, new


def _render_compare(tmp_path, name, old_snapshot, new_snapshot):
    old_impl = cja_adapt(old_snapshot)
    new_impl = cja_adapt(new_snapshot)
    payload = build_payload_with_options(new_impl)
    payload["changes"] = diff_implementations(old_impl, new_impl)
    payload["meta"]["compared_to"] = payload["changes"]["baseline"]
    out = tmp_path / name
    out.write_text(render_payload(payload), encoding="utf-8")
    return out


def test_changes_view_renders_counts_and_field_detail(browser_page, tmp_path):
    old, new = _compare_pair()
    out = _render_compare(tmp_path, "compare.html", old, new)
    browser_page.goto(out.as_uri())
    browser_page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    browser_page.click('.view-button[data-view="changes"]')
    summary = browser_page.inner_text("#changes-summary")
    assert "+1 added" in summary
    assert "(1 metric)" in summary  # per-type breakdown: 1 added metric
    assert "−1 removed" in summary
    assert "~1 modified" in summary
    rows = browser_page.evaluate("document.querySelectorAll('#changes-body .change-row').length")
    assert rows == 3
    browser_page.click("#changes-body details.change-modified summary")
    field_text = browser_page.inner_text("#changes-body .change-fields")
    assert "Metric One" in field_text
    assert "Metric One (renamed)" in field_text

    # Close the <details> again before exercising the ref-link inside its
    # <summary> — the link must open the detail panel without toggling the
    # enclosing <details> back open.
    browser_page.click("#changes-body details.change-modified summary")
    assert (
        browser_page.evaluate(
            "document.querySelector('#changes-body details.change-modified').open"
        )
        is False
    )
    browser_page.click("#changes-body details.change-modified summary button.ref-link")
    assert browser_page.inner_text("#detail-body .detail-name") == "Metric One (renamed)"
    assert (
        browser_page.evaluate(
            "document.querySelector('#changes-body details.change-modified').open"
        )
        is False
    )


def test_changes_added_entry_links_to_detail_panel(browser_page, tmp_path):
    old, new = _compare_pair()
    out = _render_compare(tmp_path, "compare_link.html", old, new)
    browser_page.goto(out.as_uri())
    browser_page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    browser_page.click('.view-button[data-view="changes"]')
    browser_page.click("#changes-body .change-added button.ref-link")
    name = browser_page.inner_text("#detail-body .detail-name")
    assert name == "Metric Two"


def test_changes_view_url_state_restores(browser_page, tmp_path):
    old, new = _compare_pair()
    out = _render_compare(tmp_path, "compare_url.html", old, new)
    browser_page.goto(out.as_uri() + "#view=changes")
    browser_page.wait_for_selector("#search-input", state="attached", timeout=10_000)
    hidden = browser_page.evaluate("document.getElementById('changes-view').hidden")
    assert hidden is False


def test_changes_empty_state(browser_page, tmp_path):
    old, _ = _compare_pair()
    out = _render_compare(tmp_path, "compare_empty.html", old, old)
    browser_page.goto(out.as_uri())
    browser_page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    browser_page.click('.view-button[data-view="changes"]')
    assert "No changes" in browser_page.inner_text("#changes-body")


def test_changes_search_filters_rows(browser_page, tmp_path):
    old, new = _compare_pair()
    out = _render_compare(tmp_path, "compare_search.html", old, new)
    browser_page.goto(out.as_uri())
    browser_page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    browser_page.click('.view-button[data-view="changes"]')
    browser_page.fill("#changes-search", "metric two")
    visible = browser_page.evaluate(
        "Array.from(document.querySelectorAll('#changes-body .change-row'))"
        ".filter(function (r) { return !r.hidden; }).length"
    )
    assert visible == 1


def _trend_series_snapshots():
    def snap(metrics):
        return {
            "metadata": {"Data View ID": "dv_trend", "Data View Name": "Trend"},
            "data_view": {"id": "dv_trend"},
            "metrics": metrics,
            "dimensions": [],
            "segments": {"segments": []},
            "calculated_metrics": {"metrics": []},
        }

    return [
        snap([{"id": "metrics/m1", "name": "One", "description": "d"}]),
        snap(
            [
                {"id": "metrics/m1", "name": "One", "description": "d"},
                {"id": "metrics/m2", "name": "Two", "description": "d"},
            ]
        ),
        snap([{"id": "metrics/m2", "name": "Two", "description": "d"}]),
    ]


def _render_trend(tmp_path, name):
    impls = [cja_adapt(s) for s in _trend_series_snapshots()]
    payload = build_payload_with_options(impls[-1])
    payload["trend"] = build_trend(impls, capped=False)
    out = tmp_path / name
    out.write_text(render_payload(payload), encoding="utf-8")
    return out


def test_trend_view_renders_charts_and_log(browser_page, tmp_path):
    out = _render_trend(tmp_path, "trend.html")
    browser_page.goto(out.as_uri())
    browser_page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    browser_page.click('.view-button[data-view="trend"]')
    charts = browser_page.evaluate("document.querySelectorAll('#trend-view svg.sparkline').length")
    assert charts >= 5
    rows = browser_page.evaluate(
        "document.querySelectorAll('#trend-log details.trend-interval').length"
    )
    assert rows == 2
    summary = browser_page.inner_text("#trend-log details.trend-interval >> nth=0")
    assert "+1" in summary


def test_trend_interval_expands_to_id_lists(browser_page, tmp_path):
    out = _render_trend(tmp_path, "trend_expand.html")
    browser_page.goto(out.as_uri())
    browser_page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    browser_page.click('.view-button[data-view="trend"]')
    browser_page.click("#trend-log details.trend-interval >> nth=1 >> summary")
    body = browser_page.inner_text("#trend-log details.trend-interval >> nth=1")
    assert "metrics/m1" in body  # removed in the second interval


def test_trend_view_url_state_restores(browser_page, tmp_path):
    out = _render_trend(tmp_path, "trend_url.html")
    browser_page.goto(out.as_uri() + "#view=trend")
    browser_page.wait_for_selector("#search-input", state="attached", timeout=10_000)
    assert browser_page.evaluate("document.getElementById('trend-view').hidden") is False


def test_trend_absent_without_flag(browser_page, tmp_path):
    out = _render_to(tmp_path, "cja_snapshot_messy.json", "notrend.html")
    browser_page.goto(out.as_uri())
    browser_page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    assert (
        browser_page.evaluate("document.querySelector('.view-button[data-view=\\'trend\\']')")
        is None
    )
