"""Performance gate (SPEC-VISUALIZER §6).

Renders the bundled large fixture and asserts:
  - build time < 6s    (1000-component budget)
  - HTML size  < 4MB

Run via:

    uv run python scripts/perf_check.py

Exits non-zero if any budget is missed. The CI test workflow doesn't yet
call this — gate it from the workflow once you're ready to enforce.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from sdr_visualizer.adapters.cja import adapt
from sdr_visualizer.render.renderer import render

REPO = Path(__file__).resolve().parent.parent
LARGE = REPO / "tests" / "fixtures" / "cja_snapshot_large.json"

BUILD_BUDGET_S = 6.0
SIZE_BUDGET_MB = 4.0


def main() -> int:
    if not LARGE.exists():
        print(
            f"sdr-visualizer: fixture {LARGE} missing; run "
            "`uv run python scripts/generate_large_fixture.py` first.",
            file=sys.stderr,
        )
        return 2

    snap = json.loads(LARGE.read_text(encoding="utf-8"))
    component_count = (
        len(snap["metrics"])
        + len(snap["dimensions"])
        + len(snap["derived_fields"]["fields"])
        + len(snap["segments"]["segments"])
        + len(snap["calculated_metrics"]["metrics"])
    )

    start = time.perf_counter()
    impl = adapt(snap)
    html = render(impl)
    elapsed = time.perf_counter() - start

    size_mb = len(html.encode("utf-8")) / (1024 * 1024)

    print(f"components: {component_count}")
    print(f"build time: {elapsed:.2f}s   (budget {BUILD_BUDGET_S}s)")
    print(f"HTML size : {size_mb:.2f}MB  (budget {SIZE_BUDGET_MB}MB)")

    failed = []
    if elapsed > BUILD_BUDGET_S:
        failed.append(f"build time {elapsed:.2f}s > {BUILD_BUDGET_S}s budget")
    if size_mb > SIZE_BUDGET_MB:
        failed.append(f"HTML size {size_mb:.2f}MB > {SIZE_BUDGET_MB}MB budget")

    if failed:
        for msg in failed:
            print(f"FAIL: {msg}", file=sys.stderr)
        return 1

    print("OK: all budgets met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
