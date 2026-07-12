"""Trend section tests (0.5.0 trend mode)."""

from __future__ import annotations

from sdr_visualizer.analysis.trend import build_trend, compute_aggregates
from sdr_visualizer.core.models import CalculatedMetric, Component, Implementation


def _component(cid, name="Metric", **overrides):
    base = dict(
        id=cid,
        name=name,
        description="d",
        component_type="metric",
        data_type="integer",
        polarity=None,
        created_at=None,
        modified_at=None,
        owner=None,
        tags=[],
        platform_specific={},
    )
    base.update(overrides)
    return Component(**base)


def _calc(cid, name="Calc", references=(), **overrides):
    base = dict(
        id=cid,
        name=name,
        description="d",
        formula={},
        formula_text="",
        attribution_model=None,
        allocation=None,
        complexity_score=0.0,
        references=list(references),
    )
    base.update(overrides)
    return CalculatedMetric(**base)


def _impl(metrics=(), dimensions=(), calcs=(), taken_at="2026-06-01 00:00:00", source="snap.json"):
    return Implementation(
        platform="cja",
        instance_id="dv_trend",
        instance_name="Trend",
        snapshot_taken_at=taken_at,
        snapshot_source=source,
        adapter_version="1.0.0",
        metrics=list(metrics),
        dimensions=list(dimensions),
        segments=[],
        calculated_metrics=list(calcs),
        derived_fields=[],
        raw={},
    )


def test_aggregates_counts_types_orphans_descriptions_edges():
    impl = _impl(
        metrics=[
            _component("metrics/m1"),
            _component("metrics/m2", description=None),
        ],
        dimensions=[_component("dims/d1", component_type="dimension")],
        calcs=[_calc("cm/c1", references=["metrics/m1"])],
    )
    agg = compute_aggregates(impl)
    assert agg["total"] == 4
    assert agg["metrics"] == 2
    assert agg["dimensions"] == 1
    assert agg["calculated_metrics"] == 1
    assert agg["derived_fields"] == 0
    assert agg["segments"] == 0
    assert agg["edges"] == 1
    # m1 is referenced by cm/c1; m2, d1, and the calc itself are orphans.
    assert agg["orphans"] == 3
    assert agg["no_description"] == 1


def test_build_trend_snapshots_carry_identity_and_aggregates():
    a = _impl(metrics=[_component("metrics/m1")], taken_at="2026-05-01 00:00:00", source="a.json")
    b = _impl(
        metrics=[_component("metrics/m1"), _component("metrics/m2")],
        taken_at="2026-06-01 00:00:00",
        source="b.json",
    )
    trend = build_trend([a, b], capped=False)
    assert [s["source"] for s in trend["snapshots"]] == ["a.json", "b.json"]
    assert [s["taken_at"] for s in trend["snapshots"]] == [
        "2026-05-01 00:00:00",
        "2026-06-01 00:00:00",
    ]
    assert [s["aggregates"]["total"] for s in trend["snapshots"]] == [1, 2]
    assert trend["capped"] is False


def test_build_trend_intervals_are_pairwise_id_lists():
    a = _impl(metrics=[_component("metrics/m1"), _component("metrics/m3")], taken_at="t1")
    b = _impl(
        metrics=[_component("metrics/m1", name="Renamed"), _component("metrics/m2")],
        taken_at="t2",
    )
    c = _impl(metrics=[_component("metrics/m1", name="Renamed")], taken_at="t3")
    trend = build_trend([a, b, c], capped=True)
    assert len(trend["intervals"]) == 2
    first, second = trend["intervals"]
    assert first["from"] == "t1" and first["to"] == "t2"
    assert first["added"] == ["metrics/m2"]
    assert first["removed"] == ["metrics/m3"]
    assert first["modified"] == ["metrics/m1"]
    assert second["added"] == []
    assert second["removed"] == ["metrics/m2"]
    assert second["modified"] == []
    assert trend["capped"] is True


def test_interval_from_to_fall_back_to_source_when_no_timestamp():
    a = _impl(metrics=[_component("metrics/m1")], taken_at=None, source="old.json")
    b = _impl(metrics=[_component("metrics/m1")], taken_at=None, source="new.json")
    trend = build_trend([a, b], capped=False)
    assert trend["intervals"][0]["from"] == "old.json"
    assert trend["intervals"][0]["to"] == "new.json"
