"""Durable launch-documentation and release-rubric regressions."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from sdr_visualizer import __version__

REPO = Path(__file__).resolve().parent.parent


def test_readme_keeps_live_test_badge_without_fixed_numeric_count():
    readme = (REPO / "README.md").read_text(encoding="utf-8")

    assert "actions/workflows/test.yml/badge.svg" in readme
    assert not re.search(r"shields\.io/badge/tests-[0-9]", readme)


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
