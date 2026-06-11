"""Edge-case tests against the minimal CJA fixture.

Per SPEC-VISUALIZER §10 Phase 3: confirm edge cases (empty implementation,
no segments, no calc metrics).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import extract_payload

from sdr_visualizer.adapters.cja import adapt
from sdr_visualizer.render.renderer import render

FIXTURES = Path(__file__).parent / "fixtures"
MINIMAL = FIXTURES / "cja_snapshot_minimal.json"


@pytest.fixture(scope="module")
def minimal_impl():
    return adapt(json.loads(MINIMAL.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def minimal_html(minimal_impl):
    return render(minimal_impl)


@pytest.fixture(scope="module")
def minimal_payload(minimal_html):
    return extract_payload(minimal_html)


def test_minimal_implementation_has_no_segments_or_calc_metrics(minimal_impl):
    assert minimal_impl.segments == []
    assert minimal_impl.calculated_metrics == []


def test_minimal_total_components_is_five(minimal_impl):
    total = (
        len(minimal_impl.metrics)
        + len(minimal_impl.dimensions)
        + len(minimal_impl.derived_fields)
        + len(minimal_impl.segments)
        + len(minimal_impl.calculated_metrics)
    )
    assert total == 5


def test_minimal_renders_without_error(minimal_html):
    """The catalog and graph view should not crash with no segments or
    calc metrics."""
    assert minimal_html.startswith("<!doctype html>")
    assert 'id="catalog-view"' in minimal_html
    assert 'id="graph-view"' in minimal_html


def test_minimal_payload_segment_and_formula_trees_are_empty(minimal_payload):
    assert minimal_payload["segment_trees"] == {}
    assert minimal_payload["formula_trees"] == {}


def test_minimal_graph_has_only_orphan_nodes(minimal_payload):
    """No segments / calc metrics means no edges."""
    assert minimal_payload["graph"]["edges"] == []
    entries = [
        *minimal_payload["components"],
        *minimal_payload["segments"],
        *minimal_payload["calculated_metrics"],
    ]
    assert all(e.get("in_degree", 0) == 0 for e in entries)


def test_minimal_normalizes_empty_and_dash_descriptions(minimal_impl):
    """The CJA adapter coerces both '-' and '' to None."""
    metrics_missing = [m for m in minimal_impl.metrics if m.description is None]
    dims_missing = [d for d in minimal_impl.dimensions if d.description is None]
    assert len(metrics_missing) == 1  # the '-' description
    assert len(dims_missing) == 1  # the '' description
