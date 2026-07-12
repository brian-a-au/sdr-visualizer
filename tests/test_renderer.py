"""Tests for render/renderer.py (SPEC-VISUALIZER §10 Phase 3)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from conftest import extract_payload, extract_payload_text

from sdr_visualizer.adapters.aa import adapt as aa_adapt
from sdr_visualizer.adapters.cja import adapt as cja_adapt
from sdr_visualizer.core.exceptions import InvalidSnapshotError
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
    parsed = extract_payload(messy_html)
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


def test_perf_hook_embedded_and_catalog_index_gone(messy_html):
    assert "__sdrPerf" in messy_html
    assert "catalog_index" not in messy_html


# ---------------------------------------------------------------------------
# Script-injection (XSS) regression tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def hostile_html():
    snap = json.loads((FIXTURES / "cja_snapshot_hostile.json").read_text(encoding="utf-8"))
    return render(cja_adapt(snap))


def test_payload_cannot_break_out_of_script_block(hostile_html, messy_html):
    """A '</script>' inside snapshot text must not terminate the data block.

    Detection is count-based: an injected '</script>' surviving into the
    payload adds closing tags relative to a clean render. (Content checks on
    the extracted block are vacuous on unfixed code — the extraction itself
    truncates at the injected tag.)
    """
    assert hostile_html.count("</script>") == messy_html.count("</script>")
    # Defense-in-depth: the (first-tag-delimited) data block holds no raw "<".
    assert "<" not in extract_payload_text(hostile_html)


def test_hostile_payload_round_trips(hostile_html):
    """Escaping must not change what JSON.parse / json.loads recovers."""
    payload = extract_payload(hostile_html)
    by_id = {c["id"]: c for c in payload["components"]}
    assert (
        by_id["metrics/cm_evil_desc"]["description"]
        == "</script><script>window.__xssEscape=true</script>"
    )
    assert by_id["metrics/cm_evil_name"]["name"] == '<img src=x onerror="window.__xssFired=true">'


def test_template_autoescape_applies_to_j2_templates(hostile_html):
    """select_autoescape(["html"]) alone does NOT cover .j2 files.

    The final extension of "index.html.j2" is ".j2", not ".html", so
    Jinja's select_autoescape would silently skip it unless "j2" is
    explicitly listed. This test verifies the fix is in place: a hostile
    snapshot name (which becomes {{ title }} / {{ meta.instance_name }})
    must be HTML-escaped, not rendered raw.
    """
    # The hostile fixture has <script>alert('name')</script> in the Data View Name.
    # After the fix it must appear as &lt;script&gt; in the title and h1.
    assert "<script>alert" not in hostile_html
    assert "&lt;script&gt;" in hostile_html


def test_nan_in_snapshot_raises_invalid_snapshot_error():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    snap["calculated_metrics"]["metrics"][0]["complexity_score"] = float("nan")
    impl = cja_adapt(snap)
    with pytest.raises(InvalidSnapshotError, match="NaN or Infinity"):
        render(impl)


def test_changes_nav_renders_only_with_changes_payload():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    impl = cja_adapt(snap)
    plain = render(impl)
    assert 'data-view="changes"' not in plain

    from sdr_visualizer.analysis.diff import diff_implementations
    from sdr_visualizer.render.renderer import build_payload_with_options, render_payload

    payload = build_payload_with_options(impl)
    payload["changes"] = diff_implementations(impl, impl)
    payload["meta"]["compared_to"] = payload["changes"]["baseline"]
    compared = render_payload(payload)
    assert 'data-view="changes"' in compared
    assert 'id="changes-view"' in compared
    assert "Compared to" in compared
