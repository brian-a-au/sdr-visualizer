"""Phase 4 tests: HTML output includes graph view scaffold and inlined D3."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdr_visualizer.adapters.cja import adapt
from sdr_visualizer.render.renderer import render

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def messy_html():
    snap = json.loads((FIXTURES / "cja_snapshot_messy.json").read_text(encoding="utf-8"))
    return render(adapt(snap))


def test_graph_view_section_present(messy_html):
    assert 'id="graph-view"' in messy_html
    assert 'id="graph-canvas"' in messy_html


def test_d3_inlined(messy_html):
    """D3 should be embedded so the file works offline."""
    assert "https://d3js.org" in messy_html  # the d3 banner comment
    assert "d3.forceSimulation" in messy_html or "forceSimulation" in messy_html


def test_graph_nav_button_enabled(messy_html):
    """Phase 3 had it disabled; Phase 4 enables it."""
    nav_block = messy_html.split("</nav>")[0]
    assert 'data-view="graph"' in nav_block
    assert "disabled" not in nav_block.split('data-view="graph"')[0].split('class="view-button"')[-1]


def test_graph_payload_has_nodes_and_edges(messy_html):
    import re
    match = re.search(
        r'<script id="sdr-data" type="application/json">(?P<json>.*?)</script>',
        messy_html,
        re.DOTALL,
    )
    payload = json.loads(match.group("json"))
    assert payload["graph"]["nodes"]
    assert payload["graph"]["edges"]
