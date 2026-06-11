"""Performance gate (SPEC-VISUALIZER §6).

Renders the bundled large fixtures and asserts the build-time + HTML-size
budgets. CI runs this after pytest (see .github/workflows/test.yml).

  - CJA / AA large (~1,200 / ~900 components): 1,000-component budgets
    (build < 6s, size < 4MB)
  - CJA XL (~2,000 components, generated on demand via
    `generate_large_fixture.py --scale 1.67 --output tests/fixtures/cja_snapshot_xl.json`):
    2,000-component budgets (build < 12s, size < 8MB). Skipped when absent.

Browser-side budgets (initial render, filter latency) are gated separately
by scripts/perf_browser_check.py.

Run via:

    uv run python scripts/perf_check.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from sdr_visualizer.adapters.aa import adapt as aa_adapt
from sdr_visualizer.adapters.cja import adapt as cja_adapt
from sdr_visualizer.render.renderer import render

REPO = Path(__file__).resolve().parent.parent
CJA_LARGE = REPO / "tests" / "fixtures" / "cja_snapshot_large.json"
AA_LARGE = REPO / "tests" / "fixtures" / "aa_snapshot_large.json"

BUILD_BUDGET_S = 6.0
SIZE_BUDGET_MB = 4.0

CJA_XL = REPO / "tests" / "fixtures" / "cja_snapshot_xl.json"
XL_BUILD_BUDGET_S = 12.0
XL_SIZE_BUDGET_MB = 8.0


def _measure(
    label: str,
    snap: dict,
    adapt,
    build_budget_s: float = BUILD_BUDGET_S,
    size_budget_mb: float = SIZE_BUDGET_MB,
) -> tuple[list[str], str]:
    start = time.perf_counter()
    impl = adapt(snap)
    html = render(impl)
    elapsed = time.perf_counter() - start
    size_mb = len(html.encode("utf-8")) / (1024 * 1024)

    msgs = [
        f"[{label}] build time: {elapsed:.2f}s   (budget {build_budget_s}s)",
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

    cja_failures, cja_report = _measure("CJA", cja_snap, cja_adapt)
    print(cja_report)
    aa_failures, aa_report = _measure("AA", aa_snap, aa_adapt)
    print(aa_report)

    xl_failures: list[str] = []
    if CJA_XL.exists():
        xl_snap = json.loads(CJA_XL.read_text(encoding="utf-8"))
        xl_failures, xl_report = _measure(
            "CJA-XL", xl_snap, cja_adapt, XL_BUILD_BUDGET_S, XL_SIZE_BUDGET_MB
        )
        print(xl_report)
    else:
        print("note: cja_snapshot_xl.json not generated; skipping 2,000-component gate")

    failed = [*cja_failures, *aa_failures, *xl_failures]
    if failed:
        for msg in failed:
            print(f"FAIL: {msg}", file=sys.stderr)
        return 1

    print("OK: all budgets met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
