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

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")

from sdr_visualizer.adapters.cja import adapt as cja_adapt  # noqa: E402
from sdr_visualizer.render.renderer import render  # noqa: E402

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
    out = _render_to(tmp_path, "cja_snapshot_messy.json", "state.html")
    browser_page.goto(out.as_uri() + "#q=evil&types=metric&desc=missing&sort=name&dir=desc")
    browser_page.wait_for_selector("#search-input", state="attached", timeout=10_000)
    assert browser_page.evaluate("document.getElementById('search-input').value") == "evil"
    checked = browser_page.evaluate(
        "Array.from(document.querySelectorAll('#type-filter input:checked')).map(i => i.value)"
    )
    assert checked == ["metric"]
    assert browser_page.evaluate("document.getElementById('description-filter').value") == "missing"
    assert browser_page.evaluate("document.querySelector('th.is-sorted').getAttribute('data-sort')") == "name"
    assert "dir=desc" in browser_page.evaluate("location.hash")


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
    out = _render_to(tmp_path, "cja_snapshot_messy.json", "detail.html")
    # Navigate directly with a known fixture id encoded in the hash so the
    # deferred restore runs on initial load (not a fragment-only navigation).
    known_id = "metrics%2Fcm_metric_001"
    browser_page.goto(out.as_uri() + "#detail=" + known_id)
    browser_page.wait_for_selector("#detail-panel.is-open", state="attached", timeout=10_000)
    assert "detail=" in browser_page.evaluate("location.hash")


def test_url_hash_ignores_bogus_params(browser_page, tmp_path):
    out = _render_to(tmp_path, "cja_snapshot_messy.json", "bogus.html")
    browser_page.goto(out.as_uri() + "#types=bogus&sort=__proto__&detail=nope")
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


def test_small_graph_uses_radial_layout(browser_page, tmp_path):
    out = tmp_path / "tiny.html"
    out.write_text(render(cja_adapt(_tiny_snapshot())), encoding="utf-8")
    browser_page.goto(out.as_uri())
    browser_page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    browser_page.click('[data-view="graph"]')
    browser_page.wait_for_selector(".graph-node", state="attached", timeout=10_000)
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
