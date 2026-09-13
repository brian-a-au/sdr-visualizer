"""Strict supplementary Workspace evidence contract."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.visualizer import build_implementation
from sdr_visualizer.core.workspace_usage import (
    SCHEMA,
    bind_workspace_usage,
    snapshot_digest,
    validate_json_value,
)
from sdr_visualizer.input.workspace_usage import load_workspace_usage


def example():
    raw = json.loads((Path(__file__).parent / "fixtures/cja_snapshot_clean.json").read_text())
    impl = build_implementation(raw, source="synthetic")
    component = {"type": "metric", "id": impl.metrics[0].id}
    value = {
        "schema_version": 1,
        "target": {
            "platform": "cja",
            "ims_org_id": "org",
            "data_view_id": impl.instance_id,
            "snapshot_digest": snapshot_digest(raw),
        },
        "collection": {
            "status": "complete",
            "project_scope": {"kind": "accessible_projects"},
            "permission_visibility": "unknown",
            "limitations": [],
        },
        "requested_components": [component],
        "results": [
            {
                "component": component.copy(),
                "status": "complete",
                "checked_at": "2026-09-12T12:00:00Z",
                "match_basis": "exact_component_id",
                "projects": [],
                "limitations": [],
            }
        ],
    }
    return impl, value


def test_exact_empty_completed_scope():
    impl, value = example()
    bound = bind_workspace_usage(value, impl, organization_context="org")
    assert bound.project("2026-09-12T13:00:00Z")["display"][0]["state"] == "no_references_found"


def bind(impl, value):
    return bind_workspace_usage(value, impl, organization_context="org")


def row(impl, value, generated="2026-09-12T13:00:00Z"):
    return bind(impl, value).project(generated)["display"][0]


@pytest.mark.parametrize(
    ("status", "basis", "projects", "expected"),
    [
        ("complete", "exact_component_id", True, "references_found"),
        ("partial", "exact_component_id", True, "partial"),
        ("failed", "exact_component_id", True, "partial"),
        ("failed", "exact_component_id", False, "failed"),
        ("complete", "unverified_lookup", True, "partial"),
        ("complete", "unverified_lookup", False, "partial"),
        ("partial", "exact_component_id", False, "partial"),
    ],
)
def test_state_precedence(status, basis, projects, expected):
    impl, value = example()
    r = value["results"][0]
    value["collection"]["status"] = r["status"] = status
    r["match_basis"] = basis
    if projects:
        r["projects"] = [{"id": "p", "name": None}]
    if status == "partial":
        r["limitations"] = ["Some projects could not be inspected"]
    if status == "failed":
        r["failure"] = value["collection"]["failure"] = "permission_denied"
    assert row(impl, value)["state"] == expected


@pytest.mark.parametrize(
    ("checked", "quality", "age"),
    [
        (None, "missing", None),
        ("", "missing", None),
        ("bad", "invalid", None),
        ("2026-09-12", "invalid", None),
        ("2026-09-12T13:00:00", "invalid", None),
        ("2026-09-12T13:00:00PDT", "invalid", None),
        ("2026-02-30T13:00:00Z", "invalid", None),
        ("2026-09-12T13:00:00+00:60", "invalid", None),
        ("2026-09-12T13:00:00.001Z", "future", None),
        ("2026-09-11T13:00:00Z", "valid", "within_24h"),
        ("2026-09-11T12:59:59Z", "valid", "older_than_24h"),
        ("2026-09-12T15:00:00+02:00", "valid", "within_24h"),
    ],
)
def test_time_independent_of_positive_observation(checked, quality, age):
    impl, value = example()
    value["results"][0]["checked_at"] = checked
    observed = row(impl, value)
    assert (observed["time_quality"], observed["age_at_generation"]) == (quality, age)
    assert observed["state"] == ("no_references_found" if quality == "valid" else "partial")
    value["results"][0]["projects"] = [{"id": "p", "name": '<script>&"'}]
    assert row(impl, value)["state"] == "references_found"


def test_missing_requested_failed_partial_and_unrequested():
    impl, value = example()
    value["results"] = []
    value["collection"].update(status="partial", limitations=["No results were collected"])
    assert row(impl, value)["reason"] == "no_result_collected"
    value["collection"].update(status="failed", failure="collection_error")
    projected = bind(impl, value).project("2026-09-12T13:00:00Z")
    assert projected["display"][0]["state"] == "failed"
    assert projected["display"][1]["state"] == "not_checked"
    assert projected["summary"]["attempted"] == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.update(schema_version=True),
        lambda v: v.update(schema_version=2),
        lambda v: v.update(unreviewed="anything"),
        lambda v: v["target"].update(ims_org_id="other"),
        lambda v: v["target"].update(data_view_id="other"),
        lambda v: v["target"].update(rsid="cross-platform"),
        lambda v: v["target"]["snapshot_digest"].update(value="0" * 64),
        lambda v: v["requested_components"].append(v["requested_components"][0]),
        lambda v: v["results"].append(deepcopy(v["results"][0])),
        lambda v: v["requested_components"][0].update(id="unknown"),
        lambda v: v["results"][0]["component"].update(type="segment"),
        lambda v: v["results"][0].update(status="failed"),
        lambda v: v["results"][0].update(failure="unknown"),
        lambda v: v.update(results=[]),
        lambda v: v["results"][0].update(checked_at=123),
        lambda v: v["results"][0].update(
            projects=[{"id": "p", "name": None, "url": "https://example.com"}]
        ),
        lambda v: v["results"][0].update(projects=[{"id": "p\n", "name": None}]),
        lambda v: v["results"][0].update(projects=[{"id": "p", "name": "x" * 257}]),
        lambda v: v["results"][0].update(limitations=["x"] * 21),
        lambda v: v["results"][0].update(projects=[{"id": "p", "name": "\ud800"}]),
    ],
)
def test_invalid_contract_is_atomic(mutate):
    impl, value = example()
    mutate(value)
    with pytest.raises(InvalidSnapshotError):
        bind(impl, value)


def test_project_dedup_sort_conflict_and_scope():
    impl, value = example()
    value["results"][0]["projects"] = [
        {"id": "z", "name": None},
        {"id": "a", "name": "A"},
        {"id": "z", "name": None},
    ]
    assert [p["id"] for p in bind(impl, value).evidence["results"][0]["projects"]] == ["a", "z"]
    value["results"][0]["projects"].append({"id": "z", "name": "Z"})
    with pytest.raises(InvalidSnapshotError, match="conflicting"):
        bind(impl, value)
    value["results"][0]["projects"].pop()
    value["collection"]["project_scope"] = {"kind": "explicit_projects", "project_ids": ["z"]}
    with pytest.raises(InvalidSnapshotError, match="outside"):
        bind(impl, value)


def test_duplicate_inventory_id_across_types():
    impl, value = example()
    impl.dimensions[0].id = impl.metrics[0].id
    with pytest.raises(InvalidSnapshotError, match="ambiguous"):
        bind(impl, value)


def test_evidence_defensive_copy():
    impl, value = example()
    bound = bind(impl, value)
    value["collection"]["limitations"].append("mutation")
    evidence = bound.evidence
    evidence["collection"]["limitations"].append("another mutation")
    assert bound.evidence["collection"]["limitations"] == []


def test_digest_vectors():
    assert snapshot_digest({"b": ["é", 1], "a": 1.0}) == snapshot_digest(
        json.loads('{"a":1.0,"b":["é",1]}')
    )
    assert snapshot_digest({"a": 1}) != snapshot_digest({"a": 1.0})
    assert snapshot_digest([1, 2]) != snapshot_digest([2, 1])
    assert (
        snapshot_digest({})["value"]
        == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )
    with pytest.raises(InvalidSnapshotError):
        snapshot_digest({"a": float("nan")})


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b"\xef\xbb\xbf{}",
        b"\xff",
        b"{",
        b"[]",
        b'{"a":"\\ud800"}',
    ],
)
def test_file_decode_rejects_ambiguity(tmp_path, raw):
    path = tmp_path / "usage.json"
    path.write_bytes(raw)
    with pytest.raises(InvalidSnapshotError):
        load_workspace_usage(path)


def test_file_mapping_parity_and_published_schema(tmp_path):
    impl, value = example()
    schema = json.loads(
        (Path(__file__).parents[1] / "docs/workspace-usage-schema.json").read_text()
    )
    assert schema == SCHEMA
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)
    path = tmp_path / "usage.json"
    path.write_text(json.dumps(value))
    assert bind(impl, load_workspace_usage(path)).evidence == bind(impl, value).evidence


@pytest.mark.parametrize("value", [float("inf"), {"a": object()}, {1: "bad"}, "\ud800"])
def test_mapping_non_json_rejected(value):
    with pytest.raises(InvalidSnapshotError):
        validate_json_value(value)


def test_structure_and_file_bounds(tmp_path):
    nested = []
    for _ in range(21):
        nested = [nested]
    for value in (nested, [None] * 100_000):
        with pytest.raises(InvalidSnapshotError, match="structure"):
            validate_json_value(value)
    circular = []
    circular.append(circular)
    with pytest.raises(InvalidSnapshotError):
        validate_json_value(circular)
    path = tmp_path / "large.json"
    path.write_bytes(b" " * 2_097_153)
    with pytest.raises(InvalidSnapshotError, match="byte limit"):
        load_workspace_usage(path)
    with pytest.raises(InvalidSnapshotError):
        load_workspace_usage(tmp_path)


def test_occurrence_bound_before_deduplication():
    impl, value = example()
    value["results"][0]["projects"] = [{"id": "same", "name": None}] * 10_001
    with pytest.raises(InvalidSnapshotError):
        bind(impl, value)


def retrieval():
    return {
        "status": "complete",
        "started_at": "2026-09-12T12:00:00Z",
        "finished_at": "2026-09-12T12:01:00Z",
        "include_type": "all",
        "request_attempts": 3,
        "pages_fetched": 1,
        "projects_discovered": 1,
        "projects_fetched": 1,
        "projects_failed": 0,
        "limitations": [],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"projects_fetched": 0},
        {"projects_failed": 1},
        {"include_type": "explicit"},
        {"finished_at": None},
        {"finished_at": "bad"},
        {"finished_at": "2026-09-11T00:00:00Z"},
        {"request_attempts": True},
        {"projects_discovered": 1001},
        {"request_attempts": 257},
        {"limitations": ["incomplete"]},
    ],
)
def test_retrieval_consistency(change):
    impl, value = example()
    value["collection"]["retrieval"] = retrieval() | change
    with pytest.raises(InvalidSnapshotError):
        bind(impl, value)


def test_retrieval_and_sdk_provenance():
    impl, value = example()
    value["collection"]["retrieval"] = retrieval()
    bind(impl, value)
    value["collection"]["source"] = {"kind": "sdk_candidates", "sdk": "cjapy", "version": "0.3.1"}
    with pytest.raises(InvalidSnapshotError, match="unverified"):
        bind(impl, value)
    value["results"][0]["match_basis"] = "unverified_lookup"
    bind(impl, value)
    value["collection"]["source"]["sdk"] = "aanalytics2"
    with pytest.raises(InvalidSnapshotError, match="SDK platform"):
        bind(impl, value)


def test_aa_independent_target_branch():
    raw = json.loads((Path(__file__).parent / "fixtures/aa_snapshot_clean.json").read_text())
    impl = build_implementation(raw, source="synthetic")
    _, value = example()
    value["target"] = {
        "platform": "aa",
        "ims_org_id": "org",
        "global_company_id": "company",
        "rsid": impl.instance_id,
        "snapshot_digest": snapshot_digest(raw),
    }
    value["requested_components"] = [{"type": "metric", "id": impl.metrics[0].id}]
    value["results"][0]["component"] = value["requested_components"][0].copy()
    assert (
        bind_workspace_usage(
            value, impl, organization_context="org", company_context="company"
        ).evidence
        == value
    )
    with pytest.raises(InvalidSnapshotError, match="company"):
        bind(impl, value)


@pytest.mark.parametrize("platform", ["aa", "cja"])
@pytest.mark.parametrize("legacy", [False, True])
def test_independent_platform_all_types_and_legacy(platform, legacy):
    from sdr_visualizer.core.workspace_usage import component_inventory

    raw = json.loads(
        (Path(__file__).parent / f"fixtures/{platform}_snapshot_clean.json").read_text()
    )
    if legacy:
        if platform == "aa":
            raw.pop("captured_at", None)
            raw.pop("tool_version", None)
        else:
            raw["metadata"].pop("Generation Timestamp", None)
            raw["metadata"].pop("Tool Version", None)
    impl = build_implementation(raw, source="synthetic")
    fixture = Path(__file__).parent / f"fixtures/workspace_usage_{platform}_all_types.json"
    value = json.loads(fixture.read_text())
    value["target"]["snapshot_digest"] = snapshot_digest(raw)
    bound = bind_workspace_usage(
        value,
        impl,
        organization_context="org",
        company_context="company" if platform == "aa" else None,
    )
    assert {c["type"] for c in value["requested_components"]} == {
        c["type"] for c in component_inventory(impl)
    }
    assert all(
        r["state"] == "references_found" for r in bound.project("2026-09-12T13:00:00Z")["display"]
    )
    Draft202012Validator(SCHEMA).validate(bound.evidence)


@pytest.mark.parametrize("platform", ["aa", "cja"])
@pytest.mark.parametrize(
    "mismatch", ["org", "instance", "platform", "type", "alias", "duplicate", "company"]
)
def test_platform_binding_mismatch_matrix(platform, mismatch):
    raw = json.loads(
        (Path(__file__).parent / f"fixtures/{platform}_snapshot_clean.json").read_text()
    )
    impl = build_implementation(raw, source="synthetic")
    value = json.loads(
        (Path(__file__).parent / f"fixtures/workspace_usage_{platform}_all_types.json").read_text()
    )
    company = "company" if platform == "aa" else None
    if mismatch == "org":
        value["target"]["ims_org_id"] = "wrong"
    elif mismatch == "instance":
        value["target"]["rsid" if platform == "aa" else "data_view_id"] = "wrong"
    elif mismatch == "platform":
        value["target"]["platform"] = "cja" if platform == "aa" else "aa"
    elif mismatch == "type":
        value["requested_components"][0]["type"] = (
            "derived_field" if platform == "aa" else "segment"
        )
    elif mismatch == "alias":
        value["requested_components"][0]["id"] = value["requested_components"][0]["id"].split("/")[
            -1
        ]
    elif mismatch == "duplicate":
        impl.dimensions[0].id = impl.metrics[0].id
    else:
        company = "wrong"
    with pytest.raises(InvalidSnapshotError):
        bind_workspace_usage(value, impl, organization_context="org", company_context=company)


def test_virtual_suite_parent_never_substituted():
    raw = json.loads((Path(__file__).parent / "fixtures/aa_snapshot_clean.json").read_text())
    raw["report_suite"].update(rsid="virtual:exact", parent_rsid="parent.prod")
    impl = build_implementation(raw, source="synthetic")
    value = json.loads(
        (Path(__file__).parent / "fixtures/workspace_usage_aa_all_types.json").read_text()
    )
    value["target"].update(rsid="virtual:exact", snapshot_digest=snapshot_digest(raw))
    bind_workspace_usage(value, impl, organization_context="org", company_context="company")
    value["target"]["rsid"] = "parent.prod"
    with pytest.raises(InvalidSnapshotError, match="instance"):
        bind_workspace_usage(value, impl, organization_context="org", company_context="company")


def test_result_indices_retain_one_evidence_copy():
    impl, value = example()
    value["results"][0]["projects"] = [{"id": "__proto__", "name": "Synthetic project"}]
    projected = bind(impl, value).project("2026-09-12T13:00:00Z")
    assert projected["binding"] == {
        "organization_context": "operator_asserted",
        "snapshot": "matched",
    }
    assert projected["display"][0]["result_index"] == 0
    assert "projects" not in projected["display"][0]
    assert projected["summary"] == {
        "complete": 1,
        "partial": 0,
        "failed": 0,
        "attempted": 1,
        "requested": 1,
    }


def test_payload_budget_rejects_without_truncation():
    impl, value = example()
    value["results"][0]["projects"] = [{"id": str(i), "name": "x" * 256} for i in range(4000)]
    bound = bind(impl, value)
    with pytest.raises(InvalidSnapshotError, match="normalized payload byte limit"):
        bound.project("2026-09-12T13:00:00Z")
    assert len(bound.evidence["results"][0]["projects"]) == 4000


def test_no_results_requires_explicit_statement():
    from sdr_visualizer.core.workspace_usage import NO_RESULTS_LIMITATION

    impl, value = example()
    value["results"] = []
    value["collection"].update(status="partial", limitations=["Only desktop projects inspected"])
    with pytest.raises(InvalidSnapshotError, match="explicit limitation"):
        bind(impl, value)
    value["collection"]["limitations"].append(NO_RESULTS_LIMITATION)
    assert row(impl, value)["state"] == "not_checked"


def test_missing_retrieval_interval_requires_clock_reversal_statement():
    from sdr_visualizer.core.workspace_usage import CLOCK_REVERSAL_LIMITATION

    impl, value = example()
    value["collection"]["retrieval"] = retrieval() | {
        "status": "partial",
        "started_at": None,
        "finished_at": None,
        "limitations": ["Only desktop projects inspected"],
    }
    with pytest.raises(InvalidSnapshotError, match="clock reversal"):
        bind(impl, value)
    value["collection"]["retrieval"]["limitations"].append(CLOCK_REVERSAL_LIMITATION)
    bind(impl, value)


def test_explicit_retrieval_counts_match_requested_scope():
    impl, value = example()
    value["collection"]["project_scope"] = {"kind": "explicit_projects", "project_ids": ["a", "b"]}
    value["collection"]["retrieval"] = retrieval() | {"include_type": "explicit"}
    with pytest.raises(InvalidSnapshotError, match="counters"):
        bind(impl, value)
    value["collection"]["retrieval"].update(projects_discovered=2, projects_fetched=2)
    bind(impl, value)


def test_non_regular_and_missing_path(tmp_path):
    import os

    with pytest.raises(InvalidSnapshotError):
        load_workspace_usage(tmp_path / "absent")
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(InvalidSnapshotError, match="regular"):
        load_workspace_usage(fifo)


def test_total_occurrences_across_records_rejected_before_dedup():
    impl, value = example()
    second = deepcopy(value["results"][0])
    second["component"] = {"type": "metric", "id": impl.metrics[1].id}
    value["requested_components"].append(second["component"])
    value["results"].append(second)
    for r in value["results"]:
        r["projects"] = [{"id": "p", "name": None}] * 5001
    with pytest.raises(InvalidSnapshotError, match="occurrence"):
        bind(impl, value)


def test_cross_record_project_name_conflict():
    impl, value = example()
    second = deepcopy(value["results"][0])
    second["component"] = {"type": "metric", "id": impl.metrics[1].id}
    value["requested_components"].append(second["component"])
    value["results"].append(second)
    value["results"][0]["projects"] = [{"id": "p", "name": None}]
    value["results"][1]["projects"] = [{"id": "p", "name": "Named"}]
    with pytest.raises(InvalidSnapshotError, match="conflicting"):
        bind(impl, value)
