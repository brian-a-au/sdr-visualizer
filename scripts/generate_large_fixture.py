"""Synthesize a large CJA fixture for performance testing (1,200 components at --scale 1.0).

Mirrors the cja_auto_sdr output shape so the existing CJA adapter accepts
it without modification. Distribution roughly:

  metrics:        300 (some currency, some integer)
  dimensions:     500 (mix of evar / prop)
  derived_fields: 300
  segments:       60  (mix of shallow + a few deep)
  calc metrics:   40

Run via:

    uv run python scripts/generate_large_fixture.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "tests" / "fixtures" / "cja_snapshot_large.json"


def _metric(idx: int) -> dict:
    is_currency = idx % 3 == 0
    return {
        "id": f"metrics/cm_metric_{idx:04d}",
        "name": f"Metric {idx:04d}",
        "description": f"Auto-generated metric {idx:04d}." if idx % 4 != 0 else "-",
        "type": "decimal" if is_currency else "integer",
        "polarity": "positive" if idx % 5 != 0 else "neutral",
        "owner": f"a.user{idx % 12}@example.com",
        "tags": ["custom"] if idx % 7 == 0 else [],
        "created_at": "2025-09-01T00:00:00Z",
        "modified_at": "2026-04-25T09:14:00Z",
        "precision": 2 if is_currency else 0,
    }


def _dimension(idx: int) -> dict:
    is_prop = idx % 4 == 0
    return {
        "id": f"variables/{'prop' if is_prop else 'evar'}{idx:04d}",
        "name": f"Dimension {idx:04d}",
        "description": f"Auto-generated dimension {idx:04d}." if idx % 5 != 0 else "-",
        "type": "string",
        "owner": f"a.user{idx % 12}@example.com",
        "tags": ["custom"] if idx % 6 == 0 else [],
        "created_at": "2025-09-01T00:00:00Z",
        "modified_at": "2026-04-25T09:14:00Z",
    }


def _derived_field(idx: int) -> dict:
    return {
        "component_id": f"derived/df_field_{idx:04d}",
        "component_name": f"Derived Field {idx:04d}",
        "description": f"Auto-generated derived field {idx:04d}.",
        "output_type": "string",
        "owner": f"a.user{idx % 8}@example.com",
        "tags": [],
        "created": "2025-09-01T00:00:00Z",
        "modified": "2026-04-25T09:14:00Z",
        "schema_field_count": 2,
    }


def _segment(idx: int) -> dict:
    deep = idx % 17 == 0
    if deep:
        # 6-level nested container chain so the segment_tree parser does
        # real work.
        definition = {
            "func": "container",
            "context": "event",
            "pred": {
                "func": "container",
                "context": "session",
                "pred": {
                    "func": "container",
                    "context": "person",
                    "pred": {
                        "func": "container",
                        "context": "event",
                        "pred": {
                            "func": "container",
                            "context": "session",
                            "pred": {
                                "func": "container",
                                "context": "person",
                                "pred": {
                                    "func": "streq",
                                    "val": {"func": "attr", "name": "variables/evar0001"},
                                    "str": "match",
                                },
                            },
                        },
                    },
                },
            },
        }
    else:
        definition = {
            "func": "container",
            "context": "event",
            "pred": {
                "func": "streq",
                "val": {"func": "attr", "name": f"variables/evar{1 + (idx % 50):04d}"},
                "str": f"value_{idx}",
            },
        }
    return {
        "segment_id": f"segments/seg_{idx:04d}",
        "segment_name": f"Segment {idx:04d}",
        "description": f"Auto-generated segment {idx:04d}.",
        "container_type": "event",
        "nesting_depth": 6 if deep else 2,
        "definition_json": json.dumps(definition),
        "dimension_references": [f"variables/evar{1 + (idx % 50):04d}"],
        "metric_references": [],
        "other_segment_references": [],
        "created": "2025-09-01T00:00:00Z",
        "modified": "2026-04-25T09:14:00Z",
        "owner": f"a.user{idx % 8}@example.com",
    }


def _calc_metric(idx: int) -> dict:
    metric_a = f"metrics/cm_metric_{1 + (idx * 3) % 300:04d}"
    metric_b = f"metrics/cm_metric_{1 + (idx * 5) % 300:04d}"
    formula = {
        "func": "divide",
        "col1": {"func": "metric", "name": metric_a},
        "col2": {"func": "metric", "name": metric_b},
    }
    return {
        "metric_id": f"calculatedMetrics/cm_calc_{idx:04d}",
        "metric_name": f"Calc Metric {idx:04d}",
        "description": f"Auto-generated calc metric {idx:04d}.",
        "formula_summary": f"Metric A {idx} / Metric B {idx}",
        "definition_json": json.dumps(formula),
        "metric_references": [metric_a, metric_b],
        "segment_references": [],
        "complexity_score": float(15 + (idx % 50)),
        "created": "2025-09-01T00:00:00Z",
        "modified": "2026-04-25T09:14:00Z",
        "owner": f"a.user{idx % 8}@example.com",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthesize a large CJA fixture for performance testing."
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Multiply the base component counts (1.0 = 1,200 components; "
        "1.67 = roughly the SPEC 6 2,000-component tier). "
        "Cross-references use hardcoded moduli, so scales above 1.0 leave the "
        "highest-index components unreferenced (orphans).",
    )
    parser.add_argument("--output", type=Path, default=TARGET, help="Fixture path to write.")
    args = parser.parse_args()

    n_metrics = round(300 * args.scale)
    n_dimensions = round(500 * args.scale)
    n_derived = round(300 * args.scale)
    n_segments = round(60 * args.scale)
    n_calc = round(40 * args.scale)

    snapshot = {
        "metadata": {
            "Data View ID": "dv_large_synthetic",
            "Data View Name": "Synthetic Large Implementation",
            "Generation Timestamp": "2026-04-25 09:14:00",
            "Tool Version": "3.5.17",
        },
        "data_view": {"id": "dv_large_synthetic"},
        "metrics": [_metric(i) for i in range(1, n_metrics + 1)],
        "dimensions": [_dimension(i) for i in range(1, n_dimensions + 1)],
        "derived_fields": {"fields": [_derived_field(i) for i in range(1, n_derived + 1)]},
        "segments": {"segments": [_segment(i) for i in range(1, n_segments + 1)]},
        "calculated_metrics": {"metrics": [_calc_metric(i) for i in range(1, n_calc + 1)]},
    }
    args.output.write_text(json.dumps(snapshot), encoding="utf-8")
    total = n_metrics + n_dimensions + n_derived + n_segments + n_calc
    print(f"wrote {args.output} ({total} components)")


if __name__ == "__main__":
    main()
