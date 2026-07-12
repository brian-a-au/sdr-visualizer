"""Performance gate (SPEC-VISUALIZER §6).

Renders fixtures and asserts the build-time + HTML-size budgets across all
four SPEC §6 tiers. CI runs this after pytest (see .github/workflows/test.yml).

  - CJA small (100 components, `generate_large_fixture.py --scale 0.083`):
    100-component budgets (build < 1s, size < 0.5MB). Skipped when absent.
  - CJA medium (~500 components, `--scale 0.417`): 500-component budgets
    (build < 3s, size < 2MB). Skipped when absent.
  - CJA / AA large (~1,200 / ~900 components): 1,000-component budgets
    (build < 6s, size < 4MB)
  - CJA XL (~2,000 components, generated on demand via
    `generate_large_fixture.py --scale 1.67 --output tests/fixtures/cja_snapshot_xl.json`):
    2,000-component budgets (build < 12s, size < 8MB). Skipped when absent.

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
from sdr_visualizer.render.renderer import build_payload_with_options, render, render_payload

REPO = Path(__file__).resolve().parent.parent
CJA_LARGE = REPO / "tests" / "fixtures" / "cja_snapshot_large.json"
AA_LARGE = REPO / "tests" / "fixtures" / "aa_snapshot_large.json"

BUILD_BUDGET_S = 6.0
SIZE_BUDGET_MB = 4.0

CJA_XL = REPO / "tests" / "fixtures" / "cja_snapshot_xl.json"
XL_BUILD_BUDGET_S = 12.0
XL_SIZE_BUDGET_MB = 8.0

# Small tiers (SPEC §6 rows previously unenforced — the fixed CSS+JS+D3
# overhead alone is ~340 KB, i.e. ~68% of the 100-component size budget,
# so static-asset growth is exactly what these tiers watch).
CJA_SMALL = REPO / "tests" / "fixtures" / "cja_snapshot_small.json"
SMALL_BUILD_BUDGET_S = 1.0
SMALL_SIZE_BUDGET_MB = 0.5
CJA_MEDIUM = REPO / "tests" / "fixtures" / "cja_snapshot_medium.json"
MEDIUM_BUILD_BUDGET_S = 3.0
MEDIUM_SIZE_BUDGET_MB = 2.0

# Comparative case (0.4.0): large CJA fixture vs its mutated copy.
# Budgets per the 0.4.0 spec: 1.5x the tier's build budget; the tier's
# size budget + 0.5 MB.
COMPARE_BUILD_BUDGET_S = BUILD_BUDGET_S * 1.5
COMPARE_SIZE_BUDGET_MB = SIZE_BUDGET_MB + 0.5


def _load_mutate():
    spec = importlib.util.spec_from_file_location(
        "mutate_fixture", REPO / "scripts" / "mutate_fixture.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.mutate


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
    size_mb = len(html.encode("utf-8")) / (1024 * 1024)
    msgs = [
        f"[CJA-compare] build time: {elapsed:.2f}s   (budget {COMPARE_BUILD_BUDGET_S}s, median of 3)",
        f"[CJA-compare] HTML size : {size_mb:.2f}MB  (budget {COMPARE_SIZE_BUDGET_MB}MB)",
    ]
    failures = []
    if elapsed > COMPARE_BUILD_BUDGET_S:
        failures.append(
            f"CJA-compare build time {elapsed:.2f}s over budget {COMPARE_BUILD_BUDGET_S}s"
        )
    if size_mb > COMPARE_SIZE_BUDGET_MB:
        failures.append(
            f"CJA-compare HTML size {size_mb:.2f}MB over budget {COMPARE_SIZE_BUDGET_MB}MB"
        )
    return failures, "\n".join(msgs)


def _measure(
    label: str,
    snap: dict,
    adapt,
    build_budget_s: float = BUILD_BUDGET_S,
    size_budget_mb: float = SIZE_BUDGET_MB,
) -> tuple[list[str], str]:
    times = []
    html = ""
    for _ in range(3):
        start = time.perf_counter()
        impl = adapt(snap)
        html = render(impl)
        times.append(time.perf_counter() - start)
    elapsed = statistics.median(times)
    size_mb = len(html.encode("utf-8")) / (1024 * 1024)

    msgs = [
        f"[{label}] build time: {elapsed:.2f}s   (budget {build_budget_s}s, median of 3)",
        f"[{label}] HTML size : {size_mb:.2f}MB  (budget {size_budget_mb}MB)",
    ]
    failures = []
    if elapsed > build_budget_s:
        failures.append(f"[{label}] build time {elapsed:.2f}s > {build_budget_s}s budget")
    if size_mb > size_budget_mb:
        failures.append(f"[{label}] HTML size {size_mb:.2f}MB > {size_budget_mb}MB budget")
    return failures, "\n".join(msgs)


def main() -> int:
    for fixture, generator in [
        (CJA_LARGE, "scripts/generate_large_fixture.py"),
        (AA_LARGE, "scripts/generate_aa_large_fixture.py"),
    ]:
        if not fixture.exists():
            print(
                f"sdr-visualizer: fixture {fixture} missing; run "
                f"`uv run python {generator}` first.",
                file=sys.stderr,
            )
            return 2

    cja_snap = json.loads(CJA_LARGE.read_text(encoding="utf-8"))
    aa_snap = json.loads(AA_LARGE.read_text(encoding="utf-8"))

    small_failures: list[str] = []
    for path, label, build_b, size_b in [
        (CJA_SMALL, "CJA-100", SMALL_BUILD_BUDGET_S, SMALL_SIZE_BUDGET_MB),
        (CJA_MEDIUM, "CJA-500", MEDIUM_BUILD_BUDGET_S, MEDIUM_SIZE_BUDGET_MB),
    ]:
        if path.exists():
            snap = json.loads(path.read_text(encoding="utf-8"))
            tier_failures, tier_report = _measure(label, snap, cja_adapt, build_b, size_b)
            small_failures += tier_failures
            print(tier_report)
        else:
            print(f"note: {path.name} not generated; skipping {label} gate")

    cja_failures, cja_report = _measure("CJA", cja_snap, cja_adapt)
    print(cja_report)
    aa_failures, aa_report = _measure("AA", aa_snap, aa_adapt)
    print(aa_report)

    compare_failures, compare_report = _measure_compare(_load_mutate()(cja_snap), cja_snap)
    print(compare_report)

    xl_failures: list[str] = []
    if CJA_XL.exists():
        xl_snap = json.loads(CJA_XL.read_text(encoding="utf-8"))
        xl_failures, xl_report = _measure(
            "CJA-XL", xl_snap, cja_adapt, XL_BUILD_BUDGET_S, XL_SIZE_BUDGET_MB
        )
        print(xl_report)
    else:
        print("note: cja_snapshot_xl.json not generated; skipping 2,000-component gate")

    failed = [*small_failures, *cja_failures, *aa_failures, *compare_failures, *xl_failures]
    if failed:
        for msg in failed:
            print(f"FAIL: {msg}", file=sys.stderr)
        return 1

    print("OK: all budgets met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
