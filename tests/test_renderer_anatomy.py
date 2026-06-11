"""Phase 5 + 6 tests: HTML carries the data needed to render anatomy.

The actual anatomy DOM is built client-side in JS, so we can't fully
exercise it in pytest without a headless browser. We assert that:

  1. The HTML carries each segment's parsed tree under payload.segment_trees
  2. The HTML carries each calc metric's parsed formula under payload.formula_trees
  3. The CSS / JS hooks the anatomy depends on are present
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import extract_payload

from sdr_visualizer.adapters.cja import adapt
from sdr_visualizer.render.renderer import render

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def messy_html_and_payload():
    snap = json.loads((FIXTURES / "cja_snapshot_messy.json").read_text(encoding="utf-8"))
    impl = adapt(snap)
    html = render(impl)
    return html, extract_payload(html)


def test_every_segment_has_a_tree(messy_html_and_payload):
    _, payload = messy_html_and_payload
    seg_ids = {s["id"] for s in payload["segments"]}
    tree_ids = set(payload["segment_trees"].keys())
    assert seg_ids == tree_ids


def test_every_calc_metric_has_a_formula_tree(messy_html_and_payload):
    _, payload = messy_html_and_payload
    cm_ids = {c["id"] for c in payload["calculated_metrics"]}
    tree_ids = set(payload["formula_trees"].keys())
    assert cm_ids == tree_ids


def test_deep_segment_anatomy_unwinds(messy_html_and_payload):
    _, payload = messy_html_and_payload
    tree = payload["segment_trees"]["segments/seg_qualified_lead_v3"]
    depth = 0
    node = tree
    while node.get("kind") == "container":
        depth += 1
        node = node["child"]
    assert depth == 8
    assert node["kind"] == "criterion"


def test_anatomy_css_classes_are_in_html(messy_html_and_payload):
    """The CSS register Phase 5 added must ship with every render."""
    html, _ = messy_html_and_payload
    for cls in [
        ".anatomy-container",
        ".anatomy-logical-op",
        ".anatomy-criterion",
        ".anatomy-op-and",
        ".anatomy-op-or",
        ".formula-op-name",
        ".formula-args",
    ]:
        assert cls in html


def test_anatomy_js_renderers_are_in_html(messy_html_and_payload):
    html, _ = messy_html_and_payload
    assert "renderSegmentTree" in html
    assert "renderFormulaTree" in html


def test_aa_segments_also_have_trees():
    snap = json.loads((FIXTURES / "aa_snapshot_messy.json").read_text(encoding="utf-8"))
    from sdr_visualizer.adapters.aa import adapt as aa_adapt

    impl = aa_adapt(snap)
    html = render(impl)
    payload = extract_payload(html)
    seg_ids = {s["id"] for s in payload["segments"]}
    assert seg_ids == set(payload["segment_trees"].keys())
