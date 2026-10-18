"""Policy tests for the required real-browser performance matrix."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "perf_browser_check.py"

spec = importlib.util.spec_from_file_location("perf_browser_check", SCRIPT)
perf_browser_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(perf_browser_check)


def test_required_fixture_matrix_covers_every_published_tier_exactly():
    actual = [
        (
            case.path.name,
            case.adapter,
            case.expected_components,
            case.render_budget_ms,
            case.filter_budget_ms,
            case.expect_opt_in,
        )
        for case in perf_browser_check.FIXTURES
    ]

    assert actual == [
        ("cja_snapshot_small.json", "cja", 100, 200.0, 50.0, False),
        ("cja_snapshot_medium.json", "cja", 500, 500.0, 100.0, False),
        ("cja_snapshot_large.json", "cja", 1200, 1000.0, 150.0, True),
        ("aa_snapshot_large.json", "aa", 900, 1000.0, 150.0, False),
        ("cja_snapshot_xl.json", "cja", 2004, 2000.0, 300.0, True),
    ]


def test_any_missing_declared_fixture_fails_preflight(tmp_path, monkeypatch, capsys):
    present = tmp_path / "present.json"
    present.write_text("{}", encoding="utf-8")
    missing = tmp_path / "missing.json"
    cases = [
        perf_browser_check.BrowserFixture(present, "cja", 100, 200.0, 50.0, False),
        perf_browser_check.BrowserFixture(missing, "cja", 500, 500.0, 100.0, False),
    ]

    monkeypatch.setattr(perf_browser_check, "FIXTURES", cases)

    assert perf_browser_check.main() == 1
    assert capsys.readouterr().err == (
        "FAIL: required browser performance fixture is missing: missing.json\n"
    )


def test_component_count_mismatch_fails_case():
    case = perf_browser_check.BrowserFixture(
        Path("cja_snapshot_medium.json"), "cja", 500, 500.0, 100.0, False
    )
    implementation = SimpleNamespace(
        metrics=[object()] * 499,
        dimensions=[],
        derived_fields=[],
        segments=[],
        calculated_metrics=[],
    )

    assert perf_browser_check._component_count_mismatch(case, implementation) == (
        "[cja_snapshot_medium] fixture has 499 components; expected exactly 500"
    )


def test_browser_jobs_generate_small_and_medium_fixtures():
    for workflow_name in ("test.yml", "release.yml"):
        workflow = (REPO / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
        browser_job = workflow.split("  browser-perf:", 1)[1]
        if "\n  build:" in browser_job:
            browser_job = browser_job.split("\n  build:", 1)[0]

        assert "--scale 0.083 --output tests/fixtures/cja_snapshot_small.json" in browser_job
        assert "--scale 0.417 --output tests/fixtures/cja_snapshot_medium.json" in browser_job


def test_workspace_gate_rejects_truncation_eager_rows_and_slow_interaction():
    observations = {
        "eager": 1,
        "total": 9999,
        "first": 51,
        "second": 100,
        "firstRange": "Showing 1–50 of 10000",
        "secondRange": "Showing 1–50 of 10000",
        "openMs": 101,
        "pageMs": 102,
    }
    failures = perf_browser_check._workspace_failures("synthetic", observations, 10000)
    assert len(failures) == 7
    assert any("embedded" in failure for failure in failures)
    assert any("page replacement" in failure for failure in failures)


def test_workspace_gate_accepts_bounded_replacement_with_all_evidence_retained():
    observations = {
        "eager": 0,
        "total": 10000,
        "first": 50,
        "second": 50,
        "firstRange": "Showing 1–50 of 10000",
        "secondRange": "Showing 51–100 of 10000",
        "openMs": 5,
        "pageMs": 3,
    }
    assert perf_browser_check._workspace_failures("synthetic", observations, 10000) == []


@pytest.mark.parametrize(
    "render_budget,filter_budget", [(200, 50), (500, 100), (1000, 150), (2000, 300)]
)
@pytest.mark.parametrize("phase", ["render", "cold", "warm"])
@pytest.mark.parametrize("delta", [-0.125, 0, 0.125])
def test_browser_published_timing_boundaries(
    monkeypatch, render_budget, filter_budget, phase, delta
):
    elapsed = render_budget + delta if phase == "render" else 0
    ticks = iter([0, elapsed / 1000])
    monkeypatch.setattr(perf_browser_check.time, "perf_counter", lambda: next(ticks))
    page = Mock()
    cold = filter_budget + delta if phase == "cold" else 0
    warm = filter_budget + delta if phase == "warm" else 0
    page.evaluate.side_effect = [
        True,
        cold,
        *([warm] * perf_browser_check.FILTER_WARM_RUNS),
        {"ms": 0, "optIn": False},
        1,
        1,
    ]
    failures = perf_browser_check._check(
        page, Path("/tmp/boundary.html"), "boundary", render_budget, filter_budget, False
    )
    assert bool(failures) == (delta >= 0)


@pytest.mark.parametrize("mode", ["compare", "trend"])
@pytest.mark.parametrize("delta", [-0.125, 0, 0.125])
def test_comparative_browser_render_boundary(monkeypatch, mode, delta):
    ticks = iter([0, (1000 + delta) / 1000])
    monkeypatch.setattr(perf_browser_check.time, "perf_counter", lambda: next(ticks))
    page = Mock()
    if mode == "compare":
        page.evaluate.side_effect = [0, None, 250, 500]
        page.locator.return_value.count.return_value = 1
        failures = perf_browser_check._check_compare(page, Path("/tmp/boundary.html"))
    else:
        page.evaluate.side_effect = [1, 0, 59, 0, 100]
        failures = perf_browser_check._check_trend(page, Path("/tmp/boundary.html"))
    assert bool(failures) == (delta >= 0)


@pytest.mark.parametrize("ms,fails", [(99.9, False), (100.0, True)])
def test_workspace_gate_rejects_exact_budget(ms, fails):
    observations = {
        "eager": 0,
        "total": 10000,
        "first": 50,
        "second": 50,
        "firstRange": "Showing 1–50 of 10000",
        "secondRange": "Showing 51–100 of 10000",
        "openMs": ms,
        "pageMs": 3,
    }
    failures = perf_browser_check._workspace_failures("synthetic", observations, 10000)
    assert bool(failures) == fails
