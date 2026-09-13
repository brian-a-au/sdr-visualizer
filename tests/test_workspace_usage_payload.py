"""Usage embedding retains evidence without changing component analysis."""

import json
from pathlib import Path

import pytest
from conftest import extract_payload
from jsonschema import Draft202012Validator
from test_workspace_usage import example

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.workspace_usage import bind_workspace_usage
from sdr_visualizer.render.renderer import build_payload_with_options, render_payload


def attached():
    impl, evidence = example()
    evidence["results"][0]["projects"] = [{"id": "__proto__", "name": "</script><img src=x>"}]
    impl.supplementary_data["workspace_usage"] = bind_workspace_usage(
        evidence, impl, organization_context="org"
    )
    return impl, evidence


def test_usage_evidence_embedded_once_with_exact_generation_instant():
    impl, evidence = attached()
    payload = build_payload_with_options(impl)
    usage = payload["workspace_usage"]
    assert usage["evidence"] == evidence
    assert usage["generated_at"] == payload["meta"]["generated_at"]
    assert usage["display"][0]["project_count"] == 1
    assert "projects" not in usage["display"][0]
    html = render_payload(payload)
    assert extract_payload(html) == payload
    assert "</script><img src=x>" not in html
    schema = json.loads(Path("docs/payload-schema.json").read_text())
    Draft202012Validator(schema).validate(payload)


def test_usage_leaves_every_other_payload_field_unchanged():
    impl, _ = attached()
    augmented = build_payload_with_options(impl)
    impl.supplementary_data.clear()
    original = build_payload_with_options(impl)
    assert "workspace_usage" not in original
    augmented.pop("workspace_usage")
    augmented["meta"]["generated_at"] = original["meta"]["generated_at"]
    assert augmented == original


@pytest.mark.parametrize("reserved", [None, {}, {"evidence": {}}])
def test_unvalidated_reserved_slot_rejected(reserved):
    impl, _ = example()
    impl.supplementary_data["workspace_usage"] = reserved
    with pytest.raises(InvalidSnapshotError, match="validated"):
        build_payload_with_options(impl)


def test_bound_evidence_cannot_move_to_changed_snapshot():
    impl, _ = attached()
    impl.raw["extra"] = "changed snapshot"
    with pytest.raises(InvalidSnapshotError, match="snapshot mismatch"):
        build_payload_with_options(impl)


@pytest.mark.parametrize(
    ("count", "edges", "extra", "limit", "exclusive"),
    [
        (0, 0, None, 500_000, True),
        (100, 0, None, 500_000, True),
        (101, 0, None, 2_000_000, True),
        (501, 0, None, 4_000_000, True),
        (1001, 0, None, 8_000_000, True),
        (2001, 0, None, 16_000_000, False),
        (100, 8001, None, 16_000_000, False),
        (100, 0, "changes", 1_000_000, True),
        (100, 0, "trend", 1_000_000, True),
    ],
)
def test_html_size_tiers_and_utf8_bytes(count, edges, extra, limit, exclusive):
    from sdr_visualizer.render.workspace_usage import check_artifact_size

    payload = {
        "workspace_usage": {},
        "meta": {"component_count": count},
        "graph": {"edges": [None] * edges},
    }
    if extra:
        payload[extra] = {}
    accepted = limit - int(exclusive)
    check_artifact_size(payload, "x" * accepted, kind="html")
    with pytest.raises(InvalidSnapshotError, match="narrower"):
        check_artifact_size(payload, "x" * (accepted + 1), kind="html")
    with pytest.raises(InvalidSnapshotError):
        check_artifact_size(payload, "é" * limit, kind="html")


def test_json_and_normalized_caps_preserve_legacy_behavior():
    from sdr_visualizer.render.workspace_usage import check_artifact_size

    check_artifact_size({}, "x" * 16_000_001, kind="json")
    check_artifact_size({"workspace_usage": {}}, "x" * 16_000_000, kind="json")
    with pytest.raises(InvalidSnapshotError, match="json"):
        check_artifact_size({"workspace_usage": {}}, "x" * 16_000_001, kind="json")
    with pytest.raises(InvalidSnapshotError, match="normalized"):
        check_artifact_size({"workspace_usage": {"unexpected": "x" * 1_048_576}}, "", kind="json")


def test_real_renderer_rejects_oversize_without_dropping_evidence():
    impl, evidence = attached()
    payload = build_payload_with_options(impl)
    with pytest.raises(InvalidSnapshotError, match="html"):
        render_payload(payload, title="é" * 250_000)
    assert payload["workspace_usage"]["evidence"] == evidence


def test_embedded_usage_schema_matches_published_input_contract():
    from sdr_visualizer.core.workspace_usage import SCHEMA

    schema = json.loads(Path("docs/payload-schema.json").read_text())
    assert schema["$defs"]["workspaceEvidence"] == {
        k: v for k, v in SCHEMA.items() if k != "$schema"
    }


def test_json_budget_precedes_any_cli_write(tmp_path, monkeypatch):
    from sdr_visualizer.cli.main import main

    impl, evidence = attached()
    snapshot, usage = tmp_path / "snapshot.json", tmp_path / "usage.json"
    snapshot.write_text(json.dumps(impl.raw))
    usage.write_text(json.dumps(evidence))
    html, sidecar = tmp_path / "out.html", tmp_path / "out.json"
    html.write_text("prior HTML")
    sidecar.write_text("prior JSON")
    original_dumps = json.dumps

    def oversized(value, *args, **kwargs):
        if kwargs.get("indent") == 2:
            return "x" * 16_000_001
        return original_dumps(value, *args, **kwargs)

    monkeypatch.setattr(json, "dumps", oversized)
    assert (
        main(
            [
                str(snapshot),
                "--workspace-usage",
                str(usage),
                "--workspace-usage-org",
                "org",
                "--output",
                str(html),
                "--json",
                str(sidecar),
            ]
        )
        == 3
    )
    assert html.read_text() == "prior HTML"
    assert sidecar.read_text() == "prior JSON"


@pytest.mark.parametrize("platform", ["aa", "cja"])
def test_cli_html_and_report_json_retain_same_evidence(tmp_path, platform):
    from sdr_visualizer.cli.main import main

    fixture = Path("tests/fixtures")
    snapshot = fixture / f"{platform}_snapshot_clean.json"
    usage = fixture / f"workspace_usage_{platform}_all_types.json"
    html, sidecar = tmp_path / "out.html", tmp_path / "out.json"
    args = [
        str(snapshot),
        "--workspace-usage",
        str(usage),
        "--workspace-usage-org",
        "org",
        "--output",
        str(html),
        "--json",
        str(sidecar),
    ]
    if platform == "aa":
        args.extend(["--workspace-usage-company", "company"])
    assert main(args) == 0
    payload = json.loads(sidecar.read_text())
    assert extract_payload(html.read_text()) == payload
    assert payload["workspace_usage"]["evidence"] == json.loads(usage.read_text())
    Draft202012Validator(json.loads(Path("docs/payload-schema.json").read_text())).validate(payload)


@pytest.mark.parametrize("checked", [None, "", "invalid", "9999-12-31T23:59:59Z"])
def test_uncertain_time_and_failed_rows_validate_schema(checked):
    impl, evidence = example()
    evidence["collection"].update(status="failed", failure="permission_denied")
    evidence["results"][0].update(status="failed", failure="permission_denied", checked_at=checked)
    impl.supplementary_data["workspace_usage"] = bind_workspace_usage(
        evidence, impl, organization_context="org"
    )
    payload = build_payload_with_options(impl)
    assert payload["workspace_usage"]["display"][0]["state"] == "failed"
    Draft202012Validator(json.loads(Path("docs/payload-schema.json").read_text())).validate(payload)
