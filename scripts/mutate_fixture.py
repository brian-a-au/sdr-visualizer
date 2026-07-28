"""Derive a deterministically mutated copy of a CJA snapshot.

Used by the comparative perf gates so the diff path is measured against a
realistic change volume (roughly 10% of components renamed, dropped, or
added). No randomness: mutations are index based, so the same input always
yields the same output.

Standalone use:

    uv run python scripts/mutate_fixture.py tests/fixtures/cja_snapshot_large.json \
        --output /tmp/cja_snapshot_large_mutated.json
"""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def mutate(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a mutated deep copy: renames, description edits, drops, adds."""
    out = copy.deepcopy(snapshot)

    metrics = list(out.get("metrics") or [])
    for i, record in enumerate(metrics):
        if not isinstance(record, dict):
            continue
        if i % 10 == 0:
            record["name"] = f"{record.get('name') or record.get('id') or 'Metric'} (renamed)"
        if i % 15 == 0:
            record["description"] = "Mutated description for the comparative perf gate."

    existing_ids = {str(r.get("id")) for r in metrics if isinstance(r, dict)}
    clones = []
    for i, record in enumerate(metrics):
        if i % 25 == 0 and isinstance(record, dict):
            clone = copy.deepcopy(record)
            base_id = f"{clone.get('id') or f'metrics/clone_{i}'}_added"
            candidate = base_id
            k = 2
            while candidate in existing_ids:
                candidate = f"{base_id}{k}"
                k += 1
            existing_ids.add(candidate)
            clone["id"] = candidate
            clone["name"] = f"{clone.get('name') or 'Metric'} (added)"
            clones.append(clone)
    out["metrics"] = metrics + clones

    dimensions = list(out.get("dimensions") or [])
    out["dimensions"] = [r for i, r in enumerate(dimensions) if i % 20 != 0]

    return out


def _record_groups(snapshot: dict[str, Any]) -> list[tuple[list[Any], str]]:
    """Return every component record list paired with its identifier key."""
    groups: list[tuple[list[Any], str]] = []
    for top_level, identifier in (("metrics", "id"), ("dimensions", "id")):
        records = snapshot.get(top_level)
        if isinstance(records, list):
            groups.append((records, identifier))
    for section_name, records_key, identifier in (
        ("derived_fields", "fields", "component_id"),
        ("segments", "segments", "segment_id"),
        ("calculated_metrics", "metrics", "metric_id"),
    ):
        section = snapshot.get(section_name)
        if isinstance(section, dict):
            records = section.get(records_key)
            if isinstance(records, list):
                groups.append((records, identifier))
    return groups


def disjoint_ids(snapshot: dict[str, Any], *, namespace: str = "disjoint") -> dict[str, Any]:
    """Return a deep copy whose component inventory has no IDs in common.

    Explicit reference lists are remapped with the inventory so the
    synthetic snapshot retains realistic graph pressure.
    """
    if not namespace:
        raise ValueError("namespace must not be empty")
    out = copy.deepcopy(snapshot)
    id_map: dict[str, str] = {}
    for records, identifier in _record_groups(out):
        for record in records:
            if not isinstance(record, dict) or identifier not in record:
                continue
            old_id = str(record[identifier])
            new_id = f"{namespace}/{old_id}"
            id_map[old_id] = new_id
            record[identifier] = new_id

    reference_keys = {
        "component_references",
        "dimension_references",
        "metric_references",
        "other_segment_references",
        "segment_references",
    }
    for records, _ in _record_groups(out):
        for record in records:
            if not isinstance(record, dict):
                continue
            for key in reference_keys:
                values = record.get(key)
                if isinstance(values, list):
                    record[key] = [id_map.get(str(value), value) for value in values]

    data_view = out.get("data_view")
    if isinstance(data_view, dict) and data_view.get("id"):
        data_view["id"] = f"{namespace}/{data_view['id']}"
    return out


def high_churn_series(snapshot: dict[str, Any], *, count: int = 60) -> list[dict[str, Any]]:
    """Build a fixed-size series whose adjacent inventories are disjoint."""
    if count < 1:
        raise ValueError("count must be >= 1")
    start = datetime(2026, 1, 1)
    series = []
    for index in range(count):
        current = disjoint_ids(snapshot, namespace=f"churn-{index:02d}")
        metadata = current.get("metadata")
        if isinstance(metadata, dict):
            metadata["Generation Timestamp"] = (start + timedelta(days=index)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        series.append(current)
    return series


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministically mutate a CJA snapshot.")
    parser.add_argument("input", help="CJA snapshot JSON to mutate")
    parser.add_argument("--output", help="Where to write a single mutated snapshot")
    series_group = parser.add_mutually_exclusive_group()
    series_group.add_argument(
        "--series",
        type=int,
        help="Write N progressively mutated snapshots (snapshot_2026-01-01T00-00-00.json style names)",
    )
    series_group.add_argument(
        "--high-churn-series",
        type=int,
        help="Write N fixed-size snapshots with disjoint adjacent component IDs",
    )
    parser.add_argument("--output-dir", help="Directory for --series output")
    args = parser.parse_args()
    snapshot = json.loads(Path(args.input).read_text(encoding="utf-8"))

    series_count = args.high_churn_series if args.high_churn_series is not None else args.series
    if series_count is not None:
        if series_count < 1:
            parser.error("series count must be >= 1")
        if series_count > 336:
            parser.error("series count must be <= 336 (month-spill filename scheme)")
        if not args.output_dir:
            parser.error("series output requires --output-dir")
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if args.high_churn_series is not None:
            snapshots = high_churn_series(snapshot, count=series_count)
        else:
            snapshots = []
            current = snapshot
            for _ in range(series_count):
                snapshots.append(current)
                current = mutate(current)
        for i, current in enumerate(snapshots):
            name = f"snapshot_2026-{i // 28 + 1:02d}-{i % 28 + 1:02d}T00-00-00.json"
            (out_dir / name).write_text(json.dumps(current), encoding="utf-8")
            print(f"wrote {out_dir / name}")
        return 0

    if not args.output:
        parser.error("--output is required without --series")
    Path(args.output).write_text(json.dumps(mutate(snapshot)), encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
