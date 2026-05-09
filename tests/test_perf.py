"""Phase 9 perf tests (SPEC-VISUALIZER §6).

Asserts the budgets that gate CI: build time + HTML size at the 1,000-
component-class workload. Two large fixtures are exercised — CJA (1,200
components) and AA (~900 components) — since the renderer paths through
each adapter differ enough that one passing doesn't imply the other.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from sdr_visualizer.adapters.aa import adapt as aa_adapt
from sdr_visualizer.adapters.cja import adapt as cja_adapt
from sdr_visualizer.render.renderer import render

FIXTURES = Path(__file__).parent / "fixtures"


def _budget_check(snap: dict, adapt):
    start = time.perf_counter()
    impl = adapt(snap)
    html = render(impl)
    elapsed = time.perf_counter() - start
    size_mb = len(html.encode("utf-8")) / (1024 * 1024)
    # Spec §6: 1,000 components → build < 6s, size < 4MB.
    assert elapsed < 6.0, f"build time {elapsed:.2f}s exceeds budget"
    assert size_mb < 4.0, f"HTML size {size_mb:.2f}MB exceeds budget"


@pytest.mark.skipif(
    not (FIXTURES / "cja_snapshot_large.json").exists(),
    reason="CJA large fixture not generated",
)
def test_cja_large_fixture_meets_budget():
    snap = json.loads((FIXTURES / "cja_snapshot_large.json").read_text(encoding="utf-8"))
    _budget_check(snap, cja_adapt)


@pytest.mark.skipif(
    not (FIXTURES / "aa_snapshot_large.json").exists(),
    reason="AA large fixture not generated",
)
def test_aa_large_fixture_meets_budget():
    snap = json.loads((FIXTURES / "aa_snapshot_large.json").read_text(encoding="utf-8"))
    _budget_check(snap, aa_adapt)
