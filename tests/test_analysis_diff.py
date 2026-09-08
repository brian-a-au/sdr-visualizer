"""Diff engine tests (0.4.0 comparative view)."""

from __future__ import annotations

import pytest

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
    old = _impl(
        snapshot_source="old.json", snapshot_taken_at="2026-05-01 09:00:00", instance_id="dv_a"
    )
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


def test_volatile_fields_are_ignored():
    old = _impl(
        metrics=[
            _component(
                "metrics/m1",
                created_at="2026-01-01T00:00:00Z",
                modified_at="2026-01-01T00:00:00Z",
                platform_specific={"extra": {"allocation": "last"}},
            )
        ],
        calcs=[_calc("cm/c1", complexity_score=1.0)],
    )
    new = _impl(
        metrics=[
            _component(
                "metrics/m1",
                created_at="2026-02-02T00:00:00Z",
                modified_at="2026-06-30T00:00:00Z",
                platform_specific={"extra": {"allocation": "first"}},
            )
        ],
        calcs=[_calc("cm/c1", complexity_score=9.0)],
    )
    changes = diff_implementations(old, new)
    assert changes["modified"] == []


def test_list_fields_diff_as_sets():
    old = _impl(
        metrics=[_component("metrics/m1", tags=["a", "b"])],
        segments=[_segment("segments/s1", references=["metrics/m1", "metrics/m2"])],
    )
    new = _impl(
        metrics=[_component("metrics/m1", tags=["b", "a"])],  # reorder only
        segments=[_segment("segments/s1", references=["metrics/m2", "metrics/m3"])],
    )
    changes = diff_implementations(old, new)
    by_id = {e["id"]: e for e in changes["modified"]}
    assert "metrics/m1" not in by_id  # reordering is not a change
    assert by_id["segments/s1"]["fields"] == [
        {"field": "references", "added": ["metrics/m3"], "removed": ["metrics/m1"]}
    ]


def test_type_change_reports_removed_plus_added():
    old = _impl(metrics=[_component("x/1", name="Was Metric")])
    new = _impl(dimensions=[_component("x/1", name="Now Dimension", component_type="dimension")])
    changes = diff_implementations(old, new)
    assert changes["modified"] == []
    assert changes["removed"] == [{"id": "x/1", "type": "metric", "name": "Was Metric"}]
    assert changes["added"] == [{"id": "x/1", "type": "dimension", "name": "Now Dimension"}]


def test_duplicate_ids_are_last_writer_wins():
    old = _impl(
        metrics=[_component("metrics/m1", name="First"), _component("metrics/m1", name="Second")]
    )
    new = _impl(metrics=[_component("metrics/m1", name="Second")])
    changes = diff_implementations(old, new)
    assert changes["added"] == [] and changes["removed"] == [] and changes["modified"] == []


def test_output_sorted_by_type_then_id():
    old = _impl()
    new = _impl(
        metrics=[_component("metrics/z"), _component("metrics/a")],
        segments=[_segment("segments/s1")],
        calcs=[_calc("cm/c1")],
        dimensions=[_component("dims/d1", component_type="dimension")],
    )
    changes = diff_implementations(old, new)
    assert [e["id"] for e in changes["added"]] == [
        "cm/c1",  # calculated_metric
        "dims/d1",  # dimension
        "metrics/a",  # metric
        "metrics/z",
        "segments/s1",  # segment
    ]


def test_none_valued_scalar_changes_are_reported():
    old = _impl(metrics=[_component("metrics/m1", description=None)])
    new = _impl(metrics=[_component("metrics/m1", description="now documented")])
    changes = diff_implementations(old, new)
    assert changes["modified"][0]["fields"] == [
        {"field": "description", "old": None, "new": "now documented"}
    ]


@pytest.mark.parametrize("kind", ["segment", "calculated_metric"])
@pytest.mark.parametrize(
    "old_refs,new_refs,old_types,new_types,expected",
    [
        (
            ["url"],
            ["url"],
            {"metric": [], "dimension": ["url"]},
            {"metric": ["url"]},
            [
                {"field": "reference_types.dimension", "added": [], "removed": ["url"]},
                {"field": "reference_types.metric", "added": ["url"], "removed": []},
            ],
        ),
        (
            ["b", "a", "a"],
            ["a", "b"],
            {"metric": ["b", "a", "a"]},
            {"segment": [], "metric": ["a", "b"]},
            [],
        ),
        (["url"], ["url"], {"dimension": ["url"]}, {"dimension": ["url"]}, []),
        (
            ["url"],
            [],
            {"dimension": ["url"]},
            {"dimension": []},
            [
                {"field": "references", "added": [], "removed": ["url"]},
                {"field": "reference_types.dimension", "added": [], "removed": ["url"]},
            ],
        ),
        (["url"], ["url"], {}, {}, []),
        (["url"], ["url"], {}, {"metric": ["url"]}, []),
        (["url"], ["url"], {"dimension": ["url"]}, {}, []),
        (
            ["old"],
            ["new"],
            {},
            {"metric": ["new"]},
            [
                {"field": "references", "added": ["new"], "removed": ["old"]},
            ],
        ),
        (
            ["old"],
            ["new"],
            {"metric": ["old"]},
            {},
            [
                {"field": "references", "added": ["new"], "removed": ["old"]},
            ],
        ),
        (
            ["old"],
            ["new"],
            {"metric": ["old"]},
            {"metric": ["new"]},
            [
                {"field": "references", "added": ["new"], "removed": ["old"]},
                {"field": "reference_types.metric", "added": ["new"], "removed": ["old"]},
            ],
        ),
        (
            ["url"],
            ["url"],
            {"dimension": ["url"], "metric": ["url"]},
            {"metric": ["url"]},
            [
                {"field": "reference_types.dimension", "added": [], "removed": ["url"]},
            ],
        ),
    ],
)
def test_typed_reference_set_comparison(kind, old_refs, new_refs, old_types, new_types, expected):
    factory, collection = (_segment, "segments") if kind == "segment" else (_calc, "calcs")
    old = _impl(
        **{collection: [factory("consumer", references=old_refs, reference_types=old_types)]}
    )
    new = _impl(
        **{collection: [factory("consumer", references=new_refs, reference_types=new_types)]}
    )
    changes = diff_implementations(old, new)
    assert changes["added"] == changes["removed"] == []
    assert changes["modified"] == (
        [
            {
                "id": "consumer",
                "type": kind,
                "name": "Segment" if kind == "segment" else "Calc",
                "fields": expected,
            }
        ]
        if expected
        else []
    )


def test_typed_metadata_availability_is_per_matched_entity():
    old = _impl(
        segments=[
            _segment("typed", references=["url"], reference_types={"dimension": ["url"]}),
            _segment("legacy", references=["url"]),
            _segment("loses-metadata", references=["url"], reference_types={"dimension": ["url"]}),
        ]
    )
    new = _impl(
        segments=[
            _segment("typed", references=["url"], reference_types={"metric": ["url"]}),
            _segment("legacy", references=["url"], reference_types={"metric": ["url"]}),
            _segment("loses-metadata", references=["url"]),
        ]
    )
    assert [entry["id"] for entry in diff_implementations(old, new)["modified"]] == ["typed"]
