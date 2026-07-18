"""Sparkline generator tests (0.5.0 trend mode)."""

from __future__ import annotations

from sdr_visualizer.render.trend_charts import build_trend_charts, sparkline_svg


def test_empty_sparkline_has_no_markup():
    assert sparkline_svg([]) == ""


def test_sparkline_is_selfcontained_svg_polyline():
    svg = sparkline_svg([1, 5, 3])
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "<polyline" in svg
    assert "http" not in svg  # no external references, ever


def test_sparkline_flat_series_does_not_divide_by_zero():
    svg = sparkline_svg([4, 4, 4])
    assert "<polyline" in svg
    assert "nan" not in svg.lower()


def test_build_trend_charts_labels_first_last():
    trend = {
        "snapshots": [
            {
                "aggregates": {
                    "total": 10,
                    "metrics": 4,
                    "dimensions": 3,
                    "derived_fields": 0,
                    "segments": 2,
                    "calculated_metrics": 1,
                    "orphans": 5,
                    "no_description": 2,
                    "edges": 7,
                }
            },
            {
                "aggregates": {
                    "total": 12,
                    "metrics": 5,
                    "dimensions": 3,
                    "derived_fields": 0,
                    "segments": 2,
                    "calculated_metrics": 2,
                    "orphans": 4,
                    "no_description": 1,
                    "edges": 9,
                }
            },
        ],
        "intervals": [],
        "capped": False,
    }
    charts = build_trend_charts(trend)
    labels = [c["label"] for c in charts]
    assert labels[0] == "Components"
    assert "Derived" not in labels  # all-zero derived_fields chart is skipped
    total = charts[0]
    assert total["first"] == 10 and total["last"] == 12
    assert "<svg" in total["svg"]


def test_derived_chart_appears_when_nonzero():
    trend = {
        "snapshots": [
            {
                "aggregates": {
                    "total": 1,
                    "metrics": 0,
                    "dimensions": 0,
                    "derived_fields": 1,
                    "segments": 0,
                    "calculated_metrics": 0,
                    "orphans": 1,
                    "no_description": 0,
                    "edges": 0,
                }
            },
            {
                "aggregates": {
                    "total": 1,
                    "metrics": 0,
                    "dimensions": 0,
                    "derived_fields": 1,
                    "segments": 0,
                    "calculated_metrics": 0,
                    "orphans": 1,
                    "no_description": 0,
                    "edges": 0,
                }
            },
        ],
        "intervals": [],
        "capped": False,
    }
    assert "Derived" in [c["label"] for c in build_trend_charts(trend)]
