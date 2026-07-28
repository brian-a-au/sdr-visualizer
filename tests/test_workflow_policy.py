"""Tests for the GitHub Actions supply-chain policy checker."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_workflow_policy.py"
SHA = "a" * 40

spec = importlib.util.spec_from_file_location("check_workflow_policy", SCRIPT)
check_workflow_policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_workflow_policy)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _basic_workflow(action_ref: str, permissions: str = "contents: read") -> str:
    return f"""
name: basic
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    permissions:
      {permissions}
    steps:
      - uses: actions/checkout@{action_ref}
"""


def _release_workflow(*, publish_needs: str = "build", publish_verify: bool = True) -> str:
    verify = (
        "      - run: cd dist/packages && sha256sum -c ../SHA256SUMS\n" if publish_verify else ""
    )
    return f"""
name: release
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@{SHA}
      - name: Build distributions
        run: uv build --out-dir dist/packages
      - name: Smoke installed artifacts
        run: uv run python scripts/package_smoke_check.py dist/packages/
      - name: Generate SHA256SUMS
        run: cd dist/packages && sha256sum *.whl *.tar.gz > ../SHA256SUMS
      - name: Store verified distributions
        uses: actions/upload-artifact@{SHA}
        with:
          path: |
            dist/packages/*.whl
            dist/packages/*.tar.gz
            dist/SHA256SUMS
  publish:
    needs: {publish_needs}
    runs-on: ubuntu-latest
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@{SHA}
        with:
          path: dist
{verify}      - uses: pypa/gh-action-pypi-publish@{SHA}
        with:
          packages-dir: dist/packages/
  github-release:
    needs: publish
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/download-artifact@{SHA}
        with:
          path: dist
      - run: cd dist/packages && sha256sum -c ../SHA256SUMS
      - uses: softprops/action-gh-release@{SHA}
        with:
          files: |
            dist/packages/*.whl
            dist/packages/*.tar.gz
            dist/SHA256SUMS
"""


def test_rejects_mutable_and_short_remote_action_refs(tmp_path):
    mutable = _write(tmp_path, "mutable.yml", _basic_workflow("v7"))
    assert any(
        "immutable 40-character SHA" in error for error in check_workflow_policy.check(mutable)
    )

    short = _write(tmp_path, "short.yml", _basic_workflow("abc1234"))
    assert any(
        "immutable 40-character SHA" in error for error in check_workflow_policy.check(short)
    )


def test_rejects_top_level_write_and_unneeded_job_write(tmp_path):
    top_level = _write(
        tmp_path,
        "top.yml",
        _basic_workflow(SHA).replace("jobs:", "permissions:\n  contents: write\njobs:"),
    )
    assert any(
        "top-level write permission" in error for error in check_workflow_policy.check(top_level)
    )

    excess = _write(tmp_path, "excess.yml", _basic_workflow(SHA, "contents: write"))
    assert any(
        "unneeded write permission" in error for error in check_workflow_policy.check(excess)
    )


def test_rejects_wrong_release_dependency_order(tmp_path):
    workflow = _write(
        tmp_path,
        "release.yml",
        _release_workflow(publish_needs="other"),
    )
    assert any(
        "publish must need build" in error for error in check_workflow_policy.check(workflow)
    )


def test_rejects_github_release_that_can_run_before_publish(tmp_path):
    workflow = _write(
        tmp_path,
        "release.yml",
        _release_workflow().replace(
            "github-release:\n    needs: publish",
            "github-release:\n    needs: build",
        ),
    )
    assert any(
        "github-release must need publish" in error
        for error in check_workflow_policy.check(workflow)
    )


def test_rejects_always_running_github_release_after_pypi_failure(tmp_path):
    workflow = _write(
        tmp_path,
        "release.yml",
        _release_workflow().replace(
            "github-release:\n    needs: publish",
            "github-release:\n    needs: publish\n    if: always()",
        ),
    )
    assert any("default success gating" in error for error in check_workflow_policy.check(workflow))


def test_rejects_release_stage_without_digest_verification(tmp_path):
    workflow = _write(
        tmp_path,
        "release.yml",
        _release_workflow(publish_verify=False),
    )
    assert any(
        "publish must verify SHA256SUMS" in error for error in check_workflow_policy.check(workflow)
    )


def test_rejects_manifest_inside_pypi_upload_directory(tmp_path):
    workflow = _write(
        tmp_path,
        "release.yml",
        _release_workflow().replace("packages-dir: dist/packages/", "packages-dir: dist/"),
    )
    assert any(
        "packages-dir must exclude" in error for error in check_workflow_policy.check(workflow)
    )


def test_examples_workflow_cannot_push_to_main(tmp_path):
    workflow = _write(
        tmp_path,
        "examples.yml",
        f"""
name: examples
on: push
jobs:
  regenerate:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@{SHA}
      - run: uv run python scripts/generate_examples.py
      - run: git diff --exit-code -- examples/
      - run: git push origin HEAD:main
""",
    )
    assert any("must not push directly" in error for error in check_workflow_policy.check(workflow))


def test_accepts_well_ordered_digest_verified_release(tmp_path):
    workflow = _write(tmp_path, "release.yml", _release_workflow())
    assert check_workflow_policy.check(workflow) == []


def test_all_repository_workflows_pass_policy():
    assert check_workflow_policy.check_repository(REPO) == []
