"""Smoke-test built wheel and sdist artifacts outside the source checkout.

Each artifact is installed into its own temporary virtual environment by
absolute path. Import/version metadata, the console entry point, ``--help``,
and a representative offline render are then exercised from a separate
temporary working directory with source import overrides removed.

Run after ``uv build``:

    uv run python scripts/package_smoke_check.py dist/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = REPO / "tests" / "fixtures" / "cja_snapshot_minimal.json"
EXPECTED_RUNTIME_DEPENDENCIES = {"jinja2"}
REQUIRED_SDIST_PATHS = {
    "README.md",
    "LICENSE",
    "THIRD_PARTY_LICENSES",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/ADAPTER_GUIDE.md",
    "docs/ARCHITECTURE.md",
    "docs/EMBEDDED_DATA_FORMAT.md",
    "docs/PERFORMANCE.md",
    "docs/payload-schema.json",
}
FORBIDDEN_SDIST_COMPONENTS = {"__pycache__", ".pytest_cache", ".git"}
FORBIDDEN_SDIST_PATHS = {"SPEC-VISUALIZER.md"}
FORBIDDEN_SDIST_PREFIXES = ("docs/plans/", "docs/specs/")
GENERATED_FIXTURES = {
    "cja_snapshot_small.json",
    "cja_snapshot_medium.json",
    "cja_snapshot_large.json",
    "cja_snapshot_xl.json",
    "aa_snapshot_large.json",
}
IDENTITY_CODE = """
import json
from importlib.metadata import version
import sdr_visualizer
print(json.dumps({
    "metadata_version": version("sdr-visualizer"),
    "module_version": sdr_visualizer.__version__,
    "module_file": sdr_visualizer.__file__,
}))
""".strip()


class SmokeFailure(RuntimeError):
    """An artifact smoke stage failed."""


def _fail(label: str, stage: str, message: str) -> SmokeFailure:
    return SmokeFailure(f"[{label}: {stage}] {message}")


def discover_artifacts(dist_dir: Path) -> list[Path]:
    """Return exactly one wheel and one sdist from *dist_dir*."""
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1:
        raise SmokeFailure(
            f"[artifacts] expected exactly one wheel in {dist_dir}, found {len(wheels)}"
        )
    if len(sdists) != 1:
        raise SmokeFailure(
            f"[artifacts] expected exactly one sdist in {dist_dir}, found {len(sdists)}"
        )
    return [wheels[0], sdists[0]]


def smoke_environment() -> dict[str, str]:
    """Return a subprocess environment that cannot import from the checkout."""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONNOUSERSITE"] = "1"
    return env


def run_checked(
    command: list[str],
    *,
    label: str,
    stage: str,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    """Run one smoke stage and attach an actionable label to failures."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise _fail(label, stage, str(exc)) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "command failed with no output").strip()
        raise _fail(label, stage, f"exit {result.returncode}: {detail}")
    return result


def _requirement_name(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9_.-]*", requirement.strip())
    if not match:
        return requirement.strip().lower()
    return re.sub(r"[-_.]+", "-", match.group(0)).lower()


def _wheel_metadata(artifact: Path) -> tuple[str, set[str]]:
    with zipfile.ZipFile(artifact) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise _fail("wheel", "metadata", f"expected one METADATA file, found {len(names)}")
        metadata = Parser().parsestr(archive.read(names[0]).decode("utf-8"))
    return metadata["Version"], {
        _requirement_name(value) for value in metadata.get_all("Requires-Dist", [])
    }


def _sdist_project(artifact: Path) -> tuple[dict[str, Any], set[str]]:
    with tarfile.open(artifact, "r:gz") as archive:
        members = [
            member for member in archive.getmembers() if member.name.endswith("/pyproject.toml")
        ]
        if len(members) != 1:
            raise _fail("sdist", "metadata", f"expected one pyproject.toml, found {len(members)}")
        stream = archive.extractfile(members[0])
        if stream is None:
            raise _fail("sdist", "metadata", "could not read pyproject.toml")
        project_file = tomllib.loads(stream.read().decode("utf-8"))
        names = {
            member.name.split("/", 1)[1] for member in archive.getmembers() if "/" in member.name
        }
    return project_file["project"], names


def artifact_metadata(artifact: Path) -> tuple[str, set[str]]:
    """Return artifact version and canonical direct runtime dependency names."""
    if artifact.suffix == ".whl":
        return _wheel_metadata(artifact)
    project, _ = _sdist_project(artifact)
    return str(project["version"]), {
        _requirement_name(requirement) for requirement in project.get("dependencies", [])
    }


def validate_sdist_contents(artifact: Path) -> None:
    """Assert that shipped docs exist and private/generated material does not."""
    _, names = _sdist_project(artifact)
    missing = sorted(REQUIRED_SDIST_PATHS - names)
    if missing:
        raise _fail("sdist", "contents", f"missing shipped files: {', '.join(missing)}")
    forbidden = sorted(
        name
        for name in names
        if Path(name).name in GENERATED_FIXTURES
        or name in FORBIDDEN_SDIST_PATHS
        or name.startswith(FORBIDDEN_SDIST_PREFIXES)
        or any(part in FORBIDDEN_SDIST_COMPONENTS for part in Path(name).parts)
    )
    if forbidden:
        raise _fail("sdist", "contents", f"contains forbidden files: {', '.join(forbidden)}")


def validate_identity(identity: dict[str, Any], label: str, repo_root: Path) -> str:
    """Validate installed versions and prove import did not resolve to source."""
    metadata_version = identity.get("metadata_version")
    module_version = identity.get("module_version")
    if not metadata_version or metadata_version != module_version:
        raise _fail(
            label,
            "import/version",
            f"metadata version {metadata_version!r} != module version {module_version!r}",
        )
    module_file = Path(str(identity.get("module_file", ""))).resolve()
    if module_file.is_relative_to(repo_root.resolve()):
        raise _fail(label, "import/version", f"module imported from source checkout: {module_file}")
    return str(metadata_version)


def validate_render(report: Path, label: str) -> None:
    """Validate the representative installed-CLI output."""
    if not report.is_file():
        raise _fail(label, "representative render", f"output was not created: {report}")
    html = report.read_text(encoding="utf-8")
    if '<script id="sdr-data" type="application/json">' not in html:
        raise _fail(label, "representative render", "output has no embedded payload")
    if "Minimal Test View" not in html:
        raise _fail(label, "representative render", "fixture content is absent from output")


def _venv_paths(venv: Path) -> tuple[Path, Path]:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe", venv / "Scripts" / "sdr-visualizer.exe"
    return venv / "bin" / "python", venv / "bin" / "sdr-visualizer"


def smoke_artifact(
    artifact: Path,
    *,
    fixture: Path = DEFAULT_FIXTURE,
    repo_root: Path = REPO,
    uv_executable: str | None = None,
) -> str:
    """Install and smoke one artifact; return its installed version."""
    artifact = artifact.resolve()
    fixture = fixture.resolve()
    label = "wheel" if artifact.suffix == ".whl" else "sdist"
    uv_command = uv_executable or shutil.which("uv")
    if not uv_command:
        raise _fail(label, "environment", "uv executable not found")
    if not fixture.is_file():
        raise _fail(label, "fixture", f"fixture not found: {fixture}")

    with tempfile.TemporaryDirectory(prefix=f"sdr-visualizer-{label}-") as temp:
        root = Path(temp)
        venv = root / "venv"
        work = root / "work"
        work.mkdir()
        copied_fixture = work / "snapshot.json"
        shutil.copy2(fixture, copied_fixture)
        env = smoke_environment()

        run_checked(
            [uv_command, "venv", "--python", sys.executable, str(venv)],
            label=label,
            stage="create environment",
            cwd=work,
            env=env,
        )
        python, console = _venv_paths(venv)
        run_checked(
            [uv_command, "pip", "install", "--python", str(python), str(artifact)],
            label=label,
            stage="install",
            cwd=work,
            env=env,
        )
        identity_result = run_checked(
            [str(python), "-c", IDENTITY_CODE],
            label=label,
            stage="import/version",
            cwd=work,
            env=env,
        )
        try:
            identity = json.loads(identity_result.stdout)
        except json.JSONDecodeError as exc:
            raise _fail(label, "import/version", f"invalid identity output: {exc}") from exc
        version = validate_identity(identity, label, repo_root)

        if not console.is_file():
            raise _fail(label, "console --help", f"console entry point not found: {console}")
        help_result = run_checked(
            [str(console), "--help"],
            label=label,
            stage="console --help",
            cwd=work,
            env=env,
        )
        if "usage: sdr-visualizer" not in help_result.stdout:
            raise _fail(label, "console --help", "usage banner is absent")

        report = work / "report.html"
        run_checked(
            [
                str(console),
                str(copied_fixture),
                "--output",
                str(report),
                "--quiet",
            ],
            label=label,
            stage="representative render",
            cwd=work,
            env=env,
        )
        validate_render(report, label)
        return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path, help="Directory containing one wheel and one sdist")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="Representative CJA fixture copied outside the checkout",
    )
    args = parser.parse_args()
    try:
        artifacts = discover_artifacts(args.dist.resolve())
        versions = []
        for artifact in artifacts:
            label = "wheel" if artifact.suffix == ".whl" else "sdist"
            version, dependencies = artifact_metadata(artifact)
            if dependencies != EXPECTED_RUNTIME_DEPENDENCIES:
                raise _fail(
                    label,
                    "metadata",
                    f"runtime dependencies {sorted(dependencies)!r} != "
                    f"{sorted(EXPECTED_RUNTIME_DEPENDENCIES)!r}",
                )
            if label == "sdist":
                validate_sdist_contents(artifact)
            installed_version = smoke_artifact(artifact, fixture=args.fixture)
            if installed_version != version:
                raise _fail(
                    label,
                    "import/version",
                    f"installed version {installed_version!r} != artifact version {version!r}",
                )
            versions.append(installed_version)
            print(f"OK: {label} {installed_version}")
        if len(set(versions)) != 1:
            raise SmokeFailure(f"[artifacts] wheel/sdist versions differ: {versions!r}")
    except SmokeFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("OK: installed artifact smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
