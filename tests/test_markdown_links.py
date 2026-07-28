"""Tests for the tracked-document Markdown link checker."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_markdown_links.py"


@pytest.fixture
def checker():
    spec = importlib.util.spec_from_file_location("check_markdown_links", SCRIPT)
    if spec is None or spec.loader is None:
        pytest.fail(f"could not load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tracked(*paths: str) -> set[str]:
    return set(paths)


def test_missing_inline_target_is_reported(checker, tmp_path):
    source = tmp_path / "README.md"
    source.write_text("[missing](docs/nope.md)\n", encoding="utf-8")

    errors = checker.check_markdown_file(
        source,
        repo=tmp_path,
        tracked_paths=_tracked("README.md"),
    )

    assert errors == ["README.md:1: local link target is not tracked: docs/nope.md"]


def test_path_escape_is_reported(checker, tmp_path):
    source = tmp_path / "docs" / "guide.md"
    source.parent.mkdir()
    source.write_text("[private](../../private.md)\n", encoding="utf-8")

    errors = checker.check_markdown_file(
        source,
        repo=tmp_path,
        tracked_paths=_tracked("docs/guide.md"),
    )

    assert errors == ["docs/guide.md:1: local link escapes the repository: ../../private.md"]


def test_existing_but_untracked_target_is_reported(checker, tmp_path):
    source = tmp_path / "README.md"
    ignored = tmp_path / "SPEC.md"
    source.write_text("[spec](SPEC.md)\n", encoding="utf-8")
    ignored.write_text("# Private spec\n", encoding="utf-8")

    errors = checker.check_markdown_file(
        source,
        repo=tmp_path,
        tracked_paths=_tracked("README.md"),
    )

    assert errors == ["README.md:1: local link target is not tracked: SPEC.md"]


def test_missing_markdown_anchor_is_reported(checker, tmp_path):
    source = tmp_path / "README.md"
    target = tmp_path / "docs" / "guide.md"
    target.parent.mkdir()
    source.write_text("[section](docs/guide.md#not-here)\n", encoding="utf-8")
    target.write_text("# Actual heading\n", encoding="utf-8")

    errors = checker.check_markdown_file(
        source,
        repo=tmp_path,
        tracked_paths=_tracked("README.md", "docs/guide.md"),
    )

    assert errors == ["README.md:1: Markdown anchor does not exist: docs/guide.md#not-here"]


def test_valid_anchor_and_reference_definition_pass(checker, tmp_path):
    source = tmp_path / "README.md"
    target = tmp_path / "docs" / "guide.md"
    target.parent.mkdir()
    source.write_text(
        "[contract][guide]\n\n[guide]: docs/guide.md#public-contract\n", encoding="utf-8"
    )
    target.write_text("# Public contract\n\n## Public contract\n", encoding="utf-8")

    errors = checker.check_markdown_file(
        source,
        repo=tmp_path,
        tracked_paths=_tracked("README.md", "docs/guide.md"),
    )

    assert errors == []


def test_remote_links_and_fenced_examples_are_ignored(checker, tmp_path):
    source = tmp_path / "README.md"
    source.write_text(
        "[site](https://example.com/path)\n"
        "[mail](mailto:maintainer@example.com)\n"
        "```markdown\n"
        "[illustration](missing.md)\n"
        "```\n",
        encoding="utf-8",
    )

    errors = checker.check_markdown_file(
        source,
        repo=tmp_path,
        tracked_paths=_tracked("README.md"),
    )

    assert errors == []


def test_all_repository_markdown_links_are_valid(checker):
    assert checker.check_repository(REPO) == []
