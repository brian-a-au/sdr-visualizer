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
