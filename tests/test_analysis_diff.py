"""Diff engine tests (0.4.0 comparative view)."""

from __future__ import annotations

from sdr_visualizer.analysis.diff import diff_implementations
from sdr_visualizer.core.models import (
    CalculatedMetric,
    Component,
    Implementation,
    Segment,
)


def _component(cid, name="Metric", **overrides):
    base = dict(
        id=cid,
        name=name,
        description="d",
        component_type="metric",
        data_type="integer",
        polarity=None,
        created_at="2026-01-01T00:00:00Z",
        modified_at="2026-01-01T00:00:00Z",
        owner="o@example.com",
        tags=[],
        platform_specific={},
    )
    base.update(overrides)
    return Component(**base)


def _segment(cid, name="Segment", **overrides):
    base = dict(
        id=cid,
        name=name,
        description="d",
        definition={},
        nesting_depth=1,
        container_types=["visits"],
        references=[],
    )
    base.update(overrides)
    return Segment(**base)


def _calc(cid, name="Calc", **overrides):
    base = dict(
        id=cid,
        name=name,
        description="d",
        formula={},
        formula_text="divide(a, b)",
        attribution_model=None,
        allocation=None,
        complexity_score=1.0,
        references=[],
    )
    base.update(overrides)
    return CalculatedMetric(**base)


def _impl(metrics=(), dimensions=(), segments=(), calcs=(), derived=(), **meta):
    base = dict(
        platform="cja",
        instance_id="dv_test",
        instance_name="Test",
        snapshot_taken_at="2026-06-01 00:00:00",
        snapshot_source="old.json",
        adapter_version="1.0.0",
    )
    base.update(meta)
    return Implementation(
        metrics=list(metrics),
        dimensions=list(dimensions),
        segments=list(segments),
        calculated_metrics=list(calcs),
        derived_fields=list(derived),
        raw={},
        **base,
    )


def test_added_and_removed_by_id():
    old = _impl(metrics=[_component("metrics/m1")])
    new = _impl(metrics=[_component("metrics/m1"), _component("metrics/m2", name="New Metric")])
    changes = diff_implementations(old, new)
    assert changes["added"] == [{"id": "metrics/m2", "type": "metric", "name": "New Metric"}]
    assert changes["removed"] == []

    changes_back = diff_implementations(new, old)
    assert changes_back["removed"] == [{"id": "metrics/m2", "type": "metric", "name": "New Metric"}]
    assert changes_back["added"] == []


def test_baseline_block_carries_old_snapshot_identity():
    old = _impl(snapshot_source="old.json", snapshot_taken_at="2026-05-01 09:00:00", instance_id="dv_a")
    new = _impl(snapshot_source="new.json", instance_id="dv_b")
    changes = diff_implementations(old, new)
    assert changes["baseline"] == {
        "source": "old.json",
        "taken_at": "2026-05-01 09:00:00",
        "instance_id": "dv_a",
    }


def test_scalar_field_change_reports_old_and_new():
    old = _impl(metrics=[_component("metrics/m1", name="Before", description="old desc")])
    new = _impl(metrics=[_component("metrics/m1", name="After", description="old desc")])
    changes = diff_implementations(old, new)
    assert len(changes["modified"]) == 1
    entry = changes["modified"][0]
    assert entry["id"] == "metrics/m1"
    assert entry["fields"] == [{"field": "name", "old": "Before", "new": "After"}]


def test_unchanged_component_not_reported():
    old = _impl(metrics=[_component("metrics/m1")], segments=[_segment("segments/s1")])
    new = _impl(metrics=[_component("metrics/m1")], segments=[_segment("segments/s1")])
    changes = diff_implementations(old, new)
    assert changes["added"] == [] and changes["removed"] == [] and changes["modified"] == []


def test_segment_and_calc_scalar_fields_compared():
    old = _impl(
        segments=[_segment("segments/s1", nesting_depth=1)],
        calcs=[_calc("cm/c1", formula_text="divide(a, b)")],
    )
    new = _impl(
        segments=[_segment("segments/s1", nesting_depth=3)],
        calcs=[_calc("cm/c1", formula_text="divide(a, c)")],
    )
    changes = diff_implementations(old, new)
    by_id = {e["id"]: e for e in changes["modified"]}
    assert by_id["segments/s1"]["fields"] == [{"field": "nesting_depth", "old": 1, "new": 3}]
    assert by_id["cm/c1"]["fields"] == [
        {"field": "formula_text", "old": "divide(a, b)", "new": "divide(a, c)"}
    ]
