"""Phase 9 perf tests (SPEC-VISUALIZER §6).

Asserts the budgets that gate CI: build time + HTML size at the 1,000-
component-class workload (the bundled cja_snapshot_large.json carries
1,200 components).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from sdr_visualizer.adapters.cja import adapt
from sdr_visualizer.render.renderer import render

FIXTURES = Path(__file__).parent / "fixtures"
LARGE = FIXTURES / "cja_snapshot_large.json"


@pytest.mark.skipif(not LARGE.exists(), reason="large fixture not generated yet")
def test_large_fixture_meets_budget():
    snap = json.loads(LARGE.read_text(encoding="utf-8"))
    start = time.perf_counter()
    impl = adapt(snap)
    html = render(impl)
    elapsed = time.perf_counter() - start
    size_mb = len(html.encode("utf-8")) / (1024 * 1024)

    # Spec §6: 1,000 components → build < 6s, size < 4MB.
    # Loosen slightly: the bundled fixture has 1,200 components.
    assert elapsed < 6.0, f"build time {elapsed:.2f}s exceeds budget"
    assert size_mb < 4.0, f"HTML size {size_mb:.2f}MB exceeds budget"
