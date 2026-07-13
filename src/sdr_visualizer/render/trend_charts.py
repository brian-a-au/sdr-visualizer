"""Server-rendered SVG sparklines for the Trend view (SPEC 0.5.0).

Charts are built in Python from numeric aggregate values and fixed labels
only — no snapshot text ever enters the SVG strings, which is what makes
them safe to inline into the template with |safe. The client draws nothing.
"""

from __future__ import annotations

from typing import Any

_WIDTH = 220
_HEIGHT = 48
_PAD = 6

# (aggregate key, chart label) in display order. Labels are fixed English
# strings; the derived-fields chart is skipped when the series is all zero
# (it is a CJA-only concept and an all-zero AA chart is noise).
CHART_SPECS = (
    ("total", "Components"),
    ("metrics", "Metrics"),
    ("dimensions", "Dimensions"),
    ("derived_fields", "Derived"),
    ("segments", "Segments"),
    ("calculated_metrics", "Calc metrics"),
    ("orphans", "Orphans"),
    ("no_description", "No description"),
    ("edges", "Reference edges"),
)


def sparkline_svg(values: list[float | int]) -> str:
    """One inline SVG polyline over the value series."""
    if not values:
        return ""
    lo = min(values)
    hi = max(values)
    span = (hi - lo) or 1
    step = (_WIDTH - 2 * _PAD) / max(len(values) - 1, 1)
    points = " ".join(
        f"{_PAD + i * step:.1f},{_HEIGHT - _PAD - (v - lo) / span * (_HEIGHT - 2 * _PAD):.1f}"
        for i, v in enumerate(values)
    )
    return (
        f'<svg class="sparkline" viewBox="0 0 {_WIDTH} {_HEIGHT}" '
        f'width="{_WIDTH}" height="{_HEIGHT}" role="img" aria-hidden="true">'
        f'<polyline points="{points}" fill="none" stroke="#1a1a1a" stroke-width="1.5" />'
        "</svg>"
    )


def build_trend_charts(trend: dict[str, Any]) -> list[dict[str, Any]]:
    """One chart dict per aggregate: {label, first, last, svg}."""
    rows = [s["aggregates"] for s in trend["snapshots"]]
    charts: list[dict[str, Any]] = []
    for key, label in CHART_SPECS:
        values = [int(r.get(key, 0)) for r in rows]
        if key == "derived_fields" and max(values) == 0:
            continue
        charts.append(
            {
                "label": label,
                "first": values[0],
                "last": values[-1],
                "svg": sparkline_svg(values),
            }
        )
    return charts
