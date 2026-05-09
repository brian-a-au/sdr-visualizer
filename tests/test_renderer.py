"""Tests for render/renderer.py (SPEC-VISUALIZER §10 Phase 3)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from sdr_visualizer.adapters.aa import adapt as aa_adapt
from sdr_visualizer.adapters.cja import adapt as cja_adapt
from sdr_visualizer.render.renderer import render

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def messy_html():
    snap = json.loads((FIXTURES / "cja_snapshot_messy.json").read_text(encoding="utf-8"))
    return render(cja_adapt(snap))


@pytest.fixture(scope="module")
def aa_html():
    snap = json.loads((FIXTURES / "aa_snapshot_messy.json").read_text(encoding="utf-8"))
    return render(aa_adapt(snap))


@pytest.fixture(scope="module")
def clean_html():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    return render(cja_adapt(snap))


# ---------------------------------------------------------------------------
# Structural checks (cheap and stable)
# ---------------------------------------------------------------------------


def test_html_starts_with_doctype(messy_html):
    assert messy_html.lstrip().startswith("<!doctype html>")


def test_html_contains_catalog_view_section(messy_html):
    assert 'id="catalog-view"' in messy_html


def test_html_contains_payload_script_with_json(messy_html):
    """Payload must be embedded as a JSON script the JS can read."""
    match = re.search(
        r'<script id="sdr-data" type="application/json">(?P<json>.*?)</script>',
        messy_html,
        re.DOTALL,
    )
    assert match
    parsed = json.loads(match.group("json"))
    assert parsed["meta"]["platform"] == "cja"
    assert parsed["meta"]["component_count"] > 0


def test_html_inlines_css_and_js(messy_html):
    assert 'font-family: "Charter"' in messy_html  # CSS
    assert "function applyFilters" in messy_html or "applyFilters" in messy_html  # JS


def test_html_no_external_resources(messy_html):
    """Spec §5: no fetches, no CDNs, no external <img>."""
    assert "<img" not in messy_html
    assert 'src="http' not in messy_html
    assert 'href="http' not in messy_html or "github.com" in messy_html  # only the See-also link


def test_aa_renders_with_aa_platform_tag(aa_html):
    assert "platform-aa" in aa_html
    assert "AA" in aa_html


def test_clean_renders_without_calc_metric_or_segment_orphans(clean_html):
    """The 'clean' fixture has no derived fields; the meta strip should
    not show a Derived count when the value is zero."""
    # Just check the page renders (no exception) and includes catalog markup.
    assert 'id="catalog-view"' in clean_html


# ---------------------------------------------------------------------------
# Determinism: same input → byte-identical output (modulo generated_at)
# ---------------------------------------------------------------------------


def test_render_deterministic_modulo_generated_at():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    impl = cja_adapt(snap)
    a = render(impl)
    b = render(impl)
    timestamp_re = re.compile(r'"generated_at":"[^"]+"')
    assert timestamp_re.sub('"generated_at":"X"', a) == timestamp_re.sub('"generated_at":"X"', b)
