"""Tests for the installed-artifact smoke driver."""

from __future__ import annotations

import importlib.util
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

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
