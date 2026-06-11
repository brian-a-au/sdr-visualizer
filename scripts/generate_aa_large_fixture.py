"""Synthesize a ~1,000-component AA fixture for performance testing.

Mirrors the aa_auto_sdr output shape so the existing AA adapter accepts
it without modification. Distribution roughly:

  dimensions:        500 (mix of evars and props)
  metrics:           300 (events)
  calculated_metrics: 50
  segments:          50  (mix of shallow + deep, hits/visits/visitors)
  classifications:   80  (attached as tags to dimensions)

Run via:

    uv run python scripts/generate_aa_large_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "tests" / "fixtures" / "aa_snapshot_large.json"


def _dimension(idx: int) -> dict:
    is_prop = idx % 5 == 0
    name_kind = "prop" if is_prop else "evar"
    return {
        "id": f"variables/{name_kind}{idx:04d}",
        "name": f"AA Dimension {idx:04d}",
        "description": f"Auto-generated AA dimension {idx:04d}." if idx % 6 != 0 else "-",
        "type": "string",
        "polarity": None,
        "owner_id": f"user-{idx % 20}",
        "tags": [],
        "created": "2025-09-01T00:00:00Z",
        "modified": "2026-04-25T09:14:00Z",
        "extra": {
            "allocation": "most-recent" if not is_prop else None,
            "expiration": "visit" if not is_prop else None,
        },
    }


def _metric(idx: int) -> dict:
    return {
        "id": f"metrics/event{idx:04d}",
        "name": f"AA Metric {idx:04d}",
        "description": f"Auto-generated AA metric {idx:04d}." if idx % 4 != 0 else "-",
        "type": "integer",
        "polarity": "positive" if idx % 7 != 0 else "neutral",
        "owner_id": f"user-{idx % 20}",
        "tags": ["custom"] if idx % 9 == 0 else [],
        "created": "2025-09-01T00:00:00Z",
        "modified": "2026-04-25T09:14:00Z",
    }


def _classification(idx: int) -> dict:
    parent_idx = (idx % 80) + 1
    return {
        "id": f"classifications/cls_{idx:04d}",
        "name": f"Classification {idx:04d}",
        "parent": f"variables/evar{parent_idx:04d}",
    }


def _segment(idx: int) -> dict:
    deep = idx % 11 == 0
    if deep:
        definition = {
            "version": [1, 0, 0],
            "container": {
                "context": "visitors",
                "func": "container",
                "pred": {
                    "func": "and",
                    "args": [
                        {
                            "func": "container",
                            "context": "visits",
                            "pred": {"func": "eq", "val": "v1"},
                        },
                        {
                            "func": "container",
                            "context": "hits",
                            "pred": {"func": "eq", "val": "h1"},
                        },
                    ],
                },
            },
        }
    else:
        definition = {
            "version": [1, 0, 0],
            "container": {
                "context": "hits",
                "func": "container",
                "pred": {"func": "eq", "val": f"value_{idx}"},
            },
        }
    return {
        "id": f"s_seg_{idx:04d}",
        "name": f"AA Segment {idx:04d}",
        "description": f"Auto-generated AA segment {idx:04d}.",
        "definition": definition,
        "owner_id": f"user-{idx % 20}",
        "created": "2025-09-01T00:00:00Z",
        "modified": "2026-04-25T09:14:00Z",
    }


def _calc_metric(idx: int) -> dict:
    a = f"metrics/event{1 + (idx * 3) % 300:04d}"
    b = f"metrics/event{1 + (idx * 5) % 300:04d}"
    return {
        "id": f"cm_aa_calc_{idx:04d}",
        "name": f"AA Calc {idx:04d}",
        "description": f"Auto-generated AA calc {idx:04d}.",
        "definition": {"formula": {"func": "divide", "args": [a, b]}},
        "attribution": "last-touch",
        "allocation": "linear",
        "complexity_score": float(10 + (idx % 60)),
        "owner_id": f"user-{idx % 20}",
        "created": "2025-09-01T00:00:00Z",
        "modified": "2026-04-25T09:14:00Z",
    }


def main() -> None:
    snapshot = {
        "report_suite": {"rsid": "large.synthetic.aa", "name": "Synthetic Large AA"},
        "captured_at": "2026-04-25T09:14:00Z",
        "tool_version": "1.0.0",
        "dimensions": [_dimension(i) for i in range(1, 501)],
        "metrics": [_metric(i) for i in range(1, 301)],
        "calculated_metrics": [_calc_metric(i) for i in range(1, 51)],
        "segments": [_segment(i) for i in range(1, 51)],
        "classifications": [_classification(i) for i in range(1, 81)],
        "virtual_report_suites": [],
    }
    TARGET.write_text(json.dumps(snapshot), encoding="utf-8")
    total = (
        len(snapshot["dimensions"])
        + len(snapshot["metrics"])
        + len(snapshot["calculated_metrics"])
        + len(snapshot["segments"])
    )
    print(f"wrote {TARGET} ({total} components)")


if __name__ == "__main__":
    main()
