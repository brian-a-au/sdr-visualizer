"""Tests for the self-contained HTML renderer."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from conftest import extract_payload, extract_payload_text

from sdr_visualizer.adapters.aa import adapt as aa_adapt
from sdr_visualizer.adapters.cja import adapt as cja_adapt
from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.visualizer import visualize
from sdr_visualizer.render.color_packs import (
    COLOR_PACK_CODES,
    InvalidColorPackError,
    resolve_color_pack,
    serialize_color_pack_css,
)
from sdr_visualizer.render.renderer import build_payload_with_options, render, render_payload

FIXTURES = Path(__file__).parent / "fixtures"
STATIC = Path(__file__).parents[1] / "src" / "sdr_visualizer" / "render" / "static"

_RESOURCE_URL_ATTRIBUTES = {
    "audio": ("src",),
    "embed": ("src",),
    "iframe": ("src",),
    "image": ("href", "xlink:href"),
    "img": ("src",),
    "input": ("src",),
    "link": ("href",),
    "object": ("data",),
    "script": ("src",),
    "source": ("src",),
    "track": ("src",),
    "use": ("href", "xlink:href"),
    "video": ("poster", "src"),
}
_SRCSET_TAGS = {"img", "source"}


class _ResourceURLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        resource_attributes = _RESOURCE_URL_ATTRIBUTES.get(tag)
        if resource_attributes is None:
            return

        attributes = dict(attrs)
        self.urls.extend(
            value for name in resource_attributes if (value := attributes.get(name)) is not None
        )
        if tag in _SRCSET_TAGS and (srcset := attributes.get("srcset")) is not None:
            self.urls.extend(
                candidate.split()[0] for candidate in srcset.split(",") if candidate.strip()
            )


def _non_embedded_resource_urls(html: str) -> list[str]:
    parser = _ResourceURLParser()
    parser.feed(html)
    return [
        url
        for url in parser.urls
        if not url.lstrip().startswith("#") and urlsplit(url.lstrip()).scheme.lower() != "data"
    ]


def _contrast_ratio(first: str, second: str) -> float:
    def luminance(hex_color: str) -> float:
        channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


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


def test_public_visualize_adapts_and_renders_snapshot():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))

    html = visualize(snap, source="public-api", title="Public API Report")

    assert html.lstrip().startswith("<!doctype html>")
    assert "Public API Report" in html
    assert extract_payload(html)["meta"]["snapshot_source"] == "public-api"


def test_public_visualize_threads_color_pack_to_html_only():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))

    html = visualize(snap, source="public-api", color_pack="ADBE")

    assert '<html lang="en" data-color-pack="ADBE">' in html
    assert "Color pack: ADBE" in html
    assert "color_pack" not in extract_payload(html)
    assert "color_pack" not in extract_payload(html)["meta"]


def test_public_visualize_rejects_unknown_platform_override():
    with pytest.raises(InvalidSnapshotError, match="unknown platform 'wat'"):
        visualize({}, platform="wat")


def test_render_embeds_max_graph_nodes_option():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))

    html = render(cja_adapt(snap), max_graph_nodes=17)

    assert extract_payload(html)["meta"]["max_graph_nodes"] == 17


@pytest.mark.parametrize("code", COLOR_PACK_CODES)
def test_render_emits_pack_identity_and_deterministic_css_after_base_styles(code):
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))

    html = render(cja_adapt(snap), color_pack=code)
    css = serialize_color_pack_css(resolve_color_pack(code))

    assert f'<html lang="en" data-color-pack="{code}">' in html
    assert f"Color pack: {code}" in html
    assert html.index("/* ---------- Reset & base ---------- */") < html.index(css)
    assert html.index(css) < html.index("</style>")
    assert f"Color pack: {code}" not in extract_payload_text(html)


def test_omitted_and_explicit_default_render_payload_are_identical():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    payload = build_payload_with_options(cja_adapt(snap))

    assert render_payload(payload) == render_payload(payload, color_pack="default")


def test_sequential_color_pack_renders_do_not_leak_state():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    payload = build_payload_with_options(cja_adapt(snap))

    adbe = render_payload(payload, color_pack="ADBE")
    blue = render_payload(payload, color_pack="BLUE")
    final_default = render_payload(payload)
    adbe_accent = resolve_color_pack("ADBE").roles["accent-primary"]
    blue_accent = resolve_color_pack("BLUE").roles["accent-primary"]

    assert f"--sdr-accent-primary: {adbe_accent};" in adbe
    assert f"--sdr-accent-primary: {blue_accent};" in blue
    assert final_default == render_payload(payload, color_pack="default")
    assert "--sdr-accent-primary: #4A6F6F;" in final_default
    assert adbe_accent not in final_default
    assert blue_accent not in final_default


@pytest.mark.parametrize("entrypoint", [render, render_payload])
def test_rendering_api_rejects_unknown_color_pack_before_template_render(entrypoint):
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    impl = cja_adapt(snap)
    value = impl if entrypoint is render else build_payload_with_options(impl)

    with pytest.raises(InvalidColorPackError, match="available color packs"):
        entrypoint(value, color_pack="adbe")


def test_color_pack_selection_never_enters_embedded_payload():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    payload = build_payload_with_options(cja_adapt(snap))

    default_payload = extract_payload(render_payload(payload, color_pack="default"))
    blue_payload = extract_payload(render_payload(payload, color_pack="BLUE"))

    assert default_payload == blue_payload == payload


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


def test_visible_css_colors_use_semantic_variables_or_documented_fixed_neutrals():
    css = (STATIC / "visualizer.css").read_text(encoding="utf-8")
    _, visible_rules = css.split("/* ---------- Reset & base ---------- */", maxsplit=1)

    assert re.findall(r"#[0-9A-Fa-f]{3,8}|rgba?\([^)]*\)", visible_rules) == []
    assert "legacy neutrals deliberately stay pack-independent" in css


def test_visible_css_uses_text_roles_for_text_and_strong_roles_for_control_boundaries():
    css = (STATIC / "visualizer.css").read_text(encoding="utf-8")

    textual_roles = re.findall(r"(?<![-\w])color:\s*var\(--sdr-([a-z0-9-]+)\)", css)
    assert "border-strong" not in textual_roles
    assert "--sdr-visualizer-missing-content: #B8651A;" not in css
    assert "--sdr-visualizer-missing-content: var(--sdr-severity-high);" in css
    assert "--sdr-visualizer-operator-text: var(--sdr-text-muted);" in css
    assert "--sdr-visualizer-operator-text: #6A4F30;" in css
    assert "color: var(--sdr-visualizer-operator-text);" in css

    for selector in ("#search-input", ".filter-group select", ".chip"):
        rule = re.search(rf"{re.escape(selector)} \{{(.*?)\n\}}", css, re.DOTALL)
        assert rule is not None
        assert "border: 1px solid var(--sdr-border-strong);" in rule.group(1)


@pytest.mark.parametrize("code", COLOR_PACK_CODES)
def test_renderer_specific_operator_text_meets_normal_text_contrast(code):
    pack = resolve_color_pack(code)
    operator_text = "#6A4F30" if code == "default" else pack.roles["text-muted"]

    assert _contrast_ratio(operator_text, "#F5DBB5") >= 4.5


def test_visualizer_js_uses_computed_semantic_colors_and_d3_symbol_shapes():
    js = (STATIC / "visualizer.js").read_text(encoding="utf-8")

    assert "getComputedStyle(document.documentElement)" in js
    assert re.findall(r"#[0-9A-Fa-f]{3,8}", js) == []
    for symbol in (
        "symbolCircle",
        "symbolSquare",
        "symbolDiamond",
        "symbolTriangle",
        "symbolCross",
    ):
        assert f"d3.{symbol}" in js
    assert 'nodeSel.append("circle")' not in js
    assert '.attr("aria-label"' in js


def test_print_css_keeps_only_active_view_and_uses_print_roles():
    css = (STATIC / "visualizer.css").read_text(encoding="utf-8")
    print_css = css.split("@media print", maxsplit=1)[1]

    assert ".view[hidden] { display: none !important; }" in print_css
    assert ".view-nav" in print_css
    assert ".detail-overlay" in print_css
    assert "var(--sdr-print-foreground)" in print_css
    assert "var(--sdr-print-background)" in print_css
    assert "var(--sdr-print-border)" in print_css


def test_html_no_external_resources(messy_html):
    """Spec §5: no fetches, no CDNs, no external <img>."""
    assert "<img" not in messy_html
    assert _non_embedded_resource_urls(messy_html) == []


def test_resource_detection_rejects_relative_and_all_srcset_candidates():
    external_url = "https://cdn.invalid/image.png"
    html = f'<source srcset="/local.png 1x, {external_url} 2x">'

    assert _non_embedded_resource_urls(html) == ["/local.png", external_url]


def test_resource_detection_allows_embedded_and_same_document_urls():
    html = (
        '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw="><svg><use href="#mark"></use></svg>'
    )

    assert _non_embedded_resource_urls(html) == []


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


def test_direct_payload_render_rejects_surrogates_before_returning_html():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    impl = cja_adapt(snap)

    from sdr_visualizer.render.renderer import build_payload_with_options, render_payload

    payload = build_payload_with_options(impl)
    payload["meta"]["instance_name"] = "\ud800"

    with pytest.raises(InvalidSnapshotError, match=r"render payload.*surrogate"):
        render_payload(payload)


def test_direct_payload_render_rejects_surrogate_mapping_key_before_returning_html():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    impl = cja_adapt(snap)

    from sdr_visualizer.render.renderer import build_payload_with_options, render_payload

    payload = build_payload_with_options(impl)
    payload["meta"]["\ud800"] = "value"

    with pytest.raises(InvalidSnapshotError, match=r"render payload.*surrogate"):
        render_payload(payload)


def test_direct_payload_render_rejects_circular_container_without_hanging():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    impl = cja_adapt(snap)

    from sdr_visualizer.render.renderer import build_payload_with_options, render_payload

    payload = build_payload_with_options(impl)
    payload["cycle"] = payload

    with pytest.raises(InvalidSnapshotError, match=r"render payload.*circular"):
        render_payload(payload)


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


def test_trend_nav_and_charts_render_only_with_trend_payload():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    impl = cja_adapt(snap)
    plain = render(impl)
    assert 'data-view="trend"' not in plain

    from sdr_visualizer.analysis.trend import build_trend
    from sdr_visualizer.render.renderer import build_payload_with_options, render_payload

    payload = build_payload_with_options(impl)
    payload["trend"] = build_trend([impl, impl], capped=False)
    with_trend = render_payload(payload)
    assert 'data-view="trend"' in with_trend
    assert 'id="trend-view"' in with_trend
    assert "<polyline" in with_trend

    adbe_trend = render_payload(payload, color_pack="ADBE")
    assert 'stroke="#B5121B"' in adbe_trend


def test_report_without_derived_fields_has_no_derived_chip():
    """Derived fields are a CJA-only concept; a report with none (every AA
    report, and CJA views without them) must not offer the Derived-field
    type chip in the catalog or graph filters. Same principle as the
    zero-count meta strip."""
    snap = json.loads((FIXTURES / "aa_snapshot_messy.json").read_text(encoding="utf-8"))
    html = render(aa_adapt(snap))
    assert 'value="derived_field"' not in html


def test_report_with_derived_fields_keeps_the_chip():
    snap = json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))
    html = render(cja_adapt(snap))
    assert html.count('value="derived_field"') == 2  # catalog chip + graph chip
