"""Tests for analysis/segment_tree.py (SPEC-VISUALIZER §10 Phase 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdr_visualizer.adapters.aa import adapt as aa_adapt
from sdr_visualizer.adapters.cja import adapt as cja_adapt
from sdr_visualizer.analysis.segment_tree import parse_segment_tree
from sdr_visualizer.core.models import Segment

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def cja_messy():
    return cja_adapt(json.loads((FIXTURES / "cja_snapshot_messy.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def aa_messy():
    return aa_adapt(json.loads((FIXTURES / "aa_snapshot_messy.json").read_text(encoding="utf-8")))


def _make_segment(definition: dict) -> Segment:
    return Segment(
        id="seg_test",
        name="Test",
        description=None,
        definition=definition,
        nesting_depth=0,
        container_types=[],
    )


# ---------------------------------------------------------------------------
# Hand-built shapes
# ---------------------------------------------------------------------------


def test_simple_container_with_streq_leaf():
    seg = _make_segment(
        {
            "func": "container",
            "context": "event",
            "pred": {
                "func": "streq",
                "val": {"func": "attr", "name": "variables/evar1"},
                "str": "match",
            },
        }
    )
    tree = parse_segment_tree(seg)
    assert tree["kind"] == "container"
    assert tree["context"] == "event"
    leaf = tree["child"]
    assert leaf["kind"] == "criterion"
    assert leaf["op"] == "streq"
    assert leaf["target_id"] == "variables/evar1"
    assert leaf["value"] == "match"
    assert "variables/evar1" in leaf["refs"]


def test_logical_and_with_args():
    seg = _make_segment(
        {
            "func": "and",
            "args": [
                {"func": "eq", "val": "v1"},
                {"func": "eq", "val": "v2"},
            ],
        }
    )
    tree = parse_segment_tree(seg)
    assert tree["kind"] == "logical"
    assert tree["op"] == "and"
    assert len(tree["children"]) == 2
    assert all(c["kind"] == "criterion" for c in tree["children"])


def test_unknown_func_falls_back_gracefully():
    seg = _make_segment({"func": "weird-experimental-op", "extra": True})
    tree = parse_segment_tree(seg)
    assert tree["kind"] == "unknown"
    assert tree["func"] == "weird-experimental-op"


def test_empty_definition_returns_unknown():
    seg = _make_segment({})
    tree = parse_segment_tree(seg)
    assert tree["kind"] == "unknown"


def test_non_mapping_definition_returns_unknown():
    tree = parse_segment_tree(_make_segment(["unexpected", "shape"]))

    assert tree == {"kind": "unknown", "func": None, "raw_keys": []}


def test_container_without_predicate_preserves_unspecified_scope():
    tree = parse_segment_tree(_make_segment({"func": "container"}))

    assert tree["kind"] == "container"
    assert tree["context"] == "unspecified"
    assert tree["child"] == {"kind": "unknown", "func": None, "raw_keys": []}


def test_context_wrapper_preserves_scope_around_criterion():
    tree = parse_segment_tree(
        _make_segment(
            {
                "context": "visits",
                "pred": {"func": "eq", "val": "returning"},
            }
        )
    )

    assert tree["kind"] == "container"
    assert tree["context"] == "visits"
    assert tree["child"]["summary"] == "value equals 'returning'"


def test_logical_scalar_and_predicate_shapes_become_children():
    scalar = parse_segment_tree(_make_segment({"func": "and", "args": "unexpected"}))
    negated = parse_segment_tree(
        _make_segment({"func": "not", "pred": {"func": "exists", "val": "value"}})
    )

    assert scalar["children"] == [{"kind": "unknown", "func": None, "raw_keys": []}]
    assert negated["op"] == "not"
    assert negated["children"][0]["summary"] == "value exists 'value'"


def test_metric_criterion_with_numeric_value_reports_reference():
    tree = parse_segment_tree(
        _make_segment(
            {
                "func": "gt",
                "val": {"func": "metric", "name": "metrics/orders"},
                "num": 5,
            }
        )
    )

    assert tree["target_id"] == "metrics/orders"
    assert tree["target_label"] == "metrics/orders"
    assert tree["value"] == 5
    assert tree["refs"] == ["metrics/orders"]
    assert tree["summary"] == "metrics/orders > 5"


def test_criterion_without_literal_has_value_free_summary():
    tree = parse_segment_tree(
        _make_segment({"func": "exists", "val": {"func": "attr", "name": "variables/evar1"}})
    )

    assert tree["value"] is None
    assert tree["summary"] == "variables/evar1 exists"


def test_unknown_criterion_target_degrades_to_value_label():
    tree = parse_segment_tree(
        _make_segment({"func": "exists", "val": {"func": "literal", "value": "x"}})
    )

    assert tree["target_id"] is None
    assert tree["target_label"] == "value"
    assert tree["refs"] == []
    assert tree["summary"] == "value exists"


# ---------------------------------------------------------------------------
# Real fixtures
# ---------------------------------------------------------------------------


def test_cja_deep_segment_unwinds_eight_containers(cja_messy):
    seg = next(s for s in cja_messy.segments if s.id == "segments/seg_qualified_lead_v3")
    tree = parse_segment_tree(seg)
    # Walk down the container chain and count how many layers we pass.
    depth = 0
    node = tree
    while node.get("kind") == "container":
        depth += 1
        node = node["child"]
    assert depth == 8
    assert node["kind"] == "criterion"
    assert node["op"] == "streq"


def test_aa_segment_with_nested_container_and_combinator(aa_messy):
    seg = next(s for s in aa_messy.segments if s.id == "s_returning")
    tree = parse_segment_tree(seg)
    # Outer wrapper has version + container; the parser unwraps to the
    # container.
    assert tree["kind"] == "container"
    assert tree["context"] == "visitors"
    inner = tree["child"]
    assert inner["kind"] == "logical"
    assert inner["op"] == "and"
    assert len(inner["children"]) == 2
    assert all(c["kind"] == "container" for c in inner["children"])


def test_every_real_segment_parses_without_error(cja_messy, aa_messy):
    for seg in [*cja_messy.segments, *aa_messy.segments]:
        tree = parse_segment_tree(seg)
        assert tree.get("kind") in {"container", "logical", "criterion", "segment_ref", "unknown"}


def test_canonical_segment_root_unwraps_to_container():
    # The Adobe Analytics 2.0 / CJA segments API returns this exact root
    # shape; it must unwrap to the container, not collapse to an empty ref.
    seg = _make_segment(
        {
            "func": "segment",
            "version": [1, 0, 0],
            "container": {
                "func": "container",
                "context": "visits",
                "pred": {
                    "func": "streq",
                    "val": {"func": "attr", "name": "variables/evar1"},
                    "str": "match",
                },
            },
        }
    )
    tree = parse_segment_tree(seg)
    assert tree["kind"] == "container"
    assert tree["context"] == "visits"
    assert tree["child"]["kind"] == "criterion"


def test_plain_segment_ref_still_parses():
    seg = _make_segment({"func": "segment", "name": "segments/other"})
    tree = parse_segment_tree(seg)
    assert tree["kind"] == "segment_ref"
    assert tree["segment_id"] == "segments/other"
