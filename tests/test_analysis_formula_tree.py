"""Tests for analysis/formula_tree.py (SPEC-VISUALIZER §10 Phase 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdr_visualizer.adapters.aa import adapt as aa_adapt
from sdr_visualizer.adapters.cja import adapt as cja_adapt
from sdr_visualizer.analysis.formula_tree import collect_metric_refs, parse_formula_tree
from sdr_visualizer.core.models import CalculatedMetric

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def cja_messy():
    return cja_adapt(json.loads((FIXTURES / "cja_snapshot_messy.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def aa_messy():
    return aa_adapt(json.loads((FIXTURES / "aa_snapshot_messy.json").read_text(encoding="utf-8")))


def _make_metric(formula: dict) -> CalculatedMetric:
    return CalculatedMetric(
        id="cm_test",
        name="Test",
        description=None,
        formula=formula,
        formula_text="",
        attribution_model=None,
        allocation=None,
        complexity_score=0.0,
    )


# ---------------------------------------------------------------------------
# CJA shape
# ---------------------------------------------------------------------------


def test_cja_divide_with_col1_col2():
    cm = _make_metric(
        {
            "func": "divide",
            "col1": {"func": "metric", "name": "metrics/revenue"},
            "col2": {"func": "metric", "name": "metrics/visits"},
        }
    )
    tree = parse_formula_tree(cm)
    assert tree["kind"] == "operation"
    assert tree["op"] == "divide"
    assert len(tree["args"]) == 2
    assert tree["args"][0] == {
        "kind": "metric_ref",
        "metric_id": "metrics/revenue",
        "label": "metrics/revenue",
    }
    assert collect_metric_refs(tree) == ["metrics/revenue", "metrics/visits"]


def test_cja_messy_revenue_per_visit_parses(cja_messy):
    cm = next(c for c in cja_messy.calculated_metrics if c.id.endswith("cm_revenue_per_visit"))
    tree = parse_formula_tree(cm)
    assert tree["op"] == "divide"
    refs = collect_metric_refs(tree)
    assert refs == ["metrics/revenue", "metrics/visits"]


# ---------------------------------------------------------------------------
# AA shape
# ---------------------------------------------------------------------------


def test_aa_divide_with_args_strings():
    cm = _make_metric({"func": "divide", "args": ["metrics/orders", "metrics/visits"]})
    tree = parse_formula_tree(cm)
    assert tree["kind"] == "operation"
    assert tree["op"] == "divide"
    assert collect_metric_refs(tree) == ["metrics/orders", "metrics/visits"]


def test_aa_messy_conversion_rate_parses(aa_messy):
    cm = next(c for c in aa_messy.calculated_metrics if c.id == "cm_conversion_rate")
    tree = parse_formula_tree(cm)
    assert tree["op"] == "divide"
    assert collect_metric_refs(tree) == ["metrics/orders", "metrics/visits"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_unknown_func_falls_back_gracefully():
    cm = _make_metric({"func": "exotic-op", "weight": 0.7})
    tree = parse_formula_tree(cm)
    assert tree["kind"] == "unknown"
    assert tree["func"] == "exotic-op"


def test_empty_formula_returns_unknown():
    cm = _make_metric({})
    tree = parse_formula_tree(cm)
    assert tree["kind"] == "unknown"


def test_constants_pass_through():
    cm = _make_metric({"func": "multiply", "args": [{"func": "metric", "name": "metrics/x"}, 100]})
    tree = parse_formula_tree(cm)
    assert tree["args"][1] == {"kind": "constant", "value": 100}


def test_bare_references_and_string_literals_are_distinguished():
    ref = parse_formula_tree(_make_metric("variables/evar1"))
    literal = parse_formula_tree(_make_metric("not a reference"))

    assert ref == {
        "kind": "metric_ref",
        "metric_id": "variables/evar1",
        "label": "variables/evar1",
    }
    assert literal == {"kind": "constant", "value": "not a reference"}


def test_non_mapping_formula_degrades_to_unknown():
    tree = parse_formula_tree(_make_metric(["unexpected", "shape"]))

    assert tree == {"kind": "unknown", "func": None, "raw_keys": []}


def test_segment_scope_and_nary_formula_collect_unique_nested_refs():
    tree = parse_formula_tree(
        _make_metric(
            {
                "func": "segment",
                "name": "segments/qualified",
                "formula": {
                    "func": "sum",
                    "args": ["metrics/orders", "metrics/orders", "metrics/revenue"],
                },
            }
        )
    )

    assert tree["kind"] == "segment_scope"
    assert tree["segment_id"] == "segments/qualified"
    assert tree["child"]["op"] == "sum"
    assert collect_metric_refs(tree) == ["metrics/orders", "metrics/revenue"]


def test_formula_wrapper_unwraps_real_tree():
    tree = parse_formula_tree(
        _make_metric({"formula": {"func": "metric", "name": "metrics/visits"}})
    )

    assert tree["kind"] == "metric_ref"
    assert tree["metric_id"] == "metrics/visits"


def test_reference_collection_ignores_empty_and_non_mapping_children():
    tree = {
        "kind": "operation",
        "args": [
            None,
            {"kind": "metric_ref", "metric_id": ""},
            {"kind": "metric_ref", "metric_id": "metrics/orders"},
        ],
    }

    assert collect_metric_refs(tree) == ["metrics/orders"]


def test_reference_collection_ignores_unknown_and_empty_segment_nodes():
    assert collect_metric_refs({"kind": "unknown"}) == []
    assert collect_metric_refs({"kind": "segment_scope", "child": None}) == []


def test_every_real_calc_metric_parses(cja_messy, aa_messy):
    for cm in [*cja_messy.calculated_metrics, *aa_messy.calculated_metrics]:
        tree = parse_formula_tree(cm)
        assert tree.get("kind") in {
            "operation",
            "metric_ref",
            "segment_scope",
            "constant",
            "unknown",
        }


# ---------------------------------------------------------------------------
# Fuzz-found regressions: malformed formula shapes must degrade gracefully,
# never raise a bare TypeError (see tests/test_adapter_fuzz.py).
# ---------------------------------------------------------------------------


def test_scalar_formula_args_degrade_to_empty_operation():
    # Fuzz-found (1.0.1): a formula node whose "args" is a scalar must not
    # crash tree building — degrade to an operation with no args, matching
    # _walk's never-raise design.
    tree = parse_formula_tree(_make_metric({"func": "add", "args": 7}))
    assert tree["kind"] == "operation"
    assert tree["args"] == []
