"""Snapshot series listing for --trend (SPEC 0.5.0).

Visualizer-only: this file is NOT in the sdr-grader vendor set (CLAUDE.md
vendors only loader/detect/shell_out). It reuses the vendored loader's
private helpers so ordering and parsing rules stay byte-identical to the
single-snapshot directory mode without modifying the vendored file.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar, overload

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.input.loader import (
    STDIN_TOKEN,
    _extract_timestamp,
    _load_from_file,
    _mtime_timestamp,
    _parse_iso_timestamp,
    list_snapshot_candidates,
)

# Hard window cap (SPEC 0.5.0): bounds build time and payload size.
TREND_SNAPSHOT_CAP = 60
SnapshotEntry = tuple[dict[str, Any], str]
Selected = TypeVar("Selected")


@overload
def list_snapshot_series(
    path_or_token: str,
    *,
    at: str | None = None,
    cap: int = TREND_SNAPSHOT_CAP,
    transform: None = None,
) -> tuple[list[SnapshotEntry], bool]:
    pass


@overload
def list_snapshot_series(
    path_or_token: str,
    *,
    at: str | None = None,
    cap: int = TREND_SNAPSHOT_CAP,
    transform: Callable[[dict[str, Any], str], Selected | None],
) -> tuple[list[Selected], bool]:
    pass


def list_snapshot_series(
    path_or_token: str,
    *,
    at: str | None = None,
    cap: int = TREND_SNAPSHOT_CAP,
    transform: Callable[[dict[str, Any], str], Any | None] | None = None,
) -> tuple[list[Any], bool]:
    """Return oldest-to-newest usable entries selected from a directory.

    ``transform`` keeps this input layer adapter-agnostic: it may convert a
    loaded snapshot to a caller-owned value or return ``None`` to skip it.
    Only successful transformed results consume cap slots. Without a
    transform, the returned values are ``(snapshot, source)`` tuples.
    """
    if path_or_token == STDIN_TOKEN:
        raise InvalidSnapshotError("--trend requires a snapshot directory; stdin is not supported")
    directory = Path(path_or_token)
    if not directory.is_dir():
        raise InvalidSnapshotError(
            f"--trend requires a snapshot directory; {path_or_token} is not one"
        )
    candidates = list_snapshot_candidates(directory)
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
        stamped = [(p, _mtime_timestamp(p)) for p in candidates]

    if at is not None:
        target = _parse_iso_timestamp(at)
        if target is None:
            raise InvalidSnapshotError(
                f"--at value {at!r} is not a recognized timestamp; "
                "use ISO-8601 (e.g. 2026-04-25 or 2026-04-25T09:14)."
            )
        stamped = [(p, ts) for p, ts in stamped if ts <= target]
        if len(stamped) < 2:
            # --at is the limiting factor here, not corruption; say so plainly
            # instead of the generic "needs at least 2 parseable" below.
            raise InvalidSnapshotError(
                f"--trend found only {len(stamped)} snapshot(s) at or before {at!r}; "
                "at least 2 are required (widen or drop --at)"
            )

    stamped.sort(key=lambda pair: pair[1])

    # Load newest-first so corrupt or non-selected recent files cannot consume
    # slots that usable older snapshots should fill. Continue through ignored
    # candidates after the window fills: capped is true only when a 61st usable
    # selected result proves that history was actually omitted.
    entries: list[Any] = []
    capped = False
    for path, _ts in reversed(stamped):
        try:
            snapshot, source = _load_from_file(path)
        except (InvalidSnapshotError, ValueError) as exc:
            print(f"sdr-visualizer: warning: skipping {path.name}: {exc}", file=sys.stderr)
            continue
        selected = (snapshot, source) if transform is None else transform(snapshot, source)
        if selected is None:
            continue
        if len(entries) >= cap:
            capped = True
            break
        entries.append(selected)
    entries.reverse()  # restore oldest-to-newest ordering

    if capped:
        print(
            f"sdr-visualizer: warning: trend window capped at {cap} snapshots; "
            "older history omitted",
            file=sys.stderr,
        )

    if len(entries) < 2:
        raise InvalidSnapshotError("--trend needs at least 2 usable snapshots in the directory")
    return entries, capped
