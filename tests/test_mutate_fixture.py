"""Mutation script tests (loaded via importlib; scripts/ is not a package)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"

spec = importlib.util.spec_from_file_location(
    "mutate_fixture", REPO / "scripts" / "mutate_fixture.py"
)
mutate_fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mutate_fixture)
mutate = mutate_fixture.mutate
disjoint_ids = mutate_fixture.disjoint_ids
high_churn_series = mutate_fixture.high_churn_series


def _clean_snapshot():
    return json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))


def test_mutate_is_deterministic():
    a = mutate(_clean_snapshot())
    b = mutate(_clean_snapshot())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_iterative_mutation_keeps_component_ids_unique():
    snap = _clean_snapshot()
    for _ in range(5):
        snap = mutate(snap)
        ids = [r["id"] for r in snap["metrics"] if isinstance(r, dict)]
        assert len(ids) == len(set(ids)), "duplicate metric ids after iterative mutation"


def test_mutate_does_not_modify_its_input():
    snap = _clean_snapshot()
    before = json.dumps(snap, sort_keys=True)
    mutate(snap)
    assert json.dumps(snap, sort_keys=True) == before


def _component_ids(snapshot):
    return {
        *(r["id"] for r in snapshot.get("metrics", [])),
        *(r["id"] for r in snapshot.get("dimensions", [])),
        *(r["component_id"] for r in snapshot.get("derived_fields", {}).get("fields", [])),
        *(r["segment_id"] for r in snapshot.get("segments", {}).get("segments", [])),
        *(r["metric_id"] for r in snapshot.get("calculated_metrics", {}).get("metrics", [])),
    }


def test_disjoint_ids_is_deterministic_complete_and_non_mutating():
    snap = _clean_snapshot()
    before = json.dumps(snap, sort_keys=True)
    first = disjoint_ids(snap, namespace="comparison")
    second = disjoint_ids(snap, namespace="comparison")

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert _component_ids(first).isdisjoint(_component_ids(snap))
    assert len(_component_ids(first)) == len(_component_ids(snap))
    assert json.dumps(snap, sort_keys=True) == before


def test_high_churn_series_has_fixed_inventory_and_disjoint_neighbors():
    snap = _clean_snapshot()
    series = high_churn_series(snap, count=60)
    expected_count = len(_component_ids(snap))

    assert len(series) == 60
    assert all(len(_component_ids(item)) == expected_count for item in series)
    assert all(
        _component_ids(left).isdisjoint(_component_ids(right))
        for left, right in zip(series, series[1:], strict=False)
    )
    assert json.dumps(series, sort_keys=True) == json.dumps(
        high_churn_series(snap, count=60), sort_keys=True
    )
