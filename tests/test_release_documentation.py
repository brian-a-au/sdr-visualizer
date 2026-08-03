"""Durable launch-documentation and release-rubric regressions."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from sdr_visualizer import __version__

REPO = Path(__file__).resolve().parent.parent


def test_readme_keeps_live_test_badge_without_fixed_numeric_count():
    readme = (REPO / "README.md").read_text(encoding="utf-8")

    assert "actions/workflows/test.yml/badge.svg" in readme
    assert not re.search(r"shields\.io/badge/tests-[0-9]", readme)


def test_readme_links_are_portable_in_pypi_long_description():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"\]\((?:<([^>]+)>|([^\s)]+))", readme)

    relative = []
    for enclosed, plain in targets:
        target = enclosed or plain
        split = urlsplit(target)
        if not split.scheme and not split.netloc and not target.startswith("#"):
            relative.append(target)

    assert relative == []


def test_readme_distinguishes_saved_and_live_input_contracts():
    readme = (REPO / "README.md").read_text(encoding="utf-8")

    for phrase in (
        "Saved snapshots",
        "Live CJA",
        "Live AA",
        "--include-all-inventory",
        "authentication",
        "PATH",
        "generator may require a newer Python version",
    ):
        assert phrase in readme
    assert "cja_auto_sdr dv_prod_web --format json --output - | sdr-visualizer -" not in readme


def test_readme_describes_navigation_and_browser_evidence_precisely():
    readme = (REPO / "README.md").read_text(encoding="utf-8")

    for phrase in (
        "two base top-level views",
        "conditional top-level view",
        "contextual detail",
        "100 / 500 / 1,000 / 2,000",
        "Chromium and WebKit",
        "Chromium-only",
    ):
        assert phrase in readme


def test_readme_troubleshooting_covers_public_failure_modes_and_safe_sharing():
    readme = (REPO / "README.md").read_text(encoding="utf-8")

    for phrase in (
        "## Troubleshooting",
        "not found",
        "authentication or access",
        "600-second timeout",
        "unknown or ambiguous",
        "mixed directory",
        "Exit `0`",
        "Exit `1`",
        "Exit `3`",
        "graph opt-in",
        "does not open automatically",
        "redact",
    ):
        assert phrase in readme


def test_derived_kind_public_documentation_matches_sparse_contract():
    document = (REPO / "docs" / "EMBEDDED_DATA_FORMAT.md").read_text(encoding="utf-8")

    assert '"derived_kind":   "dimension" | "metric"' in document
    assert "only for CJA derived fields" in document
    assert "omitted for undeclared or legacy derived fields" in document
    assert "omitted from every non-derived component" in document


def test_release_matrix_has_one_row_for_each_closure_requirement():
    releasing = (REPO / "docs" / "RELEASING.md").read_text(encoding="utf-8")

    for number in range(25, 34):
        assert len(re.findall(rf"^\| R{number} ", releasing, flags=re.MULTILINE)) == 1


def test_release_rubric_freezes_durable_record_and_four_reopen_classes():
    releasing = (REPO / "docs" / "RELEASING.md").read_text(encoding="utf-8")

    for phrase in (
        "critical security vulnerability",
        "data loss on a normal supported path",
        "broken installation or publication",
        "regression introduced by the v1.0.6 closure patch",
        "supplemental, not authoritative",
        "durable release-PR permalinks",
    ):
        assert phrase in releasing


def test_v106_metadata_lock_and_changelog_are_synchronized():
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    lock = (REPO / "uv.lock").read_text(encoding="utf-8")
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")

    assert project["project"]["version"] == "1.0.6"
    assert __version__ == "1.0.6"
    assert 'name = "sdr-visualizer"\nversion = "1.0.6"' in lock
    assert "## [1.0.6] - 2026-07-31" in changelog
