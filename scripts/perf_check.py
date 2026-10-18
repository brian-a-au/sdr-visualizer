"""Published Python-side performance gate.

Renders fixtures and asserts the build-time + HTML-size budgets across all
four documented tiers. CI runs this after pytest (see .github/workflows/test.yml).

  - CJA small (100 components, `generate_large_fixture.py --scale 0.083`):
    100-component budgets (build < 1s, size < 0.5MB). Required.
  - CJA medium (~500 components, `--scale 0.417`): 500-component budgets
    (build < 3s, size < 2MB). Required.
  - CJA / AA large (~1,200 / ~900 components): 1,000-component budgets
    (build < 6s, size < 4MB)
  - CJA XL (~2,000 components, generated on demand via
    `generate_large_fixture.py --scale 1.67 --output tests/fixtures/cja_snapshot_xl.json`):
    2,000-component budgets (build < 12s, size < 8MB). Required.

Build time is the median of 3 runs per fixture.

Browser-side budgets (initial render, filter latency) are gated separately
by scripts/perf_browser_check.py.

Run via:

    uv run python scripts/perf_check.py
"""

from __future__ import annotations

import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path

from sdr_visualizer.adapters.aa import adapt as aa_adapt
from sdr_visualizer.adapters.cja import adapt as cja_adapt
from sdr_visualizer.analysis.diff import diff_implementations
from sdr_visualizer.analysis.trend import build_trend
from sdr_visualizer.render.renderer import build_payload_with_options, render, render_payload

REPO = Path(__file__).resolve().parent.parent
CJA_LARGE = REPO / "tests" / "fixtures" / "cja_snapshot_large.json"
AA_LARGE = REPO / "tests" / "fixtures" / "aa_snapshot_large.json"

BUILD_BUDGET_S = 6.0
SIZE_BUDGET_BYTES = 4_000_000

CJA_XL = REPO / "tests" / "fixtures" / "cja_snapshot_xl.json"
XL_BUILD_BUDGET_S = 12.0
XL_SIZE_BUDGET_BYTES = 8_000_000

# Small tiers (the fixed CSS+JS+D3
# overhead alone is ~340 KB, i.e. ~68% of the 100-component size budget,
# so static-asset growth is exactly what these tiers watch).
CJA_SMALL = REPO / "tests" / "fixtures" / "cja_snapshot_small.json"
SMALL_BUILD_BUDGET_S = 1.0
SMALL_SIZE_BUDGET_BYTES = 500_000
CJA_MEDIUM = REPO / "tests" / "fixtures" / "cja_snapshot_medium.json"
MEDIUM_BUILD_BUDGET_S = 3.0
MEDIUM_SIZE_BUDGET_BYTES = 2_000_000

# Comparative case (0.4.0): large CJA fixture vs its mutated copy.
# Budgets per the 0.4.0 spec: 1.5x the tier's build budget; the tier's
# size budget + 0.5 MB.
COMPARE_BUILD_BUDGET_S = BUILD_BUDGET_S * 1.5
COMPARE_SIZE_BUDGET_BYTES = SIZE_BUDGET_BYTES + 500_000

# Trend case (0.5.0): a 6-snapshot series derived from the large CJA fixture
# by applying the deterministic mutation iteratively, built in memory.
TREND_SERIES_LEN = 6
TREND_BUILD_BUDGET_S = TREND_SERIES_LEN * 1.0
TREND_SIZE_BUDGET_BYTES = SIZE_BUDGET_BYTES + 500_000

# Non-failing early warning for deterministic HTML size growth.
HEADROOM_WARNING_RATIO = 0.9

GENERATE = "uv run python scripts/generate_large_fixture.py"
REQUIRED_FIXTURES = [
    ("CJA_SMALL", f"{GENERATE} --scale 0.083 --output tests/fixtures/cja_snapshot_small.json"),
    ("CJA_MEDIUM", f"{GENERATE} --scale 0.417 --output tests/fixtures/cja_snapshot_medium.json"),
    ("CJA_LARGE", GENERATE),
    ("AA_LARGE", "uv run python scripts/generate_aa_large_fixture.py"),
    ("CJA_XL", f"{GENERATE} --scale 1.67 --output tests/fixtures/cja_snapshot_xl.json"),
]


def _headroom_note(label: str, size_bytes: int, budget_bytes: int) -> str | None:
    if HEADROOM_WARNING_RATIO * budget_bytes <= size_bytes < budget_bytes:
        pct = size_bytes * 100 // budget_bytes
        return f"warning: [{label}] HTML size at {pct}% of budget"
    return None


def _load_usage_fixture():
    spec = importlib.util.spec_from_file_location(
        "workspace_usage_fixture", REPO / "scripts" / "workspace_usage_fixture.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_mutate():
    spec = importlib.util.spec_from_file_location(
        "mutate_fixture", REPO / "scripts" / "mutate_fixture.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.mutate


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_large_fixture", REPO / "scripts" / "generate_large_fixture.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_snapshot


def _measure_compare(old_snap: dict, new_snap: dict) -> tuple[list[str], str]:
    times = []
    html = ""
    for _ in range(3):
        start = time.perf_counter()
        old_impl = cja_adapt(old_snap)
        new_impl = cja_adapt(new_snap)
        payload = build_payload_with_options(new_impl)
        payload["changes"] = diff_implementations(old_impl, new_impl)
        payload["meta"]["compared_to"] = payload["changes"]["baseline"]
        html = render_payload(payload)
        times.append(time.perf_counter() - start)
    elapsed = statistics.median(times)
    size_bytes = len(html.encode("utf-8"))
    size_mb = size_bytes / 1_000_000
    msgs = [
        f"[CJA-compare] build time: {elapsed:.2f}s   (budget {COMPARE_BUILD_BUDGET_S}s, median of 3)",
        f"[CJA-compare] HTML size : {size_mb:.2f}MB  (budget {COMPARE_SIZE_BUDGET_BYTES / 1_000_000:g}MB)",
    ]
    if note := _headroom_note("CJA-compare", size_bytes, COMPARE_SIZE_BUDGET_BYTES):
        msgs.append(note)
    failures = []
    if elapsed >= COMPARE_BUILD_BUDGET_S:
        failures.append(
            f"CJA-compare build time {elapsed:.2f}s over budget {COMPARE_BUILD_BUDGET_S}s"
        )
    if size_bytes >= COMPARE_SIZE_BUDGET_BYTES:
        failures.append(
            f"CJA-compare HTML size {size_mb:.2f}MB over budget {COMPARE_SIZE_BUDGET_BYTES / 1_000_000:g}MB"
        )
    return failures, "\n".join(msgs)


def _measure_trend(base_snap: dict, mutate) -> tuple[list[str], str]:
    series = [base_snap]
    for _ in range(TREND_SERIES_LEN - 1):
        series.append(mutate(series[-1]))
    times = []
    html = ""
    for _ in range(3):
        start = time.perf_counter()
        impls = [cja_adapt(s) for s in series]
        trend = build_trend(impls, capped=False)
        payload = build_payload_with_options(impls[-1])
        payload["trend"] = trend
        html = render_payload(payload)
        times.append(time.perf_counter() - start)
    elapsed = statistics.median(times)
    size_bytes = len(html.encode("utf-8"))
    size_mb = size_bytes / 1_000_000
    msgs = [
        f"[CJA-trend] build time: {elapsed:.2f}s   (budget {TREND_BUILD_BUDGET_S}s, "
        f"median of 3, {TREND_SERIES_LEN} snapshots)",
        f"[CJA-trend] HTML size : {size_mb:.2f}MB  (budget {TREND_SIZE_BUDGET_BYTES / 1_000_000:g}MB)",
    ]
    if note := _headroom_note("CJA-trend", size_bytes, TREND_SIZE_BUDGET_BYTES):
        msgs.append(note)
    failures = []
    if elapsed >= TREND_BUILD_BUDGET_S:
        failures.append(f"CJA-trend build time {elapsed:.2f}s over budget {TREND_BUILD_BUDGET_S}s")
    if size_bytes >= TREND_SIZE_BUDGET_BYTES:
        failures.append(
            f"CJA-trend HTML size {size_mb:.2f}MB over budget {TREND_SIZE_BUDGET_BYTES / 1_000_000:g}MB"
        )
    return failures, "\n".join(msgs)


def _measure(
    label: str,
    snap: dict,
    adapt,
    build_budget_s: float = BUILD_BUDGET_S,
    size_budget_bytes: int = SIZE_BUDGET_BYTES,
    usage: bytes | None = None,
) -> tuple[list[str], str]:
    times = []
    html = ""
    for _ in range(3):
        start = time.perf_counter()
        impl = adapt(snap)
        if usage is not None:
            _load_usage_fixture().attach_usage(impl, usage)
        html = render(impl)
        times.append(time.perf_counter() - start)
    elapsed = statistics.median(times)
    size_bytes = len(html.encode("utf-8"))
    size_mb = size_bytes / 1_000_000

    msgs = [
        f"[{label}] build time: {elapsed:.2f}s   (budget {build_budget_s}s, median of 3)",
        f"[{label}] HTML size : {size_mb:.2f}MB  (budget {size_budget_bytes / 1_000_000:g}MB)",
    ]
    if note := _headroom_note(label, size_bytes, size_budget_bytes):
        msgs.append(note)
    failures = []
    if elapsed >= build_budget_s:
        failures.append(f"[{label}] build time {elapsed:.2f}s >= {build_budget_s}s budget")
    if size_bytes >= size_budget_bytes:
        failures.append(
            f"[{label}] HTML size {size_mb:.2f}MB >= {size_budget_bytes / 1_000_000:g}MB budget"
        )
    return failures, "\n".join(msgs)


def main() -> int:
    missing = [
        (globals()[name], command)
        for name, command in REQUIRED_FIXTURES
        if not globals()[name].exists()
    ]
    for fixture, command in missing:
        print(
            f"sdr-visualizer: fixture {fixture} missing; run `{command}` first.",
            file=sys.stderr,
        )
    if missing:
        return 2

    cja_snap = json.loads(CJA_LARGE.read_text(encoding="utf-8"))
    aa_snap = json.loads(AA_LARGE.read_text(encoding="utf-8"))

    small_failures: list[str] = []
    for path, label, build_b, size_b in [
        (CJA_SMALL, "CJA-100", SMALL_BUILD_BUDGET_S, SMALL_SIZE_BUDGET_BYTES),
        (CJA_MEDIUM, "CJA-500", MEDIUM_BUILD_BUDGET_S, MEDIUM_SIZE_BUDGET_BYTES),
    ]:
        snap = json.loads(path.read_text(encoding="utf-8"))
        tier_failures, tier_report = _measure(label, snap, cja_adapt, build_b, size_b)
        small_failures += tier_failures
        print(tier_report)

    cja_failures, cja_report = _measure("CJA", cja_snap, cja_adapt)
    print(cja_report)
    aa_failures, aa_report = _measure("AA", aa_snap, aa_adapt)
    print(aa_report)

    # The generator also retains ~100 ordinary segment/calc edges; keep the
    # total just inside the documented 8,000-edge envelope.
    dense_snap = _load_generator()(scale=5 / 6, dense_graph_edges=7_800)
    dense_failures, dense_report = _measure("CJA-dense", dense_snap, cja_adapt)
    print(dense_report)

    mutate = _load_mutate()

    compare_failures, compare_report = _measure_compare(mutate(cja_snap), cja_snap)
    print(compare_report)

    trend_failures, trend_report = _measure_trend(cja_snap, mutate)
    print(trend_report)

    xl_snap = json.loads(CJA_XL.read_text(encoding="utf-8"))
    xl_failures, xl_report = _measure(
        "CJA-XL", xl_snap, cja_adapt, XL_BUILD_BUDGET_S, XL_SIZE_BUDGET_BYTES
    )
    print(xl_report)

    # Preserve every original gate, then repeat its tier with bounded evidence.
    # Small approaches the HTML cap; XL approaches the normalized 1 MiB cap.
    usage_fixture = _load_usage_fixture()
    usage_failures = []
    for path, adapter, build_b, size_b, projects in [
        (CJA_SMALL, cja_adapt, SMALL_BUILD_BUDGET_S, SMALL_SIZE_BUDGET_BYTES, 500),
        (CJA_MEDIUM, cja_adapt, MEDIUM_BUILD_BUDGET_S, MEDIUM_SIZE_BUDGET_BYTES, 10_000),
        (CJA_LARGE, cja_adapt, BUILD_BUDGET_S, SIZE_BUDGET_BYTES, 10_000),
        (AA_LARGE, aa_adapt, BUILD_BUDGET_S, SIZE_BUDGET_BYTES, 10_000),
        (CJA_XL, cja_adapt, XL_BUILD_BUDGET_S, XL_SIZE_BUDGET_BYTES, 10_000),
    ]:
        snap = json.loads(path.read_text(encoding="utf-8"))
        encoded = usage_fixture.usage_json(adapter(snap), project_count=projects, pad_input=True)
        errors, report = _measure(
            f"{path.stem}-usage", snap, adapter, build_b, size_b, usage=encoded
        )
        usage_failures += errors
        print(report)
    repeated = usage_fixture.usage_json(
        cja_adapt(cja_snap), project_count=20, component_count=500, pad_input=True
    )
    errors, report = _measure("CJA-usage-repeated", cja_snap, cja_adapt, usage=repeated)
    usage_failures += errors
    print(report)

    failed = [
        *usage_failures,
        *small_failures,
        *cja_failures,
        *aa_failures,
        *dense_failures,
        *compare_failures,
        *trend_failures,
        *xl_failures,
    ]
    if failed:
        for msg in failed:
            print(f"FAIL: {msg}", file=sys.stderr)
        return 1

    print("OK: all budgets met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
