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
DOCKER_DIGEST_RE = re.compile(r"^docker://.+@sha256:[0-9a-fA-F]{64}$")
WRITE_CAPABILITIES = {
    "contents": "repository contents",
    "pages": "GitHub Pages",
    "id-token": "OIDC identity token",
    "security-events": "code-scanning results",
}
EXPECTED_CODEQL_MATRIX = {
    ("python", "none"),
    ("javascript-typescript", "none"),
}
EXPECTED_CODEQL_CONFIG_FILE = "./.github/codeql/codeql-config.yml"
EXPECTED_CODEQL_IGNORES = ["examples/**"]


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
            if uses.startswith("docker://"):
                if not DOCKER_DIGEST_RE.fullmatch(uses):
                    errors.append(
                        _error(
                            path,
                            f"job {job_name!r} Docker action must use an immutable "
                            f"sha256 digest, got {uses!r}",
                        )
                    )
                continue
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


def _run_is(step: dict[str, Any], command: str) -> bool:
    return str(step.get("run", "")).strip() == command


def _uses_default_success_gating(item: dict[str, Any]) -> bool:
    return item.get("if") is None and item.get("continue-on-error") in {None, False}


def _require_default_success(
    errors: list[str],
    *,
    path: Path,
    label: str,
    item: dict[str, Any],
) -> None:
    if not _uses_default_success_gating(item):
        errors.append(_error(path, f"{label} must use default success gating"))


def _lock_errors(path: Path, workflow: dict[str, Any]) -> list[str]:
    errors = []
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return errors
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in _steps(job):
            for line in str(step.get("run", "")).splitlines():
                command = line.strip()
                if re.match(r"^uv\s+sync(?:\s|$)", command) and not re.search(
                    r"(?:^|\s)--locked(?:\s|$)", command
                ):
                    errors.append(_error(path, f"job {job_name!r} uv sync must include --locked"))
    return errors


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
    if not all(isinstance(job, dict) for job in (build, publish, github_release)):
        return [*errors, _error(path, "release jobs must be mappings")]
    if "build" not in _needs(publish):
        errors.append(_error(path, "publish must need build"))
    if "publish" not in _needs(github_release):
        errors.append(_error(path, "github-release must need publish"))
    for job_name, job in jobs.items():
        if isinstance(job, dict):
            _require_default_success(
                errors,
                path=path,
                label=f"job {job_name!r}",
                item=job,
            )

    build_distribution = _step_index(
        build, lambda step: _run_is(step, "uv build --out-dir dist/packages")
    )
    smoke = _step_index(
        build,
        lambda step: _run_is(
            step,
            "uv run python scripts/package_smoke_check.py dist/packages/",
        ),
    )
    checksum = _step_index(
        build,
        lambda step: _run_is(
            step,
            "cd dist/packages && sha256sum *.whl *.tar.gz > ../SHA256SUMS",
        ),
    )
    upload = _step_index(build, lambda step: _uses_action(step, "actions/upload-artifact"))
    if None in {build_distribution, smoke, checksum, upload}:
        errors.append(_error(path, "build must build, smoke, checksum, then upload distributions"))
    elif not (build_distribution < smoke < checksum < upload):
        errors.append(
            _error(path, "build artifact stages must be ordered build -> smoke -> digest -> upload")
        )
    elif "SHA256SUMS" not in str(_steps(build)[upload].get("with", {}).get("path", "")):
        errors.append(_error(path, "build artifact upload must include SHA256SUMS"))
    for label, index in (
        ("build distribution step", build_distribution),
        ("installed-artifact smoke step", smoke),
        ("digest generation step", checksum),
        ("artifact upload step", upload),
    ):
        if index is not None:
            _require_default_success(
                errors,
                path=path,
                label=label,
                item=_steps(build)[index],
            )

    publish_fetch = _step_index(
        publish, lambda step: _uses_action(step, "actions/download-artifact")
    )
    publish_verify = _step_index(
        publish,
        lambda step: _run_is(
            step,
            "cd dist/packages && sha256sum -c ../SHA256SUMS",
        ),
    )
    pypi = _step_index(publish, lambda step: _uses_action(step, "pypa/gh-action-pypi-publish"))
    if publish_verify is None:
        errors.append(_error(path, "publish must verify SHA256SUMS"))
    if publish_fetch is None:
        errors.append(_error(path, "publish must fetch verified distributions"))
    if pypi is None:
        errors.append(_error(path, "publish must invoke pypa/gh-action-pypi-publish"))
    if None not in {publish_fetch, publish_verify, pypi} and not (
        publish_fetch < publish_verify < pypi
    ):
        errors.append(_error(path, "publish stages must be ordered fetch -> verify -> PyPI"))
    if pypi is not None:
        packages_dir = str(_steps(publish)[pypi].get("with", {}).get("packages-dir", ""))
        if packages_dir.rstrip("/") != "dist/packages":
            errors.append(_error(path, "PyPI packages-dir must exclude the SHA256SUMS manifest"))
    for label, index in (
        ("publish artifact fetch step", publish_fetch),
        ("publish digest verification step", publish_verify),
        ("PyPI publication step", pypi),
    ):
        if index is not None:
            _require_default_success(
                errors,
                path=path,
                label=label,
                item=_steps(publish)[index],
            )

    release_fetch = _step_index(
        github_release, lambda step: _uses_action(step, "actions/download-artifact")
    )
    release_verify = _step_index(
        github_release,
        lambda step: _run_is(
            step,
            "cd dist/packages && sha256sum -c ../SHA256SUMS",
        ),
    )
    release_action = _step_index(
        github_release, lambda step: _uses_action(step, "softprops/action-gh-release")
    )
    if release_verify is None:
        errors.append(_error(path, "github-release must verify SHA256SUMS"))
    if release_fetch is None:
        errors.append(_error(path, "github-release must fetch verified distributions"))
    if release_action is None:
        errors.append(_error(path, "github-release must invoke softprops/action-gh-release"))
    if None not in {release_fetch, release_verify, release_action} and not (
        release_fetch < release_verify < release_action
    ):
        errors.append(
            _error(path, "github-release stages must be ordered fetch -> verify -> release")
        )
    if release_action is not None:
        files = str(_steps(github_release)[release_action].get("with", {}).get("files", ""))
        if "SHA256SUMS" not in files:
            errors.append(_error(path, "GitHub release files must include SHA256SUMS"))
    for label, index in (
        ("release artifact fetch step", release_fetch),
        ("release digest verification step", release_verify),
        ("GitHub release step", release_action),
    ):
        if index is not None:
            _require_default_success(
                errors,
                path=path,
                label=label,
                item=_steps(github_release)[index],
            )

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


def _codeql_errors(path: Path, workflow: dict[str, Any]) -> list[str]:
    if path.name not in {"codeql.yml", "codeql.yaml"}:
        return []
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return [_error(path, "CodeQL jobs must be a mapping")]
    analyze = jobs.get("analyze")
    if not isinstance(analyze, dict):
        return [_error(path, "CodeQL workflow must define an 'analyze' job")]

    strategy = analyze.get("strategy")
    if not isinstance(strategy, dict):
        return [_error(path, "CodeQL analyze job strategy must be a mapping")]
    matrix = strategy.get("matrix")
    include = matrix.get("include") if isinstance(matrix, dict) else None
    if not isinstance(include, list):
        return [
            _error(
                path,
                "CodeQL must use the exact shipped-language matrix: "
                "python/none and javascript-typescript/none",
            )
        ]
    rows: list[tuple[Any, Any]] = [
        (row.get("language"), row.get("build-mode")) for row in include if isinstance(row, dict)
    ]
    if (
        len(rows) != len(EXPECTED_CODEQL_MATRIX)
        or len(rows) != len(include)
        or set(rows) != EXPECTED_CODEQL_MATRIX
    ):
        return [
            _error(
                path,
                "CodeQL must use the exact shipped-language matrix: "
                "python/none and javascript-typescript/none",
            )
        ]

    steps = analyze.get("steps")
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        return [_error(path, "CodeQL analyze job steps must be a list of mappings")]

    init_steps = [step for step in steps if _uses_action(step, "github/codeql-action/init")]
    if len(init_steps) != 1:
        return [_error(path, "CodeQL analyze job must have exactly one initialization step")]
    init_with = init_steps[0].get("with")
    if not isinstance(init_with, dict):
        return [_error(path, "CodeQL initialization must declare matrix inputs")]

    errors = []
    if init_with.get("languages") != "${{ matrix.language }}":
        errors.append(_error(path, "CodeQL languages must use matrix.language"))
    if init_with.get("build-mode") != "${{ matrix.build-mode }}":
        errors.append(_error(path, "CodeQL build-mode must use matrix.build-mode"))
    if init_with.get("queries") != "security-and-quality":
        errors.append(_error(path, "CodeQL queries must include security-and-quality"))
    if init_with.get("config-file") != EXPECTED_CODEQL_CONFIG_FILE:
        errors.append(_error(path, "CodeQL must use the repository's narrow analysis config"))

    analysis_steps = [step for step in steps if _uses_action(step, "github/codeql-action/analyze")]
    if len(analysis_steps) != 1:
        errors.append(_error(path, "CodeQL analyze job must have exactly one analysis step"))
        return errors
    if steps.index(analysis_steps[0]) <= steps.index(init_steps[0]):
        errors.append(_error(path, "CodeQL analysis step must run after initialization"))
    _require_default_success(
        errors,
        path=path,
        label="CodeQL analysis step",
        item=analysis_steps[0],
    )
    return errors


def _codeql_config_errors(repo: Path) -> list[str]:
    path = repo / EXPECTED_CODEQL_CONFIG_FILE.removeprefix("./")
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [_error(path, f"could not parse CodeQL config: {exc}")]
    if not isinstance(config, dict):
        return [_error(path, "CodeQL config root must be a mapping")]

    errors = []
    unexpected = sorted(set(config) - {"name", "paths-ignore"})
    if unexpected:
        errors.append(
            _error(
                path,
                "CodeQL config may only name the config and exclude generated examples; "
                f"unexpected keys: {', '.join(unexpected)}",
            )
        )
    if config.get("paths-ignore") != EXPECTED_CODEQL_IGNORES:
        errors.append(
            _error(
                path,
                "CodeQL config must exclude exactly the generated examples path",
            )
        )
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
        *_lock_errors(path, workflow),
        *_release_errors(path, workflow),
        *_examples_errors(path, workflow),
        *_codeql_errors(path, workflow),
    ]


def check_repository(repo: Path) -> list[str]:
    """Return policy violations for every repository workflow."""
    workflow_dir = repo / ".github" / "workflows"
    paths = sorted([*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")])
    errors = [error for path in paths for error in check(path)]
    codeql_paths = [path for path in paths if path.name in {"codeql.yml", "codeql.yaml"}]
    if len(codeql_paths) != 1:
        errors.append(
            _error(
                workflow_dir / "codeql.yml",
                "repository must define exactly one CodeQL workflow named "
                "codeql.yml or codeql.yaml",
            )
        )
    errors.extend(_codeql_config_errors(repo))
    return errors


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
