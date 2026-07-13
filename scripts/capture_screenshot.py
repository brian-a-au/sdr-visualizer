"""Capture the README's catalog-view screenshot from the CJA example.

Renders the bundled messy CJA fixture through the real pipeline, opens it
in headless Chromium at a fixed viewport, and screenshots the top of the
catalog view. Deterministic input, pinned viewport — rerunning refreshes
the image only when the product visibly changed.

Run via:

    uv run python scripts/capture_screenshot.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sdr_visualizer.core.visualizer import visualize  # noqa: E402

OUTPUT = REPO / "docs" / "screenshot-catalog.png"
VIEWPORT = {"width": 1440, "height": 900}


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "playwright not installed; run: uv sync --group browser && "
            "uv run playwright install chromium",
            file=sys.stderr,
        )
        return 2

    fixture = REPO / "tests" / "fixtures" / "cja_snapshot_messy.json"
    snapshot = json.loads(fixture.read_text(encoding="utf-8"))
    html = visualize(snapshot, source=str(fixture))

    with tempfile.TemporaryDirectory() as tmp:
        page_path = Path(tmp) / "report.html"
        page_path.write_text(html, encoding="utf-8")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport=VIEWPORT)
            page.goto(page_path.as_uri())
            page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
            OUTPUT.parent.mkdir(exist_ok=True)
            page.screenshot(path=str(OUTPUT))
            browser.close()
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
