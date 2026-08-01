"""Browser-side performance gate for the published budgets.

Measures the budgets Python can't: initial render time, cold/warm
filter/search latency, and the main-thread block when entering the graph
view, in real Chromium via Playwright. All declared tier fixtures are
required. The gate also exercises a disjoint-ID comparison, a 60-snapshot
high-churn trend, and a ~1,000-node/~8,000-edge graph.

Setup + run:

    uv sync --group browser
    uv run playwright install chromium
    uv run python scripts/perf_browser_check.py

Generate the small, medium, and XL fixtures with the commands in
``docs/RELEASING.md`` before running the gate locally.
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent


class BrowserFixture(NamedTuple):
    path: Path
    adapter: str
    expected_components: int
    render_budget_ms: float
    filter_budget_ms: float
    expect_opt_in: bool


# The 1,200/900-component fixtures are asserted against the published
# 1,000-component budgets (like the Python gate); the 2,004-component fixture
# generated at scale 1.67 is asserted against the 2,000-component budgets.
FIXTURES = [
    BrowserFixture(
        REPO / "tests" / "fixtures" / "cja_snapshot_small.json",
        "cja",
        100,
        200.0,
        50.0,
        False,
    ),
    BrowserFixture(
        REPO / "tests" / "fixtures" / "cja_snapshot_medium.json",
        "cja",
        500,
        500.0,
        100.0,
        False,
    ),
    BrowserFixture(
        REPO / "tests" / "fixtures" / "cja_snapshot_large.json",
        "cja",
        1200,
        1000.0,
        150.0,
        True,
    ),
    BrowserFixture(
        REPO / "tests" / "fixtures" / "aa_snapshot_large.json",
        "aa",
        900,
        1000.0,
        150.0,
        False,
    ),
    BrowserFixture(
        REPO / "tests" / "fixtures" / "cja_snapshot_xl.json",
        "cja",
        2004,
        2000.0,
        300.0,
        True,
    ),
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
# Alternate queries so every sample changes the result set and invalidates
# the rendered rows. The first sample is reported separately as cold work.
FILTER_QUERIES = ("dimension 00", "metric 00")
FILTER_WARM_RUNS = 5


def _missing_required_fixtures(fixtures: list[BrowserFixture]) -> list[Path]:
    return [case.path for case in fixtures if not case.path.is_file()]


def _component_count(implementation) -> int:
    return sum(
        len(items)
        for items in (
            implementation.metrics,
            implementation.dimensions,
            implementation.derived_fields,
            implementation.segments,
            implementation.calculated_metrics,
        )
    )


def _check(
    page,
    html_path: Path,
    label: str,
    render_budget_ms: float,
    filter_budget_ms: float,
    expect_opt_in: bool,
    minimum_graph_edges: int = 0,
) -> list[str]:
    start = time.perf_counter()
    page.goto(html_path.as_uri())
    page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    render_ms = (time.perf_counter() - start) * 1000.0

    if not page.evaluate("typeof window.__sdrPerf !== 'undefined'"):
        return [f"[{label}] __sdrPerf missing - client JS failed to initialize"]

    cold_filter_ms = page.evaluate(
        "(query) => window.__sdrPerf.timeFilter(query)", FILTER_QUERIES[0]
    )
    warm_samples = [
        page.evaluate(
            "(query) => window.__sdrPerf.timeFilter(query)",
            FILTER_QUERIES[(index + 1) % len(FILTER_QUERIES)],
        )
        for index in range(FILTER_WARM_RUNS)
    ]
    warm_filter_ms = statistics.median(warm_samples)

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
    edges_drawn = page.evaluate("document.querySelectorAll('#graph-canvas line.graph-edge').length")

    print(f"[{label}] initial render: {render_ms:.0f}ms  (budget {render_budget_ms:.0f}ms)")
    print(
        f"[{label}] cold/warm filter: {cold_filter_ms:.1f}ms / {warm_filter_ms:.1f}ms "
        f"(budget {filter_budget_ms:.0f}ms, warm median of {FILTER_WARM_RUNS})"
    )
    print(
        f"[{label}] graph init block: {graph_init_ms:.0f}ms "
        f"(budget {GRAPH_INIT_BUDGET_MS:.0f}ms, {nodes_drawn} nodes, {edges_drawn} edges)"
    )
    failures = []
    if render_ms > render_budget_ms:
        failures.append(f"[{label}] initial render {render_ms:.0f}ms > {render_budget_ms:.0f}ms")
    if cold_filter_ms > filter_budget_ms:
        failures.append(
            f"[{label}] cold filter latency {cold_filter_ms:.1f}ms > {filter_budget_ms:.0f}ms"
        )
    if warm_filter_ms > filter_budget_ms:
        failures.append(
            f"[{label}] warm filter latency {warm_filter_ms:.1f}ms > {filter_budget_ms:.0f}ms"
        )
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
    if edges_drawn < minimum_graph_edges:
        failures.append(
            f"[{label}] graph drew {edges_drawn} edges; expected at least {minimum_graph_edges}"
        )
    return failures


def _check_compare(page, html_path: Path) -> list[str]:
    """Comparative report: initial render within the 1,000-component budget,
    while the high-churn Changes DOM stays lazy and batch-bounded."""
    start = time.perf_counter()
    page.goto(html_path.as_uri())
    page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    render_ms = (time.perf_counter() - start) * 1000
    eager_rows = page.evaluate("document.querySelectorAll('#changes-body .change-row').length")
    page.click('.view-button[data-view="changes"]')
    page.evaluate("document.getElementById('changes-body').getBoundingClientRect()")
    first_rows = page.evaluate("document.querySelectorAll('#changes-body .change-row').length")
    if page.locator("#changes-show-next").count():
        page.click("#changes-show-next")
    second_rows = page.evaluate("document.querySelectorAll('#changes-body .change-row').length")
    print(
        f"[cja-compare] initial render: {render_ms:.0f}ms  "
        f"(budget 1000ms, eager/first/second rows {eager_rows}/{first_rows}/{second_rows})"
    )
    failures = []
    if render_ms > 1000.0:
        failures.append(f"[cja-compare] initial render {render_ms:.0f}ms > 1000ms")
    if eager_rows != 0:
        failures.append(f"[cja-compare] eagerly rendered {eager_rows} Changes rows")
    if not 0 < first_rows <= 250:
        failures.append(f"[cja-compare] first Changes batch has {first_rows} rows; expected 1..250")
    if not first_rows <= second_rows <= 500:
        failures.append(
            f"[cja-compare] second Changes batch has {second_rows} rows; expected <=500"
        )
    return failures


def _check_trend(page, html_path: Path) -> list[str]:
    """Trend report: initial render within the 1,000-component budget, with
    lazy interval summaries and batched IDs after expansion."""
    start = time.perf_counter()
    page.goto(html_path.as_uri())
    page.wait_for_selector("#catalog-body tr", state="attached", timeout=10_000)
    render_ms = (time.perf_counter() - start) * 1000
    charts = page.evaluate("document.querySelectorAll('#trend-view svg.sparkline').length")
    eager_rows = page.evaluate(
        "document.querySelectorAll('#trend-log details.trend-interval').length"
    )
    page.click('.view-button[data-view="trend"]')
    rows = page.evaluate("document.querySelectorAll('#trend-log details.trend-interval').length")
    eager_ids = page.evaluate("document.querySelectorAll('#trend-log .trend-id').length")
    page.click("#trend-log details.trend-interval:first-child summary")
    first_ids = page.evaluate(
        "document.querySelectorAll('#trend-log details.trend-interval:first-child .trend-id').length"
    )
    print(
        f"[cja-trend] initial render: {render_ms:.0f}ms  "
        f"(budget 1000ms, {charts} charts, {eager_rows}/{rows} eager/lazy intervals, "
        f"{first_ids} first-expansion IDs)"
    )
    failures = []
    if render_ms > 1000.0:
        failures.append(f"[cja-trend] initial render {render_ms:.0f}ms > 1000ms")
    if charts == 0:
        failures.append("[cja-trend] no sparkline charts rendered - trend path is dead")
    if eager_rows != 0:
        failures.append(f"[cja-trend] eagerly rendered {eager_rows} interval rows")
    if rows != 59:
        failures.append(f"[cja-trend] rendered {rows} interval summaries; expected 59")
    if eager_ids != 0:
        failures.append(f"[cja-trend] eagerly rendered {eager_ids} identifier chips")
    if not 0 < first_ids <= 300:
        failures.append(
            f"[cja-trend] first expansion rendered {first_ids} IDs; expected a bounded batch"
        )
    return failures


def main() -> int:
    missing = _missing_required_fixtures(FIXTURES)
    if missing:
        for path in missing:
            print(
                f"FAIL: required browser performance fixture is missing: {path.name}",
                file=sys.stderr,
            )
        return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "playwright not installed; run `uv sync --group browser` "
            "and `uv run playwright install chromium`",
            file=sys.stderr,
        )
        return 2

    import importlib.util

    from sdr_visualizer.adapters.aa import adapt as aa_adapt
    from sdr_visualizer.adapters.cja import adapt as cja_adapt
    from sdr_visualizer.analysis.diff import diff_implementations
    from sdr_visualizer.analysis.trend import build_trend
    from sdr_visualizer.render.renderer import build_payload_with_options, render, render_payload

    spec = importlib.util.spec_from_file_location(
        "mutate_fixture", REPO / "scripts" / "mutate_fixture.py"
    )
    mutate_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mutate_module)
    disjoint_ids = mutate_module.disjoint_ids
    high_churn_series = mutate_module.high_churn_series

    generator_spec = importlib.util.spec_from_file_location(
        "generate_large_fixture", REPO / "scripts" / "generate_large_fixture.py"
    )
    generator_module = importlib.util.module_from_spec(generator_spec)
    generator_spec.loader.exec_module(generator_module)

    adapters = {"cja": cja_adapt, "aa": aa_adapt}

    failures: list[str] = []
    checked = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        with tempfile.TemporaryDirectory() as tmp:
            for case in FIXTURES:
                snap = json.loads(case.path.read_text(encoding="utf-8"))
                implementation = adapters[case.adapter](snap)
                component_count = _component_count(implementation)
                if component_count != case.expected_components:
                    failures.append(
                        f"[{case.path.stem}] fixture has {component_count} components; "
                        f"expected exactly {case.expected_components}"
                    )
                html_path = Path(tmp) / f"{case.path.stem}.html"
                html_path.write_text(render(implementation), encoding="utf-8")
                failures += _check(
                    page,
                    html_path,
                    case.path.stem,
                    case.render_budget_ms,
                    case.filter_budget_ms,
                    case.expect_opt_in,
                )
                checked += 1

            large = REPO / "tests" / "fixtures" / "cja_snapshot_large.json"
            xl = REPO / "tests" / "fixtures" / "cja_snapshot_xl.json"
            compare_fixture = xl if xl.exists() else large
            if compare_fixture.exists():
                compare_snap = json.loads(compare_fixture.read_text(encoding="utf-8"))
                old_impl = adapters["cja"](disjoint_ids(compare_snap, namespace="compare-old"))
                new_impl = adapters["cja"](compare_snap)
                payload = build_payload_with_options(new_impl)
                payload["changes"] = diff_implementations(old_impl, new_impl)
                payload["meta"]["compared_to"] = payload["changes"]["baseline"]
                compare_path = Path(tmp) / "cja_compare.html"
                compare_path.write_text(render_payload(payload), encoding="utf-8")
                failures += _check_compare(page, compare_path)
                checked += 1

            if large.exists():
                large_snap = json.loads(large.read_text(encoding="utf-8"))
                series = high_churn_series(large_snap, count=60)
                impls = [
                    adapters["cja"](snapshot, source=f"high_churn_{index:02d}.json")
                    for index, snapshot in enumerate(series)
                ]
                trend_payload = build_payload_with_options(impls[-1])
                trend_payload["trend"] = build_trend(impls, capped=False)
                trend_path = Path(tmp) / "cja_trend.html"
                trend_path.write_text(render_payload(trend_payload), encoding="utf-8")
                failures += _check_trend(page, trend_path)
                checked += 1

            dense_snap = generator_module.build_snapshot(
                scale=5 / 6,
                # The generator also retains ~100 ordinary segment/calc edges;
                # keep the total just inside the documented 8,000-edge envelope.
                dense_graph_edges=7_800,
            )
            dense_path = Path(tmp) / "cja_dense_graph.html"
            dense_path.write_text(render(adapters["cja"](dense_snap)), encoding="utf-8")
            failures += _check(
                page,
                dense_path,
                "cja-dense-graph",
                1000.0,
                150.0,
                False,
                minimum_graph_edges=7_800,
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
