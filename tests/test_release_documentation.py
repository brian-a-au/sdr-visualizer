"""Durable launch-documentation and release-rubric regressions."""

from __future__ import annotations

import json
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


def test_catalog_and_changes_display_limits_remain_distinct():
    product = (REPO / "docs" / "PRODUCT_CONTRACT.md").read_text(encoding="utf-8")
    performance = (REPO / "docs" / "PERFORMANCE.md").read_text(encoding="utf-8")

    for document in (product, performance):
        normalized = " ".join(document.split())
        assert "first 1,000 matching rows render initially" in normalized
        assert "Show all" in normalized
        assert "no more than 1,000 matching changes render" in normalized
        assert "refine" in normalized


def test_adapter_guide_lists_every_platform_extension_seam_and_payload_boundary():
    guide = (REPO / "docs" / "ADAPTER_GUIDE.md").read_text(encoding="utf-8")

    for phrase in (
        "core/models.py",
        "input/detect.py",
        "core/visualizer.py",
        "cli/main.py",
        "docs/payload-schema.json",
        "render/data_payload.py",
        "render/static/visualizer.js",
        "tests/fixtures/",
        "tests/test_adapters_<name>.py",
        "platform_specific is not embedded",
        "CJA component mappings",
    ):
        assert phrase in guide
    assert "The downstream layers need no changes" not in guide


def test_adapter_guide_json_examples_are_strict_json():
    guide = (REPO / "docs" / "ADAPTER_GUIDE.md").read_text(encoding="utf-8")
    examples = re.findall(r"```json\n(.*?)\n```", guide, flags=re.DOTALL)

    assert examples
    for example in examples:
        json.loads(example)


def test_embedded_format_uses_placeholders_and_marks_tree_shapes_illustrative():
    guide = (REPO / "docs" / "EMBEDDED_DATA_FORMAT.md").read_text(encoding="utf-8")
    normalized = " ".join(guide.split())

    assert '"adapter_version":       "<generator-version>"' in guide
    assert '"visualizer_version":    "<visualizer-version>"' in guide
    assert "tree examples below are illustrative" in normalized
    assert "node `kind` values are stable" in normalized
    assert '"visualizer_version":    "0.2.0"' not in guide


def test_changelog_uses_unreleased_to_release_convention_and_complete_links():
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    contributing = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
    normalized_contributing = " ".join(contributing.split())

    assert "## [Unreleased]" in changelog
    assert "## [1.0.5] - 2026-07-31" in changelog
    assert "## [1.0.6] - 2026-08-01" in changelog
    assert (
        f"[{version}]: https://github.com/brian-a-au/sdr-visualizer/releases/tag/v{version}"
        in changelog
    )
    assert (
        f"[Unreleased]: https://github.com/brian-a-au/sdr-visualizer/compare/v{version}...HEAD"
        in changelog
    )
    assert "Keep changes under `Unreleased`" in normalized_contributing
    assert "rename `Unreleased` to the version and release date" in normalized_contributing
    assert "add a fresh empty `Unreleased` section" in normalized_contributing


def test_project_urls_expose_public_discovery_routes():
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["urls"] == {
        "Homepage": "https://brian-a-au.github.io/sdr-visualizer/",
        "Documentation": "https://github.com/brian-a-au/sdr-visualizer#documentation",
        "Repository": "https://github.com/brian-a-au/sdr-visualizer",
        "Changelog": "https://github.com/brian-a-au/sdr-visualizer/blob/main/CHANGELOG.md",
        "Issues": "https://github.com/brian-a-au/sdr-visualizer/issues",
    }


def test_pages_landing_exposes_install_examples_and_authoritative_routes():
    pages = (REPO / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    normalized = " ".join(pages.split())

    for phrase in (
        "uv tool install sdr-visualizer",
        "https://pypi.org/project/sdr-visualizer/",
        "https://github.com/brian-a-au/sdr-visualizer#documentation",
        "https://github.com/brian-a-au/sdr-visualizer",
        "https://github.com/brian-a-au/sdr-visualizer/blob/main/CHANGELOG.md",
        "https://github.com/brian-a-au/sdr-visualizer/issues",
        "https://github.com/brian-a-au/sdr-visualizer/blob/main/SECURITY.md",
        'href="cja-typical.html"',
        'href="aa-typical.html"',
        "current <code>main</code>",
        "may be ahead of the latest PyPI release",
        "PyPI is the authority for released versions",
    ):
        assert phrase in normalized


def test_derived_kind_public_documentation_matches_sparse_contract():
    document = (REPO / "docs" / "EMBEDDED_DATA_FORMAT.md").read_text(encoding="utf-8")

    assert '"derived_kind":   "dimension" | "metric"' in document
    assert "only for CJA derived fields" in document
    assert "omitted for undeclared or legacy derived fields" in document
    assert "omitted from every non-derived component" in document


def test_release_matrix_has_one_row_for_each_closure_requirement():
    releasing = (REPO / "docs" / "RELEASING.md").read_text(encoding="utf-8")

    for number in range(25, 38):
        assert len(re.findall(rf"^\| R{number} ", releasing, flags=re.MULTILINE)) == 1


def test_release_rubric_freezes_durable_record_and_four_reopen_classes():
    releasing = (REPO / "docs" / "RELEASING.md").read_text(encoding="utf-8")

    for phrase in (
        "critical security vulnerability",
        "data loss on a normal supported path",
        "broken installation or publication",
        "regression introduced by the current patch release",
        "supplemental, not authoritative",
        "durable release-PR permalinks",
    ):
        assert phrase in releasing
    assert "v1.0.6 closure patch" not in releasing


def test_release_rubric_covers_documentation_patch_public_surfaces_generically():
    releasing = (REPO / "docs" / "RELEASING.md").read_text(encoding="utf-8")

    for number in range(1, 16):
        assert len(re.findall(rf"^\| P{number} ", releasing, flags=re.MULTILINE)) == 1
    for phrase in (
        "current candidate version",
        "wheel and source distribution long descriptions",
        "Warehouse-rendered long description",
        "project URLs",
        "Pages deployment SHA",
        "examples track current `main`",
        "diff-backed N/A",
        "upstream-freshness",
    ):
        assert phrase in releasing


def test_current_metadata_lock_and_changelog_are_synchronized():
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    lock = (REPO / "uv.lock").read_text(encoding="utf-8")
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    version = project["project"]["version"]

    assert __version__ == version
    assert f'name = "sdr-visualizer"\nversion = "{version}"' in lock
    assert re.search(rf"^## \[{re.escape(version)}] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.M)
