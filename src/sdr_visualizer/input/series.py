"""Snapshot series listing for --trend (SPEC 0.5.0).

Visualizer-only: this file is NOT in the sdr-grader vendor set (CLAUDE.md
vendors only loader/detect/shell_out). It reuses the vendored loader's
private helpers so ordering and parsing rules stay byte-identical to the
single-snapshot directory mode without modifying the vendored file.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.input.loader import (
    STDIN_TOKEN,
    _extract_timestamp,
    _load_from_file,
    _parse_iso_timestamp,
)

# Hard window cap (SPEC 0.5.0): bounds build time and payload size.
TREND_SNAPSHOT_CAP = 60


def list_snapshot_series(
    path_or_token: str,
    *,
    at: str | None = None,
    cap: int = TREND_SNAPSHOT_CAP,
) -> tuple[list[tuple[dict[str, Any], str]], bool]:
    """Ordered (snapshot, source) entries for every parseable snapshot.

    Oldest to newest, windowed by `at` (inclusive end) and capped to the
    `cap` most recent. Unparseable files are skipped with a stderr warning.
    Returns (entries, capped).
    """
    if path_or_token == STDIN_TOKEN:
        raise InvalidSnapshotError("--trend requires a snapshot directory; stdin is not supported")
    directory = Path(path_or_token)
    if not directory.is_dir():
        raise InvalidSnapshotError(
            f"--trend requires a snapshot directory; {path_or_token} is not one"
        )
    candidates = sorted(directory.glob("*.json"))
    if not candidates:
        raise InvalidSnapshotError(f"no .json snapshots found in {directory}")

    # Same scale rules as the vendored loader's _pick_snapshot: filename
    # timestamps when any file carries one; mtime only when none do.
    annotated = [(p, _extract_timestamp(p)) for p in candidates]
    stamped = [(p, ts) for p, ts in annotated if ts is not None]
    if stamped and len(stamped) < len(annotated):
        for p, ts in annotated:
            if ts is None:
                print(
                    f"sdr-visualizer: warning: skipping {p.name}: no filename timestamp "
                    "while other snapshots have one",
                    file=sys.stderr,
                )
    if not stamped:
        stamped = [(p, datetime.fromtimestamp(p.stat().st_mtime)) for p in candidates]

    if at is not None:
        target = _parse_iso_timestamp(at)
        if target is None:
            raise InvalidSnapshotError(
                f"--at value {at!r} is not a recognized timestamp; "
                "use ISO-8601 (e.g. 2026-04-25 or 2026-04-25T09:14)."
            )
        stamped = [(p, ts) for p, ts in stamped if ts <= target]

    stamped.sort(key=lambda pair: pair[1])

    # Select the `cap` most recent *parseable* snapshots, loading newest-first
    # so a run of malformed recent files can't consume window slots that valid
    # older snapshots would otherwise fill. Corrupt files (bad JSON, bad
    # encoding, or values the parser rejects such as an oversized integer) are
    # skipped with a warning rather than aborting the trend. The window is
    # checked *before* loading, so once it is full we never read an older
    # candidate — reads stay bounded to the window regardless of how large or
    # corrupt the older archive is. `capped` therefore records that older
    # candidate files exist beyond the window, not that they are parseable.
    entries: list[tuple[dict[str, Any], str]] = []
    capped = False
    for path, _ts in reversed(stamped):
        if len(entries) >= cap:
            capped = True  # older candidate files exist beyond the window
            break
        try:
            snapshot, source = _load_from_file(path)
        except (InvalidSnapshotError, ValueError) as exc:
            print(f"sdr-visualizer: warning: skipping {path.name}: {exc}", file=sys.stderr)
            continue
        entries.append((snapshot, source))
    entries.reverse()  # restore oldest-to-newest ordering

    if capped:
        print(
            f"sdr-visualizer: warning: trend window capped at {cap} snapshots; "
            "older history omitted",
            file=sys.stderr,
        )

    if len(entries) < 2:
        raise InvalidSnapshotError("--trend needs at least 2 parseable snapshots in the directory")
    return entries, capped
