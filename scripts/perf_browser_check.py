"""Browser-side performance gate (SPEC-VISUALIZER §6).

Measures the budgets Python can't: initial render time, filter/search
latency, and the main-thread block when entering the graph view, in real
Chromium via Playwright. Asserts per tier: the bundled CJA (1,200) and AA
(~900) fixtures against the §6 1,000-component row (render < 1s, filter <
150ms), and the XL fixture against the 2,000-component row (render < 2s,
filter < 300ms), plus the graph-init block budget for every available
fixture. The CJA fixtures exceed the 1,000-node graph threshold, so their
graph timing takes the worst-case "Render anyway" path; the AA fixture sits
under it and must render without the gate.

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
# (path, adapter, render budget ms, filter budget ms, expect the
#  "Render anyway" opt-in — i.e. the fixture exceeds the 1,000-node
#  graph threshold). The 1,200/900-component fixtures are asserted
#  against the §6 1,000-component budgets (like the Python gate), the
#  XL fixture against the 2,000-component budgets.
FIXTURES = [
    (REPO / "tests" / "fixtures" / "cja_snapshot_large.json", "cja", 1000.0, 150.0, True),
    (REPO / "tests" / "fixtures" / "aa_snapshot_large.json", "aa", 1000.0, 150.0, False),
    (REPO / "tests" / "fixtures" / "cja_snapshot_xl.json", "cja", 2000.0, 300.0, True),
]

# Main-thread block when entering the graph view: DOM build + time-boxed
# warm-up (self-limits at ~150ms) + a forced style/layout flush of the
# inserted SVG subtree, so the budget covers the full freeze a user feels,
# not just script time. Both large fixtures exceed the 1,000-node threshold,
# so this times the opt-in "Render anyway" path — the worst case (the gate
# fails if that assumption ever stops holding). Generous against CI noise;
# the failure mode it guards (unbounded synchronous warm-up) measured
# 800ms+ at 2k nodes locally.
GRAPH_INIT_BUDGET_MS = 700.0
# Matches the synthetic fixtures' "Dimension 00xx" names (~99 rows) via the lowercased search blob.
FILTER_QUERY = "dimension 00"
FILTER_RUNS = 5


def _check(
    page,
    html_path: Path,
    label: str,
    render_budget_ms: float,
    filter_budget_ms: float,
    expect_opt_in: bool,
) -> list[str]:
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

    graph = page.evaluate(
        """() => {
          const t0 = performance.now();
          document.querySelector('.view-button[data-view="graph"]').click();
          // No null guard: the template always emits #graph-degraded, and a
          // missing element should throw here (the real cause) rather than
          // surface as a misleading wrong-path failure.
          const degraded = document.getElementById('graph-degraded');
          const optIn = !degraded.hidden;
          if (optIn) document.getElementById('graph-render-anyway').click();
          // Force style/layout of the freshly inserted SVG subtree — without
          // this the measurement stops at script time and misses the deferred
          // layout block (still excludes paint/raster).
          document.getElementById('graph-canvas').getBoundingClientRect();
          return {ms: performance.now() - t0, optIn};
        }"""
    )
    graph_init_ms = graph["ms"]
    nodes_drawn = page.evaluate("document.querySelectorAll('#graph-canvas g.graph-node').length")

    print(f"[{label}] initial render: {render_ms:.0f}ms  (budget {render_budget_ms:.0f}ms)")
    print(
        f"[{label}] filter latency: {filter_ms:.1f}ms "
        f"(budget {filter_budget_ms:.0f}ms, median of {FILTER_RUNS})"
    )
    print(
        f"[{label}] graph init block: {graph_init_ms:.0f}ms "
        f"(budget {GRAPH_INIT_BUDGET_MS:.0f}ms, {nodes_drawn} nodes)"
    )
    failures = []
    if render_ms > render_budget_ms:
        failures.append(f"[{label}] initial render {render_ms:.0f}ms > {render_budget_ms:.0f}ms")
    if filter_ms > filter_budget_ms:
        failures.append(f"[{label}] filter latency {filter_ms:.1f}ms > {filter_budget_ms:.0f}ms")
    if graph_init_ms > GRAPH_INIT_BUDGET_MS:
        failures.append(
            f"[{label}] graph init block {graph_init_ms:.0f}ms > {GRAPH_INIT_BUDGET_MS:.0f}ms"
        )
    if graph["optIn"] != expect_opt_in:
        if expect_opt_in:
            failures.append(
                f"[{label}] graph rendered without the Render-anyway gate - the fixture no "
                f"longer exceeds the node threshold, so the budget measured the wrong (cheap) path"
            )
        else:
            failures.append(
                f"[{label}] graph unexpectedly hit the Render-anyway gate - the fixture grew "
                f"past the node threshold; its budgets no longer measure the intended tier"
            )
    if nodes_drawn == 0:
        failures.append(f"[{label}] graph view drew 0 nodes - graph init failed")
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

    from sdr_visualizer.adapters.aa import adapt as aa_adapt
    from sdr_visualizer.adapters.cja import adapt as cja_adapt
    from sdr_visualizer.render.renderer import render

    adapters = {"cja": cja_adapt, "aa": aa_adapt}

    failures: list[str] = []
    checked = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        with tempfile.TemporaryDirectory() as tmp:
            for fixture, adapter_key, render_budget, filter_budget, expect_opt_in in FIXTURES:
                if not fixture.exists():
                    print(f"note: {fixture.name} not generated; skipping")
                    continue
                snap = json.loads(fixture.read_text(encoding="utf-8"))
                html_path = Path(tmp) / f"{fixture.stem}.html"
                html_path.write_text(render(adapters[adapter_key](snap)), encoding="utf-8")
                failures += _check(
                    page, html_path, fixture.stem, render_budget, filter_budget, expect_opt_in
                )
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
