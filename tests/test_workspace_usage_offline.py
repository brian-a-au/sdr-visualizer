"""Offline Workspace evidence binds only to the selected catalog."""

import importlib
import json
from io import StringIO
from pathlib import Path

import pytest

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.visualizer import build_implementation, visualize
from sdr_visualizer.core.workspace_usage import snapshot_digest

cli = importlib.import_module("sdr_visualizer.cli.main")
visualizer = importlib.import_module("sdr_visualizer.core.visualizer")


@pytest.fixture
def inputs(tmp_path):
    raw = json.loads((Path(__file__).parent / "fixtures/cja_snapshot_clean.json").read_text())
    impl = build_implementation(raw)
    value = {
        "schema_version": 1,
        "target": {
            "platform": "cja",
            "ims_org_id": "org",
            "data_view_id": impl.instance_id,
            "snapshot_digest": snapshot_digest(raw),
        },
        "collection": {
            "status": "failed",
            "project_scope": {"kind": "accessible_projects"},
            "permission_visibility": "unknown",
            "limitations": [],
            "failure": "permission_denied",
        },
        "requested_components": [{"type": "metric", "id": impl.metrics[0].id}],
        "results": [],
    }
    snapshot = tmp_path / "snapshot.json"
    usage = tmp_path / "usage.json"
    snapshot.write_text(json.dumps(raw))
    usage.write_text(json.dumps(value))
    return raw, value, snapshot, usage


def test_python_attaches_validated_evidence(inputs, monkeypatch):
    raw, value, _, _ = inputs
    monkeypatch.setattr(visualizer, "render", lambda impl, **kw: impl)
    impl = visualize(raw, workspace_usage=value, organization_context="org")
    assert impl.supplementary_data["workspace_usage"].evidence == value


@pytest.mark.parametrize(
    "options",
    [
        {"organization_context": "org"},
        {"company_context": "company"},
        {"workspace_usage": {}},
    ],
)
def test_python_requires_paired_context(inputs, options):
    with pytest.raises(InvalidSnapshotError):
        visualize(inputs[0], **options)


def arguments(inputs, tmp_path):
    return [
        str(inputs[2]),
        "--workspace-usage",
        str(inputs[3]),
        "--workspace-usage-org",
        "org",
        "--output",
        str(tmp_path / "report.html"),
    ]


@pytest.mark.parametrize("mode", ["file", "stdin", "directory", "at", "compare", "trend"])
def test_cli_attaches_primary(inputs, tmp_path, monkeypatch, mode):
    raw, value, snapshot, _ = inputs
    args = arguments(inputs, tmp_path)
    if mode == "stdin":
        args[0] = "-"
        monkeypatch.setattr("sys.stdin", StringIO(json.dumps(raw)))
    if mode in {"directory", "at", "trend"}:
        directory = tmp_path / "snapshots"
        directory.mkdir()
        (directory / "snapshot-2026-09-11T120000Z.json").write_text(json.dumps(raw))
        (directory / "snapshot-2026-09-12T120000Z.json").write_text(json.dumps(raw))
        args[0] = str(directory)
        if mode == "at":
            args += ["--at", "2026-09-12T13:00:00Z"]
        if mode == "trend":
            args += ["--trend"]
    if mode == "compare":
        args += ["--compare-to", str(snapshot)]
    attached = []
    original = cli.build_payload_with_options

    def capture(impl, **kwargs):
        attached.append(impl.supplementary_data["workspace_usage"].evidence)
        return original(impl, **kwargs)

    monkeypatch.setattr(cli, "build_payload_with_options", capture)
    assert cli.main(args) == 0
    assert attached == [value]
    assert (tmp_path / "report.html").exists()


@pytest.mark.parametrize(
    "options",
    [
        ["--workspace-usage-org", "org"],
        ["--workspace-usage-company", "company"],
        ["--workspace-usage", "missing.json"],
        ["--workspace-usage", "-", "--workspace-usage-org", "org"],
    ],
)
def test_cli_bad_pairing_before_load(inputs, tmp_path, monkeypatch, options):
    monkeypatch.setattr(cli, "_load", lambda args: pytest.fail("snapshot loaded"))
    assert cli.main([str(inputs[2]), *options, "--output", str(tmp_path / "report.html")]) == 3
    assert not (tmp_path / "report.html").exists()


@pytest.mark.parametrize("flag", ["--dataview", "--rsid"])
def test_replay_refuses_exporter(inputs, monkeypatch, flag):
    monkeypatch.setattr(cli, "_load", lambda args: pytest.fail("exporter invoked"))
    assert (
        cli.main([flag, "id", "--workspace-usage", str(inputs[3]), "--workspace-usage-org", "org"])
        == 3
    )


@pytest.mark.parametrize("damage", ["org", "digest", "company", "malformed", "missing"])
def test_invalid_usage_writes_nothing(inputs, tmp_path, damage):
    _, value, _, usage = inputs
    args = arguments(inputs, tmp_path) + ["--json", str(tmp_path / "report.json")]
    if damage == "org":
        value["target"]["ims_org_id"] = "another-org"
    if damage == "digest":
        value["target"]["snapshot_digest"]["value"] = "0" * 64
    if damage == "company":
        args += ["--workspace-usage-company", "wrong"]
    usage.write_text(json.dumps(value) if damage != "malformed" else "{")
    if damage == "missing":
        usage.unlink()
    assert cli.main(args) == 3
    assert not (tmp_path / "report.html").exists()
    assert not (tmp_path / "report.json").exists()


@pytest.mark.parametrize("kind", ["inside", "symlink_out", "symlink_in", "hardlink"])
@pytest.mark.parametrize("role", ["primary", "baseline", "trend"])
def test_directory_guard_before_selection(inputs, tmp_path, monkeypatch, kind, role):
    directory = tmp_path / "snapshots"
    directory.mkdir()
    usage = inputs[3]
    if kind == "inside":
        usage = directory / "nested" / "usage.json"
    elif kind == "symlink_out":
        inside = directory / "usage.json"
        inside.symlink_to(usage)
        usage = inside
    elif kind == "symlink_in":
        target = directory / "usage.json"
        target.write_bytes(usage.read_bytes())
        usage.unlink()
        usage.symlink_to(target)
    else:
        (directory / "candidate.json").hardlink_to(usage)
    args = arguments(inputs, tmp_path)
    args[2] = str(usage)
    if role == "baseline":
        args += ["--compare-to", str(directory)]
    else:
        args[0] = str(directory)
        if role == "trend":
            args += ["--trend"]
    monkeypatch.setattr(cli, "_load", lambda args: pytest.fail("snapshot selected"))
    monkeypatch.setattr(cli, "_load_trend", lambda args: pytest.fail("trend selected"))
    assert cli.main(args) == 3


@pytest.mark.parametrize("kind", ["direct", "symlink", "hardlink"])
@pytest.mark.parametrize("output", ["html", "json"])
def test_usage_output_alias_preserves_source(inputs, tmp_path, kind, output):
    usage = inputs[3]
    before = usage.read_bytes()
    destination = tmp_path / "alias"
    if kind == "direct":
        destination = usage
    elif kind == "symlink":
        destination.symlink_to(usage)
    else:
        destination.hardlink_to(usage)
    args = arguments(inputs, tmp_path)
    if output == "html":
        args[-1] = str(destination)
    else:
        args += ["--json", str(destination)]
    assert cli.main(args) == 3
    assert usage.read_bytes() == before
    assert not (tmp_path / "report.html").exists()


def test_python_aa_and_legacy_context(inputs, monkeypatch):
    raw = json.loads((Path(__file__).parent / "fixtures/aa_snapshot_clean.json").read_text())
    impl = build_implementation(raw)
    value = inputs[1]
    value["target"] = {
        "platform": "aa",
        "ims_org_id": "org",
        "global_company_id": "company",
        "rsid": impl.instance_id,
        "snapshot_digest": snapshot_digest(raw),
    }
    value["requested_components"] = [{"type": "metric", "id": impl.metrics[0].id}]
    monkeypatch.setattr(visualizer, "render", lambda impl, **kw: impl)
    for company in (None, "wrong"):
        with pytest.raises(InvalidSnapshotError):
            visualize(
                raw, workspace_usage=value, organization_context="org", company_context=company
            )
    result = visualize(
        raw, workspace_usage=value, organization_context="org", company_context="company"
    )
    assert result.supplementary_data["workspace_usage"].evidence == value


def test_compare_and_trend_analysis_receive_no_usage(inputs, tmp_path, monkeypatch):
    args = arguments(inputs, tmp_path)
    original = cli.diff_implementations

    def diff(baseline, primary):
        assert baseline.supplementary_data == {}
        assert "workspace_usage" in primary.supplementary_data
        return original(baseline, primary)

    monkeypatch.setattr(cli, "diff_implementations", diff)
    assert cli.main([*args, "--compare-to", str(inputs[2])]) == 0
    directory = tmp_path / "snapshots"
    directory.mkdir()
    for date in ("2026-09-11", "2026-09-12"):
        (directory / f"snapshot-{date}T120000Z.json").write_bytes(inputs[2].read_bytes())
    original_trend = cli.build_trend

    def trend(impls, **kwargs):
        assert all(impl.supplementary_data == {} for impl in impls)
        return original_trend(impls, **kwargs)

    monkeypatch.setattr(cli, "build_trend", trend)
    args[0] = str(directory)
    assert cli.main([*args, "--trend"]) == 0


def test_usage_identity_resolution_failure(inputs, tmp_path, monkeypatch):
    directory = tmp_path / "snapshots"
    directory.mkdir()
    args = arguments(inputs, tmp_path)
    args[0] = str(directory)
    monkeypatch.setattr(Path, "resolve", lambda *a, **kw: (_ for _ in ()).throw(OSError()))
    assert cli.main(args) == 3


def test_json_serialization_failure_precedes_html_write(inputs, tmp_path, monkeypatch):
    args = arguments(inputs, tmp_path) + ["--json", str(tmp_path / "report.json")]
    monkeypatch.setattr(cli, "render_payload", lambda *a, **kw: "html")
    original = cli.build_payload_with_options

    def payload(*a, **kw):
        result = original(*a, **kw)
        result["bad"] = float("nan")
        return result

    monkeypatch.setattr(cli, "build_payload_with_options", payload)
    assert cli.main(args) == 3
    assert not (tmp_path / "report.html").exists()


def test_legacy_snapshot_needs_no_exporter_enrichment(inputs, tmp_path):
    raw, value, snapshot, usage = inputs
    raw["metadata"] = {"Data View ID": value["target"]["data_view_id"]}
    value["target"]["snapshot_digest"] = snapshot_digest(raw)
    snapshot.write_text(json.dumps(raw))
    usage.write_text(json.dumps(value))
    assert cli.main(arguments(inputs, tmp_path)) == 0


def test_cli_aa_requires_company(inputs, tmp_path):
    raw = json.loads((Path(__file__).parent / "fixtures/aa_snapshot_clean.json").read_text())
    impl = build_implementation(raw)
    value = inputs[1]
    value["target"] = {
        "platform": "aa",
        "ims_org_id": "org",
        "global_company_id": "company",
        "rsid": impl.instance_id,
        "snapshot_digest": snapshot_digest(raw),
    }
    value["requested_components"] = [{"type": "metric", "id": impl.metrics[0].id}]
    inputs[2].write_text(json.dumps(raw))
    inputs[3].write_text(json.dumps(value))
    args = arguments(inputs, tmp_path)
    assert cli.main(args) == 3
    assert not (tmp_path / "report.html").exists()
    assert cli.main([*args, "--workspace-usage-company", "company"]) == 0
