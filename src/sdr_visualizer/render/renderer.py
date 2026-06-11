"""Top-level renderer (SPEC-VISUALIZER §5).

Takes an Implementation, builds the embedded payload, and emits a single
self-contained HTML string. CSS and JS are inlined; the JSON payload sits
in a `<script type="application/json">` block that the client-side JS
reads on load. No external resources, no fetches, no CDNs.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from sdr_visualizer.core.models import Implementation
from sdr_visualizer.render.data_payload import build_payload

_env = Environment(
    loader=PackageLoader("sdr_visualizer.render", "templates"),
    # "j2" must be listed explicitly: select_autoescape matches on the final
    # extension only, so "index.html.j2" does NOT match ["html"]. Without
    # listing "j2", {{ title }} / {{ meta.instance_name }} etc. render raw,
    # allowing XSS via hostile snapshot metadata.
    autoescape=select_autoescape(["html", "j2"]),
)


def render(
    impl: Implementation,
    *,
    title: str | None = None,
    exclude_orphans: bool = False,
    max_graph_nodes: int | None = None,
) -> str:
    """Build the HTML for an Implementation."""
    payload = build_payload(impl)
    payload["meta"]["exclude_orphans_default"] = bool(exclude_orphans)
    if max_graph_nodes is not None:
        payload["meta"]["max_graph_nodes"] = int(max_graph_nodes)
    return _render_from_payload(payload, title=title)


def build_payload_with_options(
    impl: Implementation,
    *,
    exclude_orphans: bool = False,
    max_graph_nodes: int | None = None,
) -> dict[str, Any]:
    """Build the payload (mostly for `--json` output)."""
    payload = build_payload(impl)
    payload["meta"]["exclude_orphans_default"] = bool(exclude_orphans)
    if max_graph_nodes is not None:
        payload["meta"]["max_graph_nodes"] = int(max_graph_nodes)
    return payload


def render_payload(payload: dict[str, Any], *, title: str | None = None) -> str:
    """Render directly from a pre-built payload (used by tests)."""
    return _render_from_payload(payload, title=title)


def _render_from_payload(payload: dict[str, Any], *, title: str | None) -> str:
    template = _env.get_template("index.html.j2")
    css = _read_static("visualizer.css")
    js = _read_static("visualizer.js")
    d3_js = _read_static("d3.min.js")
    document_title = title or f"{payload['meta']['instance_name']} — Implementation Visualizer"
    return template.render(
        title=document_title,
        meta=payload["meta"],
        css=css,
        js=js,
        d3_js=d3_js,
        # Snapshot text is untrusted: a description containing "</script>"
        # would otherwise terminate the data block and become live markup
        # (stored XSS). Escaping "<" as < is invisible to JSON.parse.
        payload_json=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).replace(
            "<", "\\u003c"
        ),
        # Snapshot stats for the header strip.
        component_count=payload["meta"]["component_count"],
        metric_count=sum(1 for c in payload["components"] if c["type"] == "metric"),
        dimension_count=sum(1 for c in payload["components"] if c["type"] == "dimension"),
        derived_field_count=sum(1 for c in payload["components"] if c["type"] == "derived_field"),
        segment_count=len(payload["segments"]),
        calc_metric_count=len(payload["calculated_metrics"]),
    )


def _read_static(name: str) -> str:
    files = resources.files("sdr_visualizer.render") / "static"
    return (files / name).read_text(encoding="utf-8")
