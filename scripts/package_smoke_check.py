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
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/ADAPTER_GUIDE.md",
    "docs/ARCHITECTURE.md",
    "docs/EMBEDDED_DATA_FORMAT.md",
    "docs/PERFORMANCE.md",
    "docs/PRODUCT_CONTRACT.md",
    "docs/RELEASING.md",
    "docs/LINEAGE.md",
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
        all_members = archive.getmembers()
        members = [member for member in all_members if member.name.endswith("/pyproject.toml")]
        if len(members) != 1:
            raise _fail("sdist", "metadata", f"expected one pyproject.toml, found {len(members)}")
        stream = archive.extractfile(members[0])
        if stream is None:
            raise _fail("sdist", "metadata", "could not read pyproject.toml")
        project_file = tomllib.loads(stream.read().decode("utf-8"))
        names = {member.name.split("/", 1)[1] for member in all_members if "/" in member.name}
    return project_file["project"], names


def _sdist_inspection(artifact: Path) -> tuple[str, set[str], set[str]]:
    project, names = _sdist_project(artifact)
    dependencies = {
        _requirement_name(requirement) for requirement in project.get("dependencies", [])
    }
    return str(project["version"]), dependencies, names


def artifact_metadata(artifact: Path) -> tuple[str, set[str]]:
    """Return artifact version and canonical direct runtime dependency names."""
    if artifact.suffix == ".whl":
        return _wheel_metadata(artifact)
    version, dependencies, _ = _sdist_inspection(artifact)
    return version, dependencies


def _validate_sdist_names(names: set[str]) -> None:
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


def validate_sdist_contents(artifact: Path) -> None:
    """Assert that shipped docs exist and private/generated material does not."""
    _, _, names = _sdist_inspection(artifact)
    _validate_sdist_names(names)


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


def write_trend_series(work: Path) -> Path:
    """Create synthetic CLI inputs without importing the source package."""
    series = work / "trend-series"
    series.mkdir()
    for index, ids in enumerate((["metrics/one"], ["metrics/one", "metrics/two"])):
        snapshot = {
            "metadata": {"Data View ID": "dv-trend", "Data View Name": "Synthetic trend"},
            "data_view": {"id": "dv-trend"},
            "metrics": [{"id": item, "name": item, "description": "Synthetic"} for item in ids],
            "dimensions": [],
            "segments": {"segments": []},
            "calculated_metrics": {"metrics": []},
        }
        (series / f"snapshot-{index}.json").write_text(json.dumps(snapshot), encoding="utf-8")
    return series


def browser_smoke_reports(catalog: Path, trend: Path, lineage: Path, label: str) -> None:
    """Execute installed output offline; both engines are mandatory when requested."""
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError as exc:
        raise _fail(
            label, "browser", "install the development browser group and both engines"
        ) from exc

    with sync_playwright() as playwright:
        for engine in ("chromium", "webkit"):
            try:
                browser = getattr(playwright, engine).launch()
                try:
                    context = browser.new_context()
                    # WebKit cannot navigate file:// with offline=True. Block network
                    # access explicitly while retaining request/error assertions below.
                    context.route(re.compile(r"^https?://"), lambda route: route.abort())
                    page = context.new_page()
                    errors: list[str] = []
                    requests: list[str] = []
                    page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda message, errors=errors: (
                            errors.append(message.text) if message.type == "error" else None
                        ),
                    )
                    page.on(
                        "request",
                        lambda request, requests=requests: (
                            requests.append(request.url)
                            if not request.is_navigation_request()
                            else None
                        ),
                    )
                    page.goto(catalog.as_uri())
                    expect(page.locator('.view-button[data-view="catalog"]')).to_be_visible()
                    expect(page.locator('.view-button[data-view="trend"]')).to_have_count(0)

                    page.goto(trend.as_uri())
                    intervals = page.locator("#trend-log details.trend-interval")
                    expect(intervals).to_have_count(0)
                    page.locator('.view-button[data-view="trend"]').click()
                    expect(intervals).to_have_count(1)
                    expect(page.locator("#trend-log .trend-id")).to_have_count(0)
                    intervals.locator("summary").click()
                    expect(intervals.locator(".trend-id")).to_have_text(["metrics/two"])
                    page.locator('.view-button[data-view="catalog"]').click()
                    page.locator('.view-button[data-view="trend"]').click()
                    expect(intervals).to_have_count(1)
                    expect(intervals.locator(".trend-id")).to_have_count(1)
                    page.goto(trend.as_uri() + "#view=trend")
                    page.reload()
                    expect(page.locator("#trend-view")).to_be_visible()
                    expect(intervals).to_have_count(1)

                    page.goto(lineage.as_uri())
                    page.locator('[data-connection-id="conn-smoke"]').click()
                    inspector = page.locator("#lineage-connection-inspector")
                    expect(inspector).to_be_visible()
                    inspector.locator('[data-data-view-id="dv-smoke"]').click()
                    page.locator("#lineage-back-connection").click()
                    expect(inspector).to_be_visible()
                    expect(page.locator("#lineage-connection-inspector-heading")).to_be_focused()
                    if errors or requests:
                        raise _fail(
                            label,
                            f"browser {engine}",
                            f"errors={errors!r}; subresource requests={requests!r}",
                        )
                finally:
                    browser.close()
            except SmokeFailure:
                raise
            except Exception as exc:
                raise _fail(label, f"browser {engine}", str(exc)) from exc
            print(f"OK: {label} {engine} installed catalog, Trend, and lineage reports (offline)")


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
    browser: bool = False,
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

        lineage_console = console.with_name("cja-lineage.exe" if os.name == "nt" else "cja-lineage")
        run_checked(
            [str(lineage_console), "--help"], label=label, stage="lineage --help", cwd=work, env=env
        )
        lineage_fixture = work / "discovery.json"
        lineage_fixture.write_text(
            json.dumps(
                {
                    "dataViews": [
                        {
                            "id": "dv-smoke",
                            "name": "Synthetic lineage",
                            "connection": {"id": "conn-smoke", "name": "Synthetic connection"},
                            "datasets": [{"id": "ds-smoke", "name": "Synthetic dataset"}],
                        }
                    ],
                    "count": 1,
                }
            ),
            encoding="utf-8",
        )
        lineage_report = work / "lineage.html"
        run_checked(
            [
                str(lineage_console),
                "--saved",
                str(lineage_fixture),
                "--output",
                str(lineage_report),
                "--quiet",
            ],
            label=label,
            stage="lineage render",
            cwd=work,
            env=env,
        )
        lineage_html = lineage_report.read_text(encoding="utf-8")
        if 'id="sdr-lineage-data"' not in lineage_html or "Synthetic lineage" not in lineage_html:
            raise _fail(label, "lineage render", "embedded lineage payload or fixture is absent")
        if browser:
            series = write_trend_series(work)
            trend_report = work / "trend.html"
            run_checked(
                [str(console), str(series), "--trend", "--output", str(trend_report), "--quiet"],
                label=label,
                stage="trend render",
                cwd=work,
                env=env,
            )
            browser_smoke_reports(report, trend_report, lineage_report, label)
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
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Require Chromium and WebKit to exercise installed reports offline",
    )
    args = parser.parse_args()
    try:
        artifacts = discover_artifacts(args.dist.resolve())
        versions = []
        for artifact in artifacts:
            label = "wheel" if artifact.suffix == ".whl" else "sdist"
            if label == "sdist":
                version, dependencies, names = _sdist_inspection(artifact)
            else:
                version, dependencies = artifact_metadata(artifact)
                names = None
            if dependencies != EXPECTED_RUNTIME_DEPENDENCIES:
                raise _fail(
                    label,
                    "metadata",
                    f"runtime dependencies {sorted(dependencies)!r} != "
                    f"{sorted(EXPECTED_RUNTIME_DEPENDENCIES)!r}",
                )
            if names is not None:
                _validate_sdist_names(names)
            installed_version = smoke_artifact(artifact, fixture=args.fixture, browser=args.browser)
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
