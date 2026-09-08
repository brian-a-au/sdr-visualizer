"""Tests for the installed-artifact smoke driver."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "package_smoke_check.py"

spec = importlib.util.spec_from_file_location("package_smoke_check", SCRIPT)
package_smoke_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_smoke_check)


def test_discover_artifacts_requires_one_wheel_and_one_sdist(tmp_path):
    with pytest.raises(package_smoke_check.SmokeFailure, match=r"\[artifacts\].*wheel"):
        package_smoke_check.discover_artifacts(tmp_path)

    (tmp_path / "first.whl").touch()
    (tmp_path / "first.tar.gz").touch()
    assert package_smoke_check.discover_artifacts(tmp_path) == [
        tmp_path / "first.whl",
        tmp_path / "first.tar.gz",
    ]

    (tmp_path / "second.whl").touch()
    with pytest.raises(package_smoke_check.SmokeFailure, match=r"\[artifacts\].*exactly one"):
        package_smoke_check.discover_artifacts(tmp_path)


def test_checked_command_failure_names_artifact_and_stage(monkeypatch, tmp_path):
    monkeypatch.setattr(
        package_smoke_check.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 7, "", "missing jinja"),
    )
    with pytest.raises(
        package_smoke_check.SmokeFailure,
        match=r"\[wheel: console --help\].*missing jinja",
    ):
        package_smoke_check.run_checked(
            ["broken-command"],
            label="wheel",
            stage="console --help",
            cwd=tmp_path,
            env={},
        )


def test_smoke_environment_removes_source_import_overrides(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/private/source")
    monkeypatch.setenv("PYTHONHOME", "/private/python")
    env = package_smoke_check.smoke_environment()
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env
    assert env["PYTHONNOUSERSITE"] == "1"


def test_identity_rejects_source_checkout_leakage():
    identity = {
        "metadata_version": "1.0.3",
        "module_version": "1.0.3",
        "module_file": str(REPO / "src" / "sdr_visualizer" / "__init__.py"),
    }
    with pytest.raises(
        package_smoke_check.SmokeFailure,
        match=r"\[wheel: import/version\].*source checkout",
    ):
        package_smoke_check.validate_identity(identity, "wheel", REPO)


def test_render_validation_requires_self_contained_report(tmp_path):
    report = tmp_path / "report.html"
    report.write_text("<html>Minimal Test View</html>", encoding="utf-8")
    with pytest.raises(
        package_smoke_check.SmokeFailure,
        match=r"\[sdist: representative render\].*embedded payload",
    ):
        package_smoke_check.validate_render(report, "sdist")


def test_artifact_metadata_parsers_report_only_direct_runtime_requirements(tmp_path):
    wheel = tmp_path / "sdr_visualizer-1.0.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "sdr_visualizer-1.0.3.dist-info/METADATA",
            "Metadata-Version: 2.4\n"
            "Name: sdr-visualizer\n"
            "Version: 1.0.3\n"
            "Requires-Dist: jinja2>=3.1\n",
        )
    assert package_smoke_check.artifact_metadata(wheel) == ("1.0.3", {"jinja2"})

    project = {
        "project": {
            "name": "sdr-visualizer",
            "version": "1.0.3",
            "dependencies": ["jinja2>=3.1"],
        }
    }
    project_file = tmp_path / "pyproject.toml"
    project_file.write_text(
        '[project]\nname = "sdr-visualizer"\nversion = "1.0.3"\ndependencies = ["jinja2>=3.1"]\n',
        encoding="utf-8",
    )
    sdist = tmp_path / "sdr_visualizer-1.0.3.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        archive.add(project_file, arcname="sdr_visualizer-1.0.3/pyproject.toml")
    assert project["project"]["dependencies"] == ["jinja2>=3.1"]
    assert package_smoke_check.artifact_metadata(sdist) == ("1.0.3", {"jinja2"})


def test_sdist_contents_reject_missing_required_document():
    names = set(package_smoke_check.REQUIRED_SDIST_PATHS)
    names.remove("README.md")

    with pytest.raises(
        package_smoke_check.SmokeFailure,
        match=r"\[sdist: contents\].*README\.md",
    ):
        package_smoke_check._validate_sdist_names(names)


@pytest.mark.parametrize(
    "forbidden",
    [
        "tests/fixtures/cja_snapshot_large.json",
        "SPEC-VISUALIZER.md",
        "docs/plans/private-plan.md",
        "src/sdr_visualizer/__pycache__/module.pyc",
    ],
)
def test_sdist_contents_reject_private_generated_and_cache_paths(forbidden):
    names = {*package_smoke_check.REQUIRED_SDIST_PATHS, forbidden}

    with pytest.raises(
        package_smoke_check.SmokeFailure,
        match=r"\[sdist: contents\].*contains forbidden files",
    ):
        package_smoke_check._validate_sdist_names(names)


def test_project_metadata_keeps_yaml_dev_only_and_ships_referenced_documents():
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["dependencies"] == ["jinja2>=3.1"]
    assert "pyyaml>=6.0" in project["dependency-groups"]["dev"]

    includes = set(project["tool"]["hatch"]["build"]["targets"]["sdist"]["include"])
    assert {
        "docs/*.md",
        "docs/payload-schema.json",
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
    } <= includes
    excludes = set(project["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"])
    assert {
        "tests/fixtures/cja_snapshot_small.json",
        "tests/fixtures/cja_snapshot_medium.json",
        "tests/fixtures/cja_snapshot_large.json",
        "tests/fixtures/cja_snapshot_xl.json",
        "tests/fixtures/aa_snapshot_large.json",
    } <= excludes

    assert {
        "docs/PRODUCT_CONTRACT.md",
        "docs/RELEASING.md",
    } <= package_smoke_check.REQUIRED_SDIST_PATHS


@pytest.mark.parametrize("browser", [False, True])
def test_browser_handoff_uses_installed_cli_outputs_before_cleanup(monkeypatch, tmp_path, browser):
    artifact = tmp_path / "package.whl"
    artifact.touch()
    commands = []
    handed_off = []

    def run(command, *, label, stage, cwd, env):
        assert not cwd.is_relative_to(REPO)
        commands.append((command, stage))
        output = ""
        if stage == "create environment":
            python, console = package_smoke_check._venv_paths(Path(command[-1]))
            console.parent.mkdir(parents=True)
            console.touch()
        elif stage == "import/version":
            output = json.dumps(
                {
                    "metadata_version": "1.1.5",
                    "module_version": "1.1.5",
                    "module_file": str(cwd.parent / "venv/lib/sdr_visualizer/__init__.py"),
                }
            )
        elif stage == "console --help":
            output = "usage: sdr-visualizer"
        elif stage.endswith("render"):
            report = Path(command[command.index("--output") + 1])
            if stage == "representative render":
                html = '<script id="sdr-data" type="application/json">Minimal Test View'
            elif stage == "lineage render":
                html = '<script id="sdr-lineage-data">Synthetic lineage'
            else:
                assert "--trend" in command
                snapshots = sorted(Path(command[1]).glob("*.json"))
                assert len(snapshots) == 2
                assert [len(json.loads(path.read_text())["metrics"]) for path in snapshots] == [
                    1,
                    2,
                ]
                html = "installed trend output"
            report.write_text(html, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, output, "")

    def handoff(catalog, trend, lineage, label):
        assert label == "wheel"
        assert all(path.is_file() for path in (catalog, trend, lineage))
        assert trend.read_text() == "installed trend output"
        handed_off.extend((catalog, trend, lineage))

    monkeypatch.setattr(package_smoke_check, "run_checked", run)
    monkeypatch.setattr(package_smoke_check, "browser_smoke_reports", handoff)
    assert (
        package_smoke_check.smoke_artifact(
            artifact,
            uv_executable="uv",
            browser=browser,
        )
        == "1.1.5"
    )
    assert bool(handed_off) is browser
    assert all(not path.exists() for path in handed_off)
    assert any(stage == "trend render" for _, stage in commands) is browser


def test_requested_browser_failure_is_not_a_skip(monkeypatch, tmp_path):
    class MissingEngine:
        def launch(self):
            raise RuntimeError("engine executable absent")

    class Playwright:
        chromium = MissingEngine()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=Playwright, expect=None),
    )
    with pytest.raises(
        package_smoke_check.SmokeFailure,
        match=r"\[sdist: browser chromium\].*engine executable absent",
    ):
        package_smoke_check.browser_smoke_reports(tmp_path, tmp_path, tmp_path, "sdist")
