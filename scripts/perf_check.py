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

from sdr_visualizer.adapters.aa import adapt as aa_adapt
from sdr_visualizer.adapters.cja import adapt as cja_adapt
from sdr_visualizer.render.renderer import render

REPO = Path(__file__).resolve().parent.parent
CJA_LARGE = REPO / "tests" / "fixtures" / "cja_snapshot_large.json"
AA_LARGE = REPO / "tests" / "fixtures" / "aa_snapshot_large.json"

BUILD_BUDGET_S = 6.0
SIZE_BUDGET_MB = 4.0


def _measure(label: str, snap: dict, adapt) -> tuple[bool, str]:
    start = time.perf_counter()
    impl = adapt(snap)
    html = render(impl)
    elapsed = time.perf_counter() - start
    size_mb = len(html.encode("utf-8")) / (1024 * 1024)

    msgs = [
        f"[{label}] build time: {elapsed:.2f}s   (budget {BUILD_BUDGET_S}s)",
        f"[{label}] HTML size : {size_mb:.2f}MB  (budget {SIZE_BUDGET_MB}MB)",
    ]
    failures = []
    if elapsed > BUILD_BUDGET_S:
        failures.append(f"[{label}] build time {elapsed:.2f}s > {BUILD_BUDGET_S}s budget")
    if size_mb > SIZE_BUDGET_MB:
        failures.append(f"[{label}] HTML size {size_mb:.2f}MB > {SIZE_BUDGET_MB}MB budget")
    return failures, "\n".join(msgs)


def main() -> int:
    for fixture, generator in [
        (CJA_LARGE, "scripts/generate_large_fixture.py"),
        (AA_LARGE,  "scripts/generate_aa_large_fixture.py"),
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

    failed = [*cja_failures, *aa_failures]
    if failed:
        for msg in failed:
            print(f"FAIL: {msg}", file=sys.stderr)
        return 1

    print("OK: all budgets met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
