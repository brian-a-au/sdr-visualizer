"""Self-contained HTML renderer for normalized CJA lineage."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from jinja2 import Environment, PackageLoader

from sdr_visualizer import __version__ as VISUALIZER_VERSION
from sdr_visualizer.analysis.lineage_layout import LineageLayoutError
from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.lineage import LineageTopology
from sdr_visualizer.core.structure_limits import validate_unicode_scalars
from sdr_visualizer.render.color_packs import resolve_color_pack, serialize_color_pack_css
from sdr_visualizer.render.lineage_payload import build_payload

_env = Environment(loader=PackageLoader("sdr_visualizer.render", "templates"), autoescape=True)
_DEFAULT_TITLE = "CJA Dataset Lineage"
_MAX_TITLE_LENGTH = 512
_BIDI_CONTROLS = frozenset(
    "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)


def render(
    topology: LineageTopology, *, title: str | None = None, color_pack: str = "default"
) -> str:
    """Build one deterministic, offline report from normalized topology."""
    return render_payload(build_payload(topology), title=title, color_pack=color_pack)


def render_payload(
    payload: dict[str, Any], *, title: str | None = None, color_pack: str = "default"
) -> str:
    """Render a prepared payload, retaining the same defensive boundary."""
    pack = resolve_color_pack(color_pack)
    document_title = _validated_title(title)
    validate_unicode_scalars(payload, label="CJA lineage render payload")
    try:
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=False,
        ).replace("<", "\\u003c")
        template = _env.get_template("cja_lineage.html.j2")
        return template.render(
            title=document_title,
            base_css=_read_static("visualizer.css"),
            css=_read_static("cja_lineage.css"),
            graph_js=_read_static("cja_lineage_graph.js"),
            roles_js=_read_static("cja_lineage_roles.js"),
            js=_read_static("cja_lineage.js"),
            color_pack_css=serialize_color_pack_css(pack),
            color_pack=pack.code,
            visualizer_version=VISUALIZER_VERSION,
            payload_json=payload_json,
            scope_label=payload["scope_label"],
            coverage=payload["coverage"],
            counts=payload["counts"],
            gating=payload["gating"],
            empty=payload["empty"],
            gated=payload["gating"]["full_graph_gated"],
        )
    except (KeyError, TypeError, ValueError):
        raise LineageLayoutError("CJA lineage render failed") from None


def _validated_title(title: str | None) -> str:
    value = _DEFAULT_TITLE if title is None else title
    if not isinstance(value, str) or not value or value != value.strip():
        raise LineageLayoutError("CJA lineage render failed")
    try:
        validate_unicode_scalars(value, label="CJA lineage report title")
    except InvalidSnapshotError:
        raise LineageLayoutError("CJA lineage render failed") from None
    if len(value) > _MAX_TITLE_LENGTH or any(
        ord(character) < 32 or 127 <= ord(character) <= 159 for character in value
    ):
        raise LineageLayoutError("CJA lineage render failed")
    if any(character in _BIDI_CONTROLS for character in value):
        raise LineageLayoutError("CJA lineage render failed")
    return value


@cache
def _read_static(name: str) -> str:
    files = resources.files("sdr_visualizer.render") / "static"
    return (files / name).read_text(encoding="utf-8")


__all__ = ["render", "render_payload"]
