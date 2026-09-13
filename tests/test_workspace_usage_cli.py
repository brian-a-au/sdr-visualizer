"""One-command Workspace augmentation using only synthetic offline acquisition."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import extract_payload
from test_workspace_usage_collection import synthetic_project

from sdr_visualizer.cli.main import main
from sdr_visualizer.usage import collector


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    for key in ("ORG_ID", "CLIENT_ID", "SECRET", "SCOPES"):
        monkeypatch.delenv(key, raising=False)


def acquisition(failed=False):
    return {
        "projects": [] if failed else [synthetic_project(component="variables/evar1")],
        "checked_at": "2026-09-12T12:00:00Z",
        "failure": "permission_denied" if failed else None,
        "retrieval": {
            "status": "failed" if failed else "complete",
            "started_at": "2026-09-12T12:00:00Z",
            "finished_at": "2026-09-12T12:00:00Z",
            "include_type": "all",
            "request_attempts": 4,
            "pages_fetched": 0 if failed else 1,
            "projects_discovered": 0 if failed else 1,
            "projects_fetched": 0 if failed else 1,
            "projects_failed": 0,
            "limitations": ["Workspace resource inaccessible"] if failed else [],
        },
    }


def command(tmp_path, platform="cja"):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_bytes(Path(f"tests/fixtures/{platform}_snapshot_clean.json").read_bytes())
    args = [
        str(snapshot),
        "--collect-workspace-usage",
        "--workspace-usage-org",
        "org",
        "--output",
        str(tmp_path / "report.html"),
        "--json",
        str(tmp_path / "report.json"),
    ]
    if platform == "aa":
        args += ["--workspace-usage-company", "co"]
    return args


@pytest.mark.parametrize("platform", ["aa", "cja"])
def test_collection_automatically_saves_replayable_evidence(tmp_path, monkeypatch, platform):
    calls = []
    monkeypatch.setattr(
        collector, "_acquire", lambda request: calls.append(request) or acquisition()
    )
    assert main(command(tmp_path, platform)) == 0
    evidence = json.loads((tmp_path / "report.workspace-usage.json").read_text())
    payload = json.loads((tmp_path / "report.json").read_text())
    assert evidence == payload["workspace_usage"]["evidence"]
    assert extract_payload((tmp_path / "report.html").read_text()) == payload
    assert calls[0]["platform"] == platform
    assert evidence["collection"]["source"]["kind"] == "sdk_candidates"
    assert any(result["projects"] for result in evidence["results"])


@pytest.fixture
def empty_lookup(monkeypatch):
    calls = []

    def acquire(request):
        calls.append(request)
        value = acquisition()
        value["projects"] = []
        value["retrieval"].update(
            projects_discovered=0,
            projects_fetched=0,
            include_type="explicit" if request["project_ids"] else request["scope"],
        )
        if request["project_ids"]:
            value["retrieval"].update(
                status="partial",
                pages_fetched=0,
                projects_discovered=len(request["project_ids"]),
                limitations=["Synthetic project unavailable"],
            )
        return value

    monkeypatch.setattr(collector, "_acquire", acquire)
    return calls


def test_replay_uses_saved_file_without_collection_or_new_sidecar(
    tmp_path, monkeypatch, empty_lookup
):
    args = command(tmp_path)
    assert main(args) == 0
    saved = tmp_path / "report.workspace-usage.json"
    evidence = saved.read_bytes()
    monkeypatch.setattr(collector, "_acquire", lambda _: pytest.fail("replay made API call"))
    assert (
        main(
            [
                args[0],
                "--workspace-usage",
                str(saved),
                "--workspace-usage-org",
                "org",
                "--output",
                str(tmp_path / "replay.html"),
            ]
        )
        == 0
    )
    assert saved.read_bytes() == evidence
    assert not (tmp_path / "replay.workspace-usage.json").exists()
    replay = extract_payload((tmp_path / "replay.html").read_text())
    assert replay["workspace_usage"]["evidence"] == json.loads(evidence)


def test_custom_evidence_and_owner_only_mode(tmp_path, empty_lookup, capsys):
    import stat

    args = command(tmp_path)
    destination = tmp_path / "evidence.json"
    destination.write_text("old")
    destination.chmod(0o644)
    assert main(args + ["--workspace-usage-output", str(destination), "--quiet"]) == 0
    assert json.loads(destination.read_text())["target"]["platform"] == "cja"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert not (tmp_path / "report.workspace-usage.json").exists()
    assert "wrote" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "mode", ["directory", "at", "stdin", "compare", "trend", "cja_live", "aa_live"]
)
def test_collection_preserves_input_modes(tmp_path, monkeypatch, empty_lookup, mode):
    import importlib
    import io

    cli = importlib.import_module("sdr_visualizer.cli.main")
    platform = "aa" if mode == "aa_live" else "cja"
    args = command(tmp_path, platform)
    raw = Path(args[0]).read_text()
    if mode in ("directory", "at", "trend"):
        directory = tmp_path / "snapshots"
        directory.mkdir()
        (directory / "snapshot_2026-09-10T120000.json").write_text(raw)
        (directory / "snapshot_2026-09-11T120000.json").write_text(raw)
        args[0] = str(directory)
        if mode == "at":
            args += ["--at", "2026-09-10T23:59:59Z"]
        if mode == "trend":
            args += ["--trend"]
    elif mode == "stdin":
        monkeypatch.setattr("sys.stdin", io.StringIO(raw))
        args[0] = "-"
    elif mode == "compare":
        args += ["--compare-to", args[0]]
    else:
        calls = []
        monkeypatch.setattr(
            cli,
            "shell_aa" if platform == "aa" else "shell_cja",
            lambda identity: calls.append(identity) or (json.loads(raw), "synthetic-export"),
        )
        args = ["--rsid" if platform == "aa" else "--dataview", "environment", *args[1:]]
    assert main(args) == 0
    assert len(empty_lookup) == 1
    payload = json.loads((tmp_path / "report.json").read_text())
    assert ("changes" in payload) == (mode == "compare")
    assert ("trend" in payload) == (mode == "trend")
    if mode.endswith("live"):
        assert calls == ["environment"]


@pytest.mark.parametrize(
    "extra",
    [
        ["--workspace-usage-scope", "owned"],
        ["--workspace-usage-config", "missing"],
        ["--workspace-usage-project", "p"],
        ["--workspace-usage-component", "metric=m"],
        ["--workspace-usage-output", "usage.json"],
    ],
)
def test_collect_only_options_rejected_without_collection(tmp_path, empty_lookup, extra):
    args = command(tmp_path)
    args.remove("--collect-workspace-usage")
    assert main(args + extra) == 3
    assert not empty_lookup
    assert not (tmp_path / "report.html").exists()


@pytest.mark.parametrize(
    "extra",
    [
        ["--workspace-usage-scope", "all", "--workspace-usage-project", "p"],
        ["--workspace-usage-project", "p", "--workspace-usage-project", "p"],
        ["--workspace-usage-project", ""],
        ["--workspace-usage-component", "metric"],
        ["--workspace-usage-component", "metric="],
        ["--workspace-usage-component", "unknown=m"],
        ["--workspace-usage-component", "metric=unknown"],
        ["--workspace-usage-component", "metric=m", "--workspace-usage-component", "metric=m"],
        ["--workspace-usage-config", "missing"],
        ["--workspace-usage-company", "co"],
    ],
)
def test_invalid_collection_options_never_acquire(tmp_path, empty_lookup, extra):
    assert main(command(tmp_path) + extra) == 3
    assert not empty_lookup
    assert not (tmp_path / "report.html").exists()


def test_collection_requires_org_and_aa_company(tmp_path, empty_lookup):
    args = command(tmp_path)
    index = args.index("--workspace-usage-org")
    del args[index : index + 2]
    assert main(args) == 3
    args = command(tmp_path, "aa")[:-2]
    assert main(args) == 3
    assert not empty_lookup


def test_collect_and_replay_exclusive(tmp_path, empty_lookup):
    with pytest.raises(SystemExit) as error:
        main(command(tmp_path) + ["--workspace-usage", "usage.json"])
    assert error.value.code == 3
    assert not empty_lookup


@pytest.mark.parametrize("kind", ["literal", "symlink", "hardlink", "parent_symlink"])
def test_evidence_output_cannot_alias_snapshot(tmp_path, empty_lookup, kind):
    import os

    args = command(tmp_path)
    snapshot = Path(args[0])
    target = snapshot
    if kind in ("symlink", "hardlink"):
        target = tmp_path / "alias.json"
        if kind == "symlink":
            target.symlink_to(snapshot)
        else:
            os.link(snapshot, target)
    if kind == "parent_symlink":
        parent = tmp_path / "alias-dir"
        parent.symlink_to(tmp_path, target_is_directory=True)
        target = parent / snapshot.name
    original = snapshot.read_bytes()
    assert main(args + ["--workspace-usage-output", str(target)]) == 3
    assert snapshot.read_bytes() == original
    assert not empty_lookup


@pytest.mark.parametrize("option", ["--workspace-usage-config", "--workspace-usage-output"])
def test_supplementary_paths_outside_snapshot_directory_before_selection(
    tmp_path, empty_lookup, option
):
    args = command(tmp_path)
    directory = tmp_path / "snapshots"
    directory.mkdir()
    candidate = directory / "not-a-snapshot.json"
    candidate.write_text("DO NOT READ THESE CREDENTIALS")
    args[0] = str(directory)
    assert main(args + [option, str(candidate)]) == 3
    assert not empty_lookup
    assert candidate.read_text() == "DO NOT READ THESE CREDENTIALS"


@pytest.mark.parametrize("output", ["report.html", "report.json", "snapshot.json"])
def test_config_protected_from_every_output(tmp_path, empty_lookup, output):
    args = command(tmp_path)
    config = tmp_path / output
    if not config.exists():
        config.write_text("synthetic config never parsed by parent")
    original = config.read_bytes()
    assert main(args + ["--workspace-usage-config", str(config)]) == 3
    assert config.read_bytes() == original
    assert not empty_lookup


@pytest.mark.parametrize("output", ["report.html", "report.json"])
def test_outputs_pairwise_distinct(tmp_path, empty_lookup, output):
    assert main(command(tmp_path) + ["--workspace-usage-output", str(tmp_path / output)]) == 3
    assert not empty_lookup


def test_default_evidence_output_cannot_pollute_snapshot_directory(tmp_path, empty_lookup):
    args = command(tmp_path)
    directory = tmp_path / "snapshots"
    directory.mkdir()
    (directory / "snapshot.json").write_bytes(Path(args[0]).read_bytes())
    args[0] = str(directory)
    args[args.index("--output") + 1] = str(directory / "report.html")
    assert main(args) == 3
    assert not empty_lookup


def test_failed_lookup_still_writes_truthful_evidence(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(collector, "_acquire", lambda _: acquisition(failed=True))
    assert main(command(tmp_path)) == 0
    evidence = json.loads((tmp_path / "report.workspace-usage.json").read_text())
    assert evidence["collection"]["status"] == "failed"
    assert evidence["results"] == []
    assert "Workspace lookup failed" in capsys.readouterr().err


def test_interrupt_during_collection_writes_nothing(tmp_path, monkeypatch, capsys):
    def interrupt(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(collector, "_acquire", interrupt)
    assert main(command(tmp_path)) == 1
    assert not (tmp_path / "report.html").exists()
    assert "interrupted" in capsys.readouterr().err


@pytest.mark.parametrize("failure", ["stage", "replace", "interrupt"])
def test_staged_writes_preserve_complete_files_and_cleanup(
    tmp_path, monkeypatch, empty_lookup, capsys, failure
):
    from sdr_visualizer.cli import workspace_usage as helper

    args = command(tmp_path)
    finals = [
        tmp_path / name for name in ("report.html", "report.json", "report.workspace-usage.json")
    ]
    for destination in finals:
        destination.write_text("old content")
    if failure in ("stage", "interrupt"):
        original = helper.tempfile.NamedTemporaryFile
        calls = []

        def stage(**kwargs):
            calls.append(1)
            if len(calls) == 2:
                if failure == "interrupt":
                    raise KeyboardInterrupt
                raise OSError("synthetic staging failure")
            return original(**kwargs)

        monkeypatch.setattr(helper.tempfile, "NamedTemporaryFile", stage)
    else:
        original = helper.os.replace
        calls = []

        def replace(source, destination):
            calls.append(1)
            if len(calls) == 2:
                raise OSError("synthetic replacement failure")
            return original(source, destination)

        monkeypatch.setattr(helper.os, "replace", replace)
    assert main(args) == 1
    assert not list(tmp_path.glob(".*.tmp"))
    assert finals[1].read_text() == finals[2].read_text() == "old content"
    assert (
        finals[0].read_text().startswith("<!doctype html>")
        if failure == "replace"
        else finals[0].read_text() == "old content"
    )
    error = capsys.readouterr().err
    assert "wrote" not in error
    if failure != "interrupt":
        assert "report.json" in error


def test_public_python_collection_returns_replay_mapping(tmp_path, empty_lookup):
    from sdr_visualizer.core.visualizer import visualize
    from sdr_visualizer.usage import collect_workspace_usage

    args = command(tmp_path)
    snapshot = json.loads(Path(args[0]).read_text())
    evidence = collect_workspace_usage(snapshot, organization_context="org")
    html = visualize(snapshot, workspace_usage=evidence, organization_context="org")
    assert extract_payload(html)["workspace_usage"]["evidence"] == evidence
    assert len(empty_lookup) == 1


@pytest.mark.parametrize("scope", ["all", "owned", "shared"])
def test_selected_scope_and_config_reach_collector_without_parent_read(
    tmp_path, monkeypatch, empty_lookup, scope
):
    args = command(tmp_path)
    config = tmp_path / "credentials.json"
    config.write_text("synthetic invalid content must not be parsed in parent")
    original = Path.read_text

    def read(path, *a, **kw):
        assert path != config, "Parent attempted credential read"
        return original(path, *a, **kw)

    monkeypatch.setattr(Path, "read_text", read)
    assert (
        main(args + ["--workspace-usage-scope", scope, "--workspace-usage-config", str(config)])
        == 0
    )
    assert empty_lookup[0]["scope"] == scope
    assert empty_lookup[0]["config_path"] == str(config)


def test_exact_component_selection_preserves_equals_in_id(tmp_path, empty_lookup):
    args = command(tmp_path)
    snapshot = Path(args[0])
    raw = json.loads(snapshot.read_text())
    raw["dimensions"][0]["id"] = "variables/id=with=equals"
    snapshot.write_text(json.dumps(raw))
    assert main(args + ["--workspace-usage-component", "dimension=variables/id=with=equals"]) == 0
    evidence = json.loads((tmp_path / "report.workspace-usage.json").read_text())
    assert evidence["requested_components"] == [
        {"type": "dimension", "id": "variables/id=with=equals"}
    ]
    assert len(evidence["results"]) == 1


def test_explicit_project_ids_reach_collector(tmp_path, empty_lookup):
    assert (
        main(
            command(tmp_path)
            + ["--workspace-usage-project", "p1", "--workspace-usage-project", "p2"]
        )
        == 0
    )
    assert empty_lookup[0]["project_ids"] == ["p1", "p2"]
    evidence = json.loads((tmp_path / "report.workspace-usage.json").read_text())
    assert evidence["collection"]["project_scope"] == {
        "kind": "explicit_projects",
        "project_ids": ["p1", "p2"],
    }


@pytest.mark.parametrize("problem", ["company", "dependencies", "destination"])
def test_known_preflight_failures_precede_live_exporter(tmp_path, monkeypatch, problem):
    import importlib
    import importlib.metadata

    cli = importlib.import_module("sdr_visualizer.cli.main")
    monkeypatch.setattr(cli, "shell_aa", lambda _: pytest.fail("exporter must not run"))
    args = [
        "--rsid",
        "suite",
        "--collect-workspace-usage",
        "--workspace-usage-org",
        "org",
        "--output",
        str(tmp_path / "report.html"),
    ]
    if problem != "company":
        args += ["--workspace-usage-company", "co"]
    if problem == "dependencies":

        def missing(_):
            raise importlib.metadata.PackageNotFoundError("synthetic")

        monkeypatch.setattr(importlib.metadata, "version", missing)
    if problem == "destination":
        args += ["--json", str(tmp_path / "report.workspace-usage.json")]
    assert main(args) == 3


@pytest.mark.parametrize("kind", ["directory", "oversize"])
def test_config_metadata_errors_before_api(tmp_path, empty_lookup, kind):
    args = command(tmp_path)
    config = tmp_path / "config"
    if kind == "directory":
        config.mkdir()
    else:
        config.write_bytes(b"x" * 65537)
    assert main(args + ["--workspace-usage-config", str(config)]) == 3
    assert not empty_lookup


@pytest.mark.parametrize("destination", ["missing/report.html", "."])
def test_invalid_output_parent_before_api(tmp_path, empty_lookup, destination):
    args = command(tmp_path)
    args[args.index("--output") + 1] = str(tmp_path / destination)
    assert main(args) == 3
    assert not empty_lookup


def test_unknown_path_identity_rejects_without_api(tmp_path, monkeypatch, empty_lookup):
    monkeypatch.setattr("sdr_visualizer.cli.workspace_usage.paths_alias", lambda *args: None)
    assert main(command(tmp_path)) == 3
    assert not empty_lookup


def test_dependency_version_mismatch_rejects_before_api(tmp_path, monkeypatch, empty_lookup):
    monkeypatch.setattr("importlib.metadata.version", lambda _: "wrong")
    assert main(command(tmp_path) + ["--platform", "cja"]) == 3
    assert not empty_lookup


def test_existing_html_permissions_preserved_when_staged(tmp_path, empty_lookup):
    import stat

    args = command(tmp_path)
    html = tmp_path / "report.html"
    html.write_text("old")
    html.chmod(0o640)
    assert main(args) == 0
    assert stat.S_IMODE(html.stat().st_mode) == 0o640


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permission contract")
@pytest.mark.parametrize("mask", [0o022, 0o027, 0o077])
def test_staged_output_permissions_follow_creation_and_replacement_policy(tmp_path, mask):
    # Isolate umask changes from this test process and any concurrent threads.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
import stat
import sys
from pathlib import Path
from sdr_visualizer.cli.workspace_usage import write_artifacts

root = Path(sys.argv[1])
os.umask(int(sys.argv[2]))
ordinary = root / "ordinary.html"
ordinary.write_text("ordinary output")
expected = stat.S_IMODE(ordinary.stat().st_mode)
artifacts = []
for name, private, existing_mode in [
    ("new.html", False, None),
    ("new.json", False, None),
    ("new.workspace-usage.json", True, None),
    ("existing.html", False, 0o604),
    ("existing.json", False, 0o640),
    ("existing.workspace-usage.json", True, 0o644),
]:
    path = root / name
    if existing_mode is not None:
        path.write_text("old")
        path.chmod(existing_mode)
    artifacts.append((path, "new content", private))
write_artifacts(artifacts)
for path, _, private in artifacts:
    mode = 0o600 if private else {
        "existing.html": 0o604, "existing.json": 0o640,
    }.get(path.name, expected)
    assert stat.S_IMODE(path.stat().st_mode) == mode, path.name
    assert path.read_text() == "new content"
assert len(list(root.iterdir())) == len(artifacts) + 1
""",
            str(tmp_path),
            str(mask),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("failure", ["create", "stat", "chmod"])
def test_creation_mode_failure_cleans_staging_and_preserves_finals(tmp_path, monkeypatch, failure):
    from sdr_visualizer.cli import workspace_usage as helper

    existing = tmp_path / "existing.html"
    existing.write_text("old content")
    destination = tmp_path / "new.json"

    if failure == "create":
        original = Path.open

        def open_probe(path, *args, **kwargs):
            if path.name == "probe":
                raise OSError("synthetic mode failure")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", open_probe)
    elif failure == "stat":
        import stat

        original = helper.os.fstat

        def stat_probe(fd):
            result = original(fd)
            if stat.S_ISREG(result.st_mode):
                raise OSError("synthetic mode failure")
            return result

        monkeypatch.setattr(helper.os, "fstat", stat_probe)
    else:
        original = helper.os.chmod

        def chmod(path, mode):
            if Path(path).name.startswith(".new.json."):
                raise OSError("synthetic mode failure")
            return original(path, mode)

        monkeypatch.setattr(helper.os, "chmod", chmod)

    with pytest.raises(OSError, match="could not write .*new.json: synthetic mode failure"):
        helper.write_artifacts([(existing, "replacement", False), (destination, "new", False)])
    assert existing.read_text() == "old content"
    assert list(tmp_path.iterdir()) == [existing]


@pytest.mark.parametrize(
    "extra",
    [["--workspace-usage-company", ""], ["--platform", "cja", "--workspace-usage-company", "co"]],
)
def test_company_context_preflight(tmp_path, empty_lookup, extra):
    assert main(command(tmp_path) + extra) == 3
    assert not empty_lookup


def test_unresolvable_supplementary_directory_identity(tmp_path, monkeypatch, empty_lookup):
    args = command(tmp_path)
    directory = tmp_path / "snapshots"
    directory.mkdir()
    args[0] = str(directory)
    config = tmp_path / "config.json"
    config.write_text("synthetic")
    original = Path.resolve

    def resolve(path, *a, **kw):
        if path == config:
            raise RuntimeError("synthetic symlink loop")
        return original(path, *a, **kw)

    monkeypatch.setattr(Path, "resolve", resolve)
    assert main(args + ["--workspace-usage-config", str(config)]) == 3
    assert not empty_lookup


def test_collection_default_html_name_without_report_json(tmp_path, monkeypatch, empty_lookup):
    args = command(tmp_path)
    args = args[: args.index("--output")]
    monkeypatch.chdir(tmp_path)
    assert main(args) == 0
    html = next(tmp_path.glob("visualize-*.html"))
    saved = html.with_name(html.stem + ".workspace-usage.json")
    assert (
        json.loads(saved.read_text())
        == extract_payload(html.read_text())["workspace_usage"]["evidence"]
    )
    assert not (tmp_path / "report.json").exists()


def test_usage_json_serialization_failure_precedes_all_writes(
    tmp_path, monkeypatch, empty_lookup, capsys
):
    import importlib

    cli = importlib.import_module("sdr_visualizer.cli.main")
    original = cli.build_payload_with_options

    def payload(*args, **kwargs):
        result = original(*args, **kwargs)
        result["nonfinite"] = float("nan")
        return result

    monkeypatch.setattr(cli, "build_payload_with_options", payload)
    assert main(command(tmp_path)) == 3
    assert len(empty_lookup) == 1
    assert not (tmp_path / "report.html").exists()
    assert not (tmp_path / "report.workspace-usage.json").exists()
    assert "NaN or Infinity" in capsys.readouterr().err


def test_legacy_interrupt_behavior_preserved(tmp_path, monkeypatch):
    import importlib

    cli = importlib.import_module("sdr_visualizer.cli.main")

    def interrupt(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_load", interrupt)
    args = command(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        main([args[0]])


def test_partial_collection_failure_warns_and_preserves_positive_results(
    tmp_path, monkeypatch, capsys
):
    args = command(tmp_path, "aa")
    value = acquisition()
    value["failure"] = "permission_denied"
    value["retrieval"].update(status="partial", limitations=["Some projects were inaccessible"])
    monkeypatch.setattr(collector, "_acquire", lambda _: value)
    assert main(args) == 0
    evidence = json.loads((tmp_path / "report.workspace-usage.json").read_text())
    assert evidence["collection"]["status"] == "partial"
    assert any(result["projects"] for result in evidence["results"])
    assert "Workspace lookup failed" in capsys.readouterr().err
