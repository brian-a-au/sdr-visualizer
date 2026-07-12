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

    clones = []
    for i, record in enumerate(metrics):
        if i % 25 == 0 and isinstance(record, dict):
            clone = copy.deepcopy(record)
            clone["id"] = f"{clone.get('id') or f'metrics/clone_{i}'}_added"
            clone["name"] = f"{clone.get('name') or 'Metric'} (added)"
            clones.append(clone)
    out["metrics"] = metrics + clones

    dimensions = list(out.get("dimensions") or [])
    out["dimensions"] = [r for i, r in enumerate(dimensions) if i % 20 != 0]

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministically mutate a CJA snapshot.")
    parser.add_argument("input", help="CJA snapshot JSON to mutate")
    parser.add_argument("--output", required=True, help="Where to write the mutated snapshot")
    args = parser.parse_args()
    snapshot = json.loads(Path(args.input).read_text(encoding="utf-8"))
    Path(args.output).write_text(json.dumps(mutate(snapshot)), encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
