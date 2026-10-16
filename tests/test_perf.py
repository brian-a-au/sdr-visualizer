"""Tests for the published Python-side performance gate.

Asserts the budgets that gate CI: build time + HTML size at the 1,000-
component-class workload. Two large fixtures are exercised — CJA (1,200
components) and AA (~900 components) — since the renderer paths through
each adapter differ enough that one passing doesn't imply the other.
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest

from sdr_visualizer.adapters.aa import adapt as aa_adapt
from sdr_visualizer.adapters.cja import adapt as cja_adapt
from sdr_visualizer.render.renderer import build_payload_with_options, render

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parent.parent

generator_spec = importlib.util.spec_from_file_location(
    "generate_large_fixture", REPO / "scripts" / "generate_large_fixture.py"
)
generate_large_fixture = importlib.util.module_from_spec(generator_spec)
generator_spec.loader.exec_module(generate_large_fixture)


def _budget_check(snap: dict, adapt):
    start = time.perf_counter()
    impl = adapt(snap)
    html = render(impl)
    elapsed = time.perf_counter() - start
    size_bytes = len(html.encode("utf-8"))
    # Spec §6: 1,000 components → build < 6s, size < 4MB.
    assert elapsed < 6.0, f"build time {elapsed:.2f}s exceeds budget"
    assert size_bytes < 4_000_000, f"HTML size {size_bytes} bytes exceeds budget"


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


def test_dense_graph_fixture_has_expected_node_and_edge_pressure():
    snap = generate_large_fixture.build_snapshot(scale=5 / 6, dense_graph_edges=7_800)
    payload = build_payload_with_options(cja_adapt(snap))
    html = render(cja_adapt(snap))

    assert 990 <= payload["meta"]["component_count"] <= 1_010
    assert 7_800 <= len(payload["graph"]["edges"]) <= 8_000
    assert len(html.encode("utf-8")) < 4_000_000


def test_browser_graph_edge_limit_matches_python_performance_gate():
    javascript = (
        REPO / "src" / "sdr_visualizer" / "render" / "static" / "visualizer.js"
    ).read_text(encoding="utf-8")

    assert "var GRAPH_EDGE_THRESHOLD = 8000;" in javascript


spec = importlib.util.spec_from_file_location("perf_check", REPO / "scripts" / "perf_check.py")
perf_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(perf_check)


@pytest.mark.parametrize(
    "budget",
    [
        perf_check.SMALL_SIZE_BUDGET_BYTES,
        perf_check.MEDIUM_SIZE_BUDGET_BYTES,
        perf_check.SIZE_BUDGET_BYTES,
        perf_check.XL_SIZE_BUDGET_BYTES,
    ],
)
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_fixture_size_boundary(monkeypatch, budget, delta):
    # Include multibyte text so character counts cannot satisfy this assertion.
    html = "é" + "x" * (budget + delta - 2)
    monkeypatch.setattr(perf_check, "render", lambda impl: html)
    monkeypatch.setattr(perf_check.time, "perf_counter", lambda: 0)
    failures, _ = perf_check._measure("boundary", {}, lambda snap: None, size_budget_bytes=budget)
    assert bool(failures) == (delta >= 0)


@pytest.mark.parametrize("budget", [1.0, 3.0, 6.0, 12.0])
@pytest.mark.parametrize("delta", [-0.125, 0, 0.125])
def test_fixture_build_boundary(monkeypatch, budget, delta):
    times = iter([0, budget + delta] * 3)
    monkeypatch.setattr(perf_check.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(perf_check, "render", lambda impl: "")
    failures, _ = perf_check._measure("boundary", {}, lambda snap: None, build_budget_s=budget)
    assert bool(failures) == (delta >= 0)


@pytest.mark.parametrize("mode", ["compare", "trend"])
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_comparative_size_allowance_once(monkeypatch, mode, delta):
    monkeypatch.setattr(perf_check, "cja_adapt", lambda snap: None)
    monkeypatch.setattr(perf_check, "build_payload_with_options", lambda impl: {"meta": {}})
    monkeypatch.setattr(perf_check, "diff_implementations", lambda *args: {"baseline": {}})
    monkeypatch.setattr(perf_check, "build_trend", lambda *args, **kwargs: {})
    monkeypatch.setattr(perf_check, "render_payload", lambda payload: "x" * (4_500_000 + delta))
    monkeypatch.setattr(perf_check.time, "perf_counter", lambda: 0)
    if mode == "compare":
        failures, _ = perf_check._measure_compare({}, {})
    else:
        failures, _ = perf_check._measure_trend({}, lambda snap: snap)
    assert bool(failures) == (delta >= 0)


@pytest.mark.parametrize("mode,budget", [("compare", 9.0), ("trend", 6.0)])
@pytest.mark.parametrize("delta", [-0.125, 0, 0.125])
def test_comparative_build_boundary(monkeypatch, mode, budget, delta):
    monkeypatch.setattr(perf_check, "cja_adapt", lambda snap: None)
    monkeypatch.setattr(perf_check, "build_payload_with_options", lambda impl: {"meta": {}})
    monkeypatch.setattr(perf_check, "diff_implementations", lambda *args: {"baseline": {}})
    monkeypatch.setattr(perf_check, "build_trend", lambda *args, **kwargs: {})
    monkeypatch.setattr(perf_check, "render_payload", lambda payload: "")
    times = iter([0, budget + delta] * 3)
    monkeypatch.setattr(perf_check.time, "perf_counter", lambda: next(times))
    if mode == "compare":
        failures, _ = perf_check._measure_compare({}, {})
    else:
        failures, _ = perf_check._measure_trend({}, lambda snap: snap)
    assert bool(failures) == (delta >= 0)


def test_fixture_and_corpus_tier_budgets_agree_exactly():
    spec = importlib.util.spec_from_file_location(
        "corpus_check", REPO / "scripts" / "corpus_check.py"
    )
    corpus = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corpus)
    budgets = [
        perf_check.SMALL_SIZE_BUDGET_BYTES,
        perf_check.MEDIUM_SIZE_BUDGET_BYTES,
        perf_check.SIZE_BUDGET_BYTES,
        perf_check.XL_SIZE_BUDGET_BYTES,
    ]
    assert budgets == [500_000, 2_000_000, 4_000_000, 8_000_000]
    assert [corpus._tier_budget_bytes(count) for count in (100, 500, 1000, 2000)] == budgets
    assert corpus._tier_budget_bytes(2001) is None
    assert perf_check.COMPARE_SIZE_BUDGET_BYTES == 4_500_000
    assert perf_check.TREND_SIZE_BUDGET_BYTES == 4_500_000
