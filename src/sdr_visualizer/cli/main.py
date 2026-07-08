"""CLI entry point (SPEC-VISUALIZER §7).

Wires all four input modes:
  Mode 1: file path
  Mode 2: snapshot directory (latest, or `--at TIMESTAMP`)
  Mode 3: shell out to cja_auto_sdr (`--dataview ID`) or aa_auto_sdr (`--rsid ID`)
  Mode 4: stdin (path argument is `-`)
"""

from __future__ import annotations

import argparse
import json
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
from sdr_visualizer.input.shell_out import shell_aa, shell_cja
from sdr_visualizer.render.renderer import build_payload_with_options, render_payload


class _ArgumentParser(argparse.ArgumentParser):
    """argparse exits 2 on usage errors; SPEC §7 reserves the 0/1/3 contract
    and explicitly forbids 2, so remap usage problems to input-validation."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(INPUT_VALIDATION_ERROR)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not _exactly_one_input_source(args):
        parser.error(
            "provide exactly one of: snapshot path/directory/'-', --dataview ID, or --rsid ID"
        )

    try:
        snapshot, source = _load(args)
        impl = build_implementation(
            snapshot,
            source=source,
            platform=args.platform,
        )
        payload = build_payload_with_options(
            impl,
            exclude_orphans=args.exclude_orphans,
            max_graph_nodes=args.max_graph_nodes,
        )
        html = render_payload(payload, title=args.title)
    except (InvalidSnapshotError, UnknownPlatformError) as exc:
        print(f"sdr-visualizer: {exc}", file=sys.stderr)
        return INPUT_VALIDATION_ERROR
    except Exception as exc:  # pragma: no cover — unexpected runtime failure
        print(f"sdr-visualizer: unexpected error: {exc}", file=sys.stderr)
        return RUNTIME_ERROR

    output_path = _resolve_output_path(args.output, impl.instance_id)
    try:
        output_path.write_text(html, encoding="utf-8")
    except OSError as exc:
        print(f"sdr-visualizer: could not write {output_path}: {exc}", file=sys.stderr)
        return RUNTIME_ERROR
    if not args.quiet:
        print(f"sdr-visualizer: wrote {output_path}", file=sys.stderr)

    if args.json:
        try:
            json_text = json.dumps(payload, indent=2, allow_nan=False)
        except ValueError:
            print(
                "sdr-visualizer: payload contains NaN or Infinity; cannot write --json",
                file=sys.stderr,
            )
            return INPUT_VALIDATION_ERROR
        try:
            Path(args.json).write_text(json_text, encoding="utf-8")
        except OSError as exc:
            print(f"sdr-visualizer: could not write {args.json}: {exc}", file=sys.stderr)
            return RUNTIME_ERROR
        if not args.quiet:
            print(f"sdr-visualizer: wrote {args.json}", file=sys.stderr)

    return SUCCESS


def _exactly_one_input_source(args: argparse.Namespace) -> bool:
    sources = [bool(args.path), bool(args.dataview), bool(args.rsid)]
    return sum(sources) == 1


def _load(args: argparse.Namespace) -> tuple[dict, str]:
    if args.dataview or args.rsid:
        if args.at:
            print(
                "sdr-visualizer: --at applies only to snapshot directories; ignoring",
                file=sys.stderr,
            )
        return shell_cja(args.dataview) if args.dataview else shell_aa(args.rsid)
    return load_snapshot(args.path, at=args.at)


def _build_parser() -> argparse.ArgumentParser:
    p = _ArgumentParser(
        prog="sdr-visualizer",
        description="Generate a visual catalog of an Adobe CJA / AA implementation.",
    )
    p.add_argument(
        "path",
        nargs="?",
        help=(
            "Snapshot file path, snapshot directory, or '-' for stdin. "
            "Mutually exclusive with --dataview / --rsid."
        ),
    )
    p.add_argument(
        "--dataview",
        help="Mode 3 (CJA): shell out to cja_auto_sdr against this Data View ID.",
    )
    p.add_argument(
        "--rsid",
        help="Mode 3 (AA): shell out to aa_auto_sdr against this Report Suite ID.",
    )
    p.add_argument(
        "--platform",
        choices=["cja", "aa"],
        help="Override platform auto-detection.",
    )
    p.add_argument(
        "--at",
        help=(
            "When path is a directory, pick the snapshot closest to (and not after) this timestamp."
        ),
    )
    p.add_argument(
        "--output",
        help="HTML output path. Default: ./visualize-{instance_id}-{timestamp}.html",
    )
    p.add_argument("--title", help="Override the document title.")
    p.add_argument(
        "--exclude-orphans",
        action="store_true",
        help="Default the catalog's references filter to 'Referenced' so orphans are hidden.",
    )
    p.add_argument(
        "--max-graph-nodes",
        type=int,
        help="Override the graph-rendering threshold (default 1000).",
    )
    p.add_argument(
        "--json",
        help="Also emit the embedded data payload as a separate JSON file at this path.",
    )
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
