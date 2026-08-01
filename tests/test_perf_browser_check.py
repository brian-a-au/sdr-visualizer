"""Policy tests for the required real-browser performance matrix."""

from __future__ import annotations

import importlib.util
from pathlib import Path

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


def test_any_missing_declared_fixture_fails_preflight(tmp_path):
    present = tmp_path / "present.json"
    present.write_text("{}", encoding="utf-8")
    missing = tmp_path / "missing.json"
    cases = [
        perf_browser_check.BrowserFixture(present, "cja", 100, 200.0, 50.0, False),
        perf_browser_check.BrowserFixture(missing, "cja", 500, 500.0, 100.0, False),
    ]

    assert perf_browser_check._missing_required_fixtures(cases) == [missing]


def test_browser_jobs_generate_small_and_medium_fixtures():
    for workflow_name in ("test.yml", "release.yml"):
        workflow = (REPO / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
        browser_job = workflow.split("  browser-perf:", 1)[1]
        if "\n  build:" in browser_job:
            browser_job = browser_job.split("\n  build:", 1)[0]

        assert "--scale 0.083 --output tests/fixtures/cja_snapshot_small.json" in browser_job
        assert "--scale 0.417 --output tests/fixtures/cja_snapshot_medium.json" in browser_job
