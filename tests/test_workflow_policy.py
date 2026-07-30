"""Tests for the GitHub Actions supply-chain policy checker."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

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


def _codeql_workflow(matrix_rows: str) -> str:
    return f"""
name: codeql
on: push
jobs:
  analyze:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write
    strategy:
      fail-fast: false
      matrix:
        include:
{matrix_rows}
    steps:
      - uses: actions/checkout@{SHA}
      - name: Initialize CodeQL
        uses: github/codeql-action/init@{SHA}
        with:
          languages: ${{{{ matrix.language }}}}
          build-mode: ${{{{ matrix.build-mode }}}}
          queries: security-and-quality
      - name: Analyze
        uses: github/codeql-action/analyze@{SHA}
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


def test_docker_actions_require_immutable_image_digests(tmp_path):
    mutable = _write(
        tmp_path,
        "mutable-docker.yml",
        """
name: docker
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: docker://alpine:3.21
""",
    )
    assert any(
        "Docker action must use an immutable sha256 digest" in error
        for error in check_workflow_policy.check(mutable)
    )

    digest = "b" * 64
    pinned = _write(
        tmp_path,
        "pinned-docker.yml",
        mutable.read_text(encoding="utf-8").replace(
            "docker://alpine:3.21",
            f"docker://alpine@sha256:{digest}",
        ),
    )
    assert check_workflow_policy.check(pinned) == []


def test_dependency_sync_must_be_locked(tmp_path):
    workflow = _write(
        tmp_path,
        "unlocked.yml",
        _basic_workflow(SHA).replace(
            f"- uses: actions/checkout@{SHA}",
            f"- uses: actions/checkout@{SHA}\n      - run: uv sync --dev",
        ),
    )
    assert any(
        "uv sync must include --locked" in error for error in check_workflow_policy.check(workflow)
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


def test_codeql_analyze_requires_only_its_security_events_write(tmp_path):
    rows = """          - language: python
            build-mode: none
          - language: javascript-typescript
            build-mode: none"""
    workflow = _write(
        tmp_path,
        "codeql.yml",
        _codeql_workflow(rows),
    )
    assert check_workflow_policy.check(workflow) == []

    missing = _write(
        tmp_path,
        "missing-codeql.yml",
        workflow.read_text(encoding="utf-8").replace(
            "security-events: write", "security-events: read"
        ),
    )
    assert any(
        "missing required write permission for code-scanning results" in error
        for error in check_workflow_policy.check(missing)
    )


def test_codeql_requires_exact_shipped_language_matrix(tmp_path):
    valid_rows = """          - language: python
            build-mode: none
          - language: javascript-typescript
            build-mode: none"""
    workflow = _write(tmp_path, "codeql.yml", _codeql_workflow(valid_rows))

    assert check_workflow_policy.check(workflow) == []

    invalid_cases = {
        "missing-python": valid_rows.replace(
            "          - language: python\n            build-mode: none\n", ""
        ),
        "missing-javascript": valid_rows.replace(
            "          - language: javascript-typescript\n            build-mode: none", ""
        ),
        "duplicate-language": valid_rows
        + "\n          - language: python\n            build-mode: none",
        "unknown-language": valid_rows.replace("javascript-typescript", "ruby"),
        "wrong-build-mode": valid_rows.replace(
            "language: javascript-typescript\n            build-mode: none",
            "language: javascript-typescript\n            build-mode: manual",
        ),
    }
    for name, rows in invalid_cases.items():
        candidate = _write(tmp_path, "codeql.yml", _codeql_workflow(rows))
        errors = check_workflow_policy.check(candidate)
        assert any("exact shipped-language matrix" in error for error in errors), name


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ("queries: security-and-quality", "queries: security-extended", "security-and-quality"),
        (
            "languages: ${{ matrix.language }}",
            "languages: python",
            "matrix.language",
        ),
        (
            "build-mode: ${{ matrix.build-mode }}",
            "build-mode: none",
            "matrix.build-mode",
        ),
    ],
)
def test_codeql_initialization_must_use_policy_matrix(tmp_path, before, after, expected):
    rows = """          - language: python
            build-mode: none
          - language: javascript-typescript
            build-mode: none"""
    workflow = _write(tmp_path, "codeql.yml", _codeql_workflow(rows).replace(before, after))

    assert any(expected in error for error in check_workflow_policy.check(workflow))


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


def test_rejects_noop_digest_verification_text(tmp_path):
    workflow = _write(
        tmp_path,
        "release.yml",
        _release_workflow().replace(
            "run: cd dist/packages && sha256sum -c ../SHA256SUMS",
            "run: echo sha256sum -c SHA256SUMS",
            1,
        ),
    )
    assert any(
        "publish must verify SHA256SUMS" in error for error in check_workflow_policy.check(workflow)
    )


def test_release_critical_steps_require_default_success_gating(tmp_path):
    nonblocking_verify = _write(
        tmp_path,
        "release.yml",
        _release_workflow().replace(
            "      - run: cd dist/packages && sha256sum -c ../SHA256SUMS",
            "      - continue-on-error: true\n"
            "        run: cd dist/packages && sha256sum -c ../SHA256SUMS",
            1,
        ),
    )
    assert any(
        "publish digest verification step must use default success gating" in error
        for error in check_workflow_policy.check(nonblocking_verify)
    )

    always_publish = _write(
        tmp_path,
        "release.yml",
        _release_workflow().replace(
            f"      - uses: pypa/gh-action-pypi-publish@{SHA}",
            f"      - uses: pypa/gh-action-pypi-publish@{SHA}\n        if: always()",
        ),
    )
    assert any(
        "PyPI publication step must use default success gating" in error
        for error in check_workflow_policy.check(always_publish)
    )


def test_rejects_each_unsafe_release_stage_order(tmp_path):
    cases = {
        "smoke-before-build": (
            "      - name: Build distributions\n"
            "        run: uv build --out-dir dist/packages\n"
            "      - name: Smoke installed artifacts\n"
            "        run: uv run python scripts/package_smoke_check.py dist/packages/",
            "      - name: Smoke installed artifacts\n"
            "        run: uv run python scripts/package_smoke_check.py dist/packages/\n"
            "      - name: Build distributions\n"
            "        run: uv build --out-dir dist/packages",
            "build artifact stages must be ordered",
        ),
        "verify-after-pypi": (
            "      - run: cd dist/packages && sha256sum -c ../SHA256SUMS\n"
            f"      - uses: pypa/gh-action-pypi-publish@{SHA}",
            f"      - uses: pypa/gh-action-pypi-publish@{SHA}\n"
            "      - run: cd dist/packages && sha256sum -c ../SHA256SUMS",
            "publish stages must be ordered",
        ),
        "verify-after-release": (
            "      - run: cd dist/packages && sha256sum -c ../SHA256SUMS\n"
            f"      - uses: softprops/action-gh-release@{SHA}",
            f"      - uses: softprops/action-gh-release@{SHA}\n"
            "      - run: cd dist/packages && sha256sum -c ../SHA256SUMS",
            "github-release stages must be ordered",
        ),
    }
    for name, (before, after, expected) in cases.items():
        workflow = _write(
            tmp_path,
            f"{name}.yml",
            _release_workflow().replace(before, after),
        )
        release_path = tmp_path / "release.yml"
        release_path.write_text(workflow.read_text(encoding="utf-8"), encoding="utf-8")
        assert any(expected in error for error in check_workflow_policy.check(release_path)), name


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
