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
    browser_page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    browser_page.goto(out.as_uri())
    browser_page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)

    for flag in ["__xssEscape", "__xssFired", "__xssOwner", "__xssSeg", "__xssCrit"]:
        assert browser_page.evaluate(f"window.{flag}") is None, f"{flag} executed"
    assert dialogs == []
    # The hostile strings render as visible text, not as elements.
    assert browser_page.evaluate("document.querySelectorAll('img[src=x]').length") == 0
    body_text = browser_page.evaluate("document.body.innerText")
    assert "window.__xssEscape=true" in body_text  # description shown as text
