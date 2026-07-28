"""Validate immutable GitHub Actions pins, permissions, and release ordering.

Run locally with:

    uv run python scripts/check_workflow_policy.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
WRITE_CAPABILITIES = {
    "contents": "repository contents",
    "pages": "GitHub Pages",
    "id-token": "OIDC identity token",
    "security-events": "code-scanning results",
}


def _error(path: Path, message: str) -> str:
    return f"{path.name}: {message}"


def _remote_action(uses: str) -> tuple[str, str] | None:
    if uses.startswith("./") or uses.startswith("docker://"):
        return None
    if "@" not in uses:
        return uses, ""
    action, ref = uses.rsplit("@", 1)
    return action.lower(), ref


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps", [])
    return [step for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []


def _job_actions(job: dict[str, Any]) -> list[str]:
    actions = []
    reusable = job.get("uses")
    if isinstance(reusable, str):
        actions.append(reusable)
    for step in _steps(job):
        uses = step.get("uses")
        if isinstance(uses, str):
            actions.append(uses)
    return actions


def _job_run(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in _steps(job))


def _required_write_permissions(job: dict[str, Any]) -> set[str]:
    actions = [(_remote_action(uses) or ("", ""))[0] for uses in _job_actions(job)]
    run = _job_run(job)
    required = set()
    if any(action == "softprops/action-gh-release" for action in actions) or re.search(
        r"(?m)^\s*git\s+push(?:\s|$)", run
    ):
        required.add("contents")
    if any(action == "actions/deploy-pages" for action in actions):
        required.update({"pages", "id-token"})
    if any(action == "pypa/gh-action-pypi-publish" for action in actions):
        required.add("id-token")
    if any(action == "github/codeql-action/analyze" for action in actions):
        required.add("security-events")
    return required


def _permission_errors(path: Path, workflow: dict[str, Any]) -> list[str]:
    errors = []
    top_permissions = workflow.get("permissions")
    if top_permissions == "write-all":
        errors.append(_error(path, "top-level write permission 'write-all' is forbidden"))
    if isinstance(top_permissions, dict):
        for permission, value in top_permissions.items():
            if value == "write":
                errors.append(
                    _error(path, f"top-level write permission {permission!r} is forbidden")
                )

    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return [*errors, _error(path, "jobs must be a mapping")]
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            errors.append(_error(path, f"job {job_name!r} must be a mapping"))
            continue
        permissions = job.get("permissions")
        if not isinstance(permissions, dict):
            errors.append(_error(path, f"job {job_name!r} must declare mapping permissions"))
            continue
        actual_writes = {key for key, value in permissions.items() if value == "write"}
        required_writes = _required_write_permissions(job)
        for permission in sorted(actual_writes - required_writes):
            label = WRITE_CAPABILITIES.get(permission, permission)
            errors.append(
                _error(path, f"job {job_name!r} has unneeded write permission for {label}")
            )
        for permission in sorted(required_writes - actual_writes):
            label = WRITE_CAPABILITIES.get(permission, permission)
            errors.append(
                _error(path, f"job {job_name!r} is missing required write permission for {label}")
            )
    return errors


def _action_errors(path: Path, workflow: dict[str, Any]) -> list[str]:
    errors = []
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return errors
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for uses in _job_actions(job):
            remote = _remote_action(uses)
            if remote is None:
                continue
            action, ref = remote
            if not SHA_RE.fullmatch(ref):
                errors.append(
                    _error(
                        path,
                        f"job {job_name!r} action {action!r} must use an immutable "
                        f"40-character SHA, got {ref!r}",
                    )
                )
    return errors


def _needs(job: dict[str, Any]) -> set[str]:
    value = job.get("needs", [])
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    return set()


def _step_index(job: dict[str, Any], predicate) -> int | None:
    for index, step in enumerate(_steps(job)):
        if predicate(step):
            return index
    return None


def _uses_action(step: dict[str, Any], action: str) -> bool:
    uses = step.get("uses")
    if not isinstance(uses, str):
        return False
    remote = _remote_action(uses)
    return remote is not None and remote[0] == action


def _run_contains(step: dict[str, Any], *needles: str) -> bool:
    run = str(step.get("run", ""))
    return all(needle in run for needle in needles)


def _release_errors(path: Path, workflow: dict[str, Any]) -> list[str]:
    if path.name not in {"release.yml", "release.yaml"}:
        return []
    errors = []
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return [_error(path, "release jobs must be a mapping")]
    required_jobs = {"build", "publish", "github-release"}
    missing_jobs = sorted(required_jobs - jobs.keys())
    if missing_jobs:
        return [_error(path, f"release workflow is missing jobs: {', '.join(missing_jobs)}")]
    build = jobs["build"]
    publish = jobs["publish"]
    github_release = jobs["github-release"]
    if "build" not in _needs(publish):
        errors.append(_error(path, "publish must need build"))
    if "publish" not in _needs(github_release):
        errors.append(_error(path, "github-release must need publish"))
    if github_release.get("if") is not None:
        errors.append(_error(path, "github-release must use default success gating after publish"))
    if publish.get("continue-on-error") not in {None, False}:
        errors.append(_error(path, "publish must not continue on PyPI errors"))

    build_distribution = _step_index(build, lambda step: _run_contains(step, "uv build"))
    smoke = _step_index(build, lambda step: _run_contains(step, "package_smoke_check.py"))
    checksum = _step_index(build, lambda step: _run_contains(step, "sha256sum", "SHA256SUMS"))
    upload = _step_index(build, lambda step: _uses_action(step, "actions/upload-artifact"))
    if None in {build_distribution, smoke, checksum, upload}:
        errors.append(_error(path, "build must build, smoke, checksum, then upload distributions"))
    elif not (build_distribution < smoke < checksum < upload):
        errors.append(
            _error(path, "build artifact stages must be ordered build -> smoke -> digest -> upload")
        )
    elif "SHA256SUMS" not in str(_steps(build)[upload].get("with", {}).get("path", "")):
        errors.append(_error(path, "build artifact upload must include SHA256SUMS"))

    publish_verify = _step_index(
        publish, lambda step: _run_contains(step, "sha256sum", "-c", "SHA256SUMS")
    )
    pypi = _step_index(publish, lambda step: _uses_action(step, "pypa/gh-action-pypi-publish"))
    if publish_verify is None:
        errors.append(_error(path, "publish must verify SHA256SUMS"))
    if pypi is None:
        errors.append(_error(path, "publish must invoke pypa/gh-action-pypi-publish"))
    elif _steps(publish)[pypi].get("continue-on-error") not in {None, False}:
        errors.append(_error(path, "PyPI publication step must fail the publish job"))
    if publish_verify is not None and pypi is not None and publish_verify > pypi:
        errors.append(_error(path, "publish must verify SHA256SUMS before PyPI"))
    if pypi is not None:
        packages_dir = str(_steps(publish)[pypi].get("with", {}).get("packages-dir", ""))
        if packages_dir.rstrip("/") != "dist/packages":
            errors.append(_error(path, "PyPI packages-dir must exclude the SHA256SUMS manifest"))

    release_verify = _step_index(
        github_release, lambda step: _run_contains(step, "sha256sum", "-c", "SHA256SUMS")
    )
    release_action = _step_index(
        github_release, lambda step: _uses_action(step, "softprops/action-gh-release")
    )
    if release_verify is None:
        errors.append(_error(path, "github-release must verify SHA256SUMS"))
    if release_action is None:
        errors.append(_error(path, "github-release must invoke softprops/action-gh-release"))
    if (
        release_verify is not None
        and release_action is not None
        and release_verify > release_action
    ):
        errors.append(_error(path, "github-release must verify SHA256SUMS before release"))
    if release_action is not None:
        files = str(_steps(github_release)[release_action].get("with", {}).get("files", ""))
        if "SHA256SUMS" not in files:
            errors.append(_error(path, "GitHub release files must include SHA256SUMS"))

    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in _steps(job):
            if _uses_action(step, "pypa/gh-action-pypi-publish") and job_name != "publish":
                errors.append(_error(path, "PyPI publication is allowed only in publish"))
            if _uses_action(step, "softprops/action-gh-release") and job_name != "github-release":
                errors.append(_error(path, "GitHub release creation is allowed only after publish"))
    return errors


def _examples_errors(path: Path, workflow: dict[str, Any]) -> list[str]:
    if path.name not in {"examples.yml", "examples.yaml"}:
        return []
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return [_error(path, "examples jobs must be a mapping")]
    run = "\n".join(_job_run(job) for job in jobs.values() if isinstance(job, dict))
    errors = []
    if re.search(r"(?m)^\s*git\s+push(?:\s|$)", run):
        errors.append(_error(path, "examples workflow must not push directly to main"))
    if "generate_examples.py" not in run or not all(
        token in run for token in ("git diff", "--exit-code", "examples/")
    ):
        errors.append(_error(path, "examples workflow must regenerate and fail on tracked drift"))
    return errors


def check(path: Path) -> list[str]:
    """Return policy violations for one workflow path."""
    try:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [_error(path, f"could not parse workflow: {exc}")]
    if not isinstance(workflow, dict):
        return [_error(path, "workflow root must be a mapping")]
    return [
        *_action_errors(path, workflow),
        *_permission_errors(path, workflow),
        *_release_errors(path, workflow),
        *_examples_errors(path, workflow),
    ]


def check_repository(repo: Path) -> list[str]:
    """Return policy violations for every repository workflow."""
    workflow_dir = repo / ".github" / "workflows"
    paths = sorted([*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")])
    return [error for path in paths for error in check(path)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "repo",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repository root (defaults to this checkout)",
    )
    args = parser.parse_args()
    errors = check_repository(args.repo.resolve())
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("OK: workflow policy passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
