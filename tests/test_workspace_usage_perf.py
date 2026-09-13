"""Synthetic resource-boundary cases used by both performance gates."""

import importlib.util
from pathlib import Path

import pytest

from sdr_visualizer.adapters.cja import adapt
from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.render.renderer import build_payload_with_options, render

REPO = Path(__file__).resolve().parent.parent


def helper():
    spec = importlib.util.spec_from_file_location(
        "workspace_usage_fixture", REPO / "scripts/workspace_usage_fixture.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(scale):
    spec = importlib.util.spec_from_file_location(
        "generate_large_fixture", REPO / "scripts/generate_large_fixture.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_snapshot(scale=scale)


def test_near_input_cap_preserves_ten_thousand_projects():
    case = helper()
    impl = adapt(snapshot(0.417))
    encoded = case.usage_json(impl, project_count=10_000, pad_input=True)
    assert len(encoded) == 2 * 1024 * 1024
    case.attach_usage(impl, encoded)
    payload = build_payload_with_options(impl)
    assert len(payload["workspace_usage"]["evidence"]["results"][0]["projects"]) == 10_000
    assert len(render(impl).encode()) < 2_000_000


def test_many_components_retain_repeated_project_occurrences():
    case = helper()
    impl = adapt(snapshot(1))
    case.attach_usage(impl, case.usage_json(impl, project_count=20, component_count=500))
    evidence = build_payload_with_options(impl)["workspace_usage"]["evidence"]
    assert len(evidence["results"]) == 500
    assert sum(len(row["projects"]) for row in evidence["results"]) == 10_000
    assert len(render(impl).encode()) < 4_000_000


def test_small_snapshot_large_usage_rejects_without_truncation():
    case = helper()
    impl = adapt(snapshot(0.083))
    case.attach_usage(impl, case.usage_json(impl, project_count=10_000))
    with pytest.raises(InvalidSnapshotError, match="narrower"):
        render(impl)
    assert (
        len(impl.supplementary_data["workspace_usage"].evidence["results"][0]["projects"]) == 10_000
    )


def test_supplemented_boundary_fixtures_still_exercise_the_intended_caps():
    import json

    case = helper()
    small = adapt(snapshot(0.083))
    case.attach_usage(small, case.usage_json(small, project_count=500))
    assert 450_000 <= len(render(small).encode()) < 500_000

    xl = adapt(snapshot(1.67))
    case.attach_usage(xl, case.usage_json(xl))
    usage = build_payload_with_options(xl)["workspace_usage"]
    normalized_size = len(json.dumps(usage, separators=(",", ":")).encode())
    assert 900_000 <= normalized_size <= 1024 * 1024
