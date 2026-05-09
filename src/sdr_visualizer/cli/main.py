"""CLI entry point (SPEC-VISUALIZER §7).

v0.1 Phase 3 wires Mode 1 (file path). Other modes (directory, shell-out,
stdin) are added in Phase 8.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sdr_visualizer import __version__
from sdr_visualizer.cli.exit_codes import (
    INPUT_VALIDATION_ERROR,
    RUNTIME_ERROR,
    SUCCESS,
)
from sdr_visualizer.core.exceptions import (
    InvalidSnapshotError,
    UnknownPlatformError,
)
from sdr_visualizer.core.visualizer import build_implementation
from sdr_visualizer.input.loader import STDIN_TOKEN, load_snapshot
from sdr_visualizer.render.renderer import render


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        snapshot, source = load_snapshot(args.path, at=args.at)
        impl = build_implementation(
            snapshot,
            source=source,
            platform=args.platform,
        )
        html = render(impl, title=args.title)
    except (InvalidSnapshotError, UnknownPlatformError) as exc:
        print(f"sdr-visualizer: {exc}", file=sys.stderr)
        return INPUT_VALIDATION_ERROR
    except Exception as exc:  # pragma: no cover — unexpected runtime failure
        print(f"sdr-visualizer: unexpected error: {exc}", file=sys.stderr)
        return RUNTIME_ERROR

    output_path = _resolve_output_path(args.output, impl.instance_id)
    output_path.write_text(html, encoding="utf-8")
    if not args.quiet:
        print(f"sdr-visualizer: wrote {output_path}", file=sys.stderr)
    return SUCCESS


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sdr-visualizer",
        description="Generate a visual catalog of an Adobe CJA / AA implementation.",
    )
    p.add_argument(
        "path",
        help=(
            "Snapshot file path, snapshot directory, or '-' for stdin. "
            "Mode 3 (--dataview / --rsid) is wired in Phase 8."
        ),
    )
    p.add_argument(
        "--platform",
        choices=["cja", "aa"],
        help="Override platform auto-detection.",
    )
    p.add_argument(
        "--at",
        help="When path is a directory, pick the snapshot closest to (and not after) this timestamp.",
    )
    p.add_argument(
        "--output",
        help="HTML output path. Default: ./visualize-{instance_id}-{timestamp}.html",
    )
    p.add_argument("--title", help="Override the document title.")
    p.add_argument("--quiet", action="store_true", help="Suppress informational stderr output.")
    p.add_argument("--version", action="version", version=f"sdr-visualizer {__version__}")
    return p


def _resolve_output_path(explicit: str | None, instance_id: str) -> Path:
    if explicit:
        return Path(explicit)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    safe_instance = instance_id.replace("/", "_")
    return Path(f"./visualize-{safe_instance}-{timestamp}.html")


__all__ = ["main", "STDIN_TOKEN"]
