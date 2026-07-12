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


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministically mutate a CJA snapshot.")
    parser.add_argument("input", help="CJA snapshot JSON to mutate")
    parser.add_argument("--output", help="Where to write a single mutated snapshot")
    parser.add_argument(
        "--series",
        type=int,
        help="Write N progressively mutated snapshots (snapshot_2026-01-01T00-00-00.json style names)",
    )
    parser.add_argument("--output-dir", help="Directory for --series output")
    args = parser.parse_args()
    snapshot = json.loads(Path(args.input).read_text(encoding="utf-8"))

    if args.series:
        if args.series > 336:
            parser.error("--series must be <= 336 (month-spill filename scheme)")
        if not args.output_dir:
            parser.error("--series requires --output-dir")
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        current = snapshot
        for i in range(args.series):
            name = f"snapshot_2026-{i // 28 + 1:02d}-{i % 28 + 1:02d}T00-00-00.json"
            (out_dir / name).write_text(json.dumps(current), encoding="utf-8")
            print(f"wrote {out_dir / name}")
            current = mutate(current)
        return 0

    if not args.output:
        parser.error("--output is required without --series")
    Path(args.output).write_text(json.dumps(mutate(snapshot)), encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
