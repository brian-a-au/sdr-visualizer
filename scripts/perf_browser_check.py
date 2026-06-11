"""Browser-side performance gate (SPEC-VISUALIZER §6).

Measures the budgets Python can't: initial render time and filter/search
latency, in real Chromium via Playwright. Asserts the §6 2,000-component
row (render < 2s, filter < 300ms) for every available large fixture —
conservative against CI noise while still catching order-of-magnitude
regressions.

Setup + run:

    uv sync --group browser
    uv run playwright install chromium
    uv run python scripts/perf_browser_check.py

The XL fixture is optional; generate it with
`generate_large_fixture.py --scale 1.67 --output tests/fixtures/cja_snapshot_xl.json`.
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = [
    REPO / "tests" / "fixtures" / "cja_snapshot_large.json",
    REPO / "tests" / "fixtures" / "cja_snapshot_xl.json",
]

RENDER_BUDGET_MS = 2000.0
FILTER_BUDGET_MS = 300.0
# Matches the synthetic fixtures' "Dimension 00xx" names (~99 rows) via the lowercased search blob.
FILTER_QUERY = "dimension 00"
FILTER_RUNS = 5


def _check(page, html_path: Path, label: str) -> list[str]:
    start = time.perf_counter()
    page.goto(html_path.as_uri())
    page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    render_ms = (time.perf_counter() - start) * 1000.0

    if not page.evaluate("typeof window.__sdrPerf !== 'undefined'"):
        return [f"[{label}] __sdrPerf missing - client JS failed to initialize"]

    samples = [
        page.evaluate(f"window.__sdrPerf.timeFilter({json.dumps(FILTER_QUERY)})")
        for _ in range(FILTER_RUNS)
    ]
    filter_ms = statistics.median(samples)

    print(f"[{label}] initial render: {render_ms:.0f}ms  (budget {RENDER_BUDGET_MS:.0f}ms)")
    print(
        f"[{label}] filter latency: {filter_ms:.1f}ms "
        f"(budget {FILTER_BUDGET_MS:.0f}ms, median of {FILTER_RUNS})"
    )
    failures = []
    if render_ms > RENDER_BUDGET_MS:
        failures.append(f"[{label}] initial render {render_ms:.0f}ms > {RENDER_BUDGET_MS:.0f}ms")
    if filter_ms > FILTER_BUDGET_MS:
        failures.append(f"[{label}] filter latency {filter_ms:.1f}ms > {FILTER_BUDGET_MS:.0f}ms")
    return failures


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "playwright not installed; run `uv sync --group browser` "
            "and `uv run playwright install chromium`",
            file=sys.stderr,
        )
        return 2

    from sdr_visualizer.adapters.cja import adapt
    from sdr_visualizer.render.renderer import render

    failures: list[str] = []
    checked = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        with tempfile.TemporaryDirectory() as tmp:
            for fixture in FIXTURES:
                if not fixture.exists():
                    print(f"note: {fixture.name} not generated; skipping")
                    continue
                snap = json.loads(fixture.read_text(encoding="utf-8"))
                html_path = Path(tmp) / f"{fixture.stem}.html"
                html_path.write_text(render(adapt(snap)), encoding="utf-8")
                failures += _check(page, html_path, fixture.stem)
                checked += 1
        browser.close()

    if checked == 0:
        print("no fixtures available; run tests once to materialize them", file=sys.stderr)
        return 2
    if failures:
        for msg in failures:
            print(f"FAIL: {msg}", file=sys.stderr)
        return 1
    print("OK: browser budgets met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
