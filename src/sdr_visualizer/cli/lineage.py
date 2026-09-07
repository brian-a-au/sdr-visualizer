"""Generate offline CJA-only lineage from dataset discovery JSON (not AA or component snapshots)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sdr_visualizer import __version__
from sdr_visualizer.adapters.cja_lineage import MAX_SCOPE_LABEL_LENGTH
from sdr_visualizer.cli.lineage_output import validate_lineage_destination, write_lineage_output
from sdr_visualizer.input.lineage_discovery import (
    LineageDiscoveryFailure,
    acquire_live,
    acquire_saved,
)
from sdr_visualizer.render.color_packs import COLOR_PACK_CODES
from sdr_visualizer.render.lineage_renderer import render


class _Parser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        # argparse errors may include raw arguments; never echo selectors or credentials.
        self.exit(2, "cja-lineage: invalid arguments; use --help for source and output options.\n")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="cja-lineage", description=__doc__, allow_abbrev=False)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--saved", type=Path, help="Saved --list-datasets JSON discovery file")
    sources.add_argument(
        "--live", action="store_true", help="Acquire accessible lineage using cja_auto_sdr"
    )
    parser.add_argument(
        "--binary", type=Path, help="Absolute path to cja_auto_sdr 3.11.8 or 3.12.0 (live only)"
    )
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument("--profile", help="Named upstream credential profile (live only)")
    auth.add_argument(
        "--config-file", type=Path, help="Absolute upstream credential config path (live only)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("lineage.html"),
        help="Destination HTML file (default: lineage.html)",
    )
    parser.add_argument(
        "--scope-label", default="Accessible CJA scope", help="Human-readable report scope"
    )
    parser.add_argument("--color-pack", choices=COLOR_PACK_CODES, default="default")
    parser.add_argument("--quiet", action="store_true", help="Suppress success output")
    parser.add_argument("--version", action="version", version=f"cja-lineage {__version__}")
    args = parser.parse_args(argv)
    if args.live:
        if args.binary is None or not args.binary.is_absolute():
            parser.error("binary")
        if args.config_file is not None and not args.config_file.is_absolute():
            parser.error("config")
    elif any(value is not None for value in (args.binary, args.profile, args.config_file)):
        parser.error("live selectors")
    label = args.scope_label
    if (
        not label
        or label != label.strip()
        or len(label) > MAX_SCOPE_LABEL_LENGTH
        or any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in label)
    ):
        parser.error("scope")
    protected = tuple(
        path for path in (args.saved, args.binary, args.config_file) if path is not None
    )
    if validate_lineage_destination(args.output, protected) is not None:
        print(
            "cja-lineage: unsafe destination; choose a regular output file distinct from inputs and credentials.",
            file=sys.stderr,
        )
        return 3
    topology = (
        acquire_live(
            args.binary, scope_label=label, profile=args.profile, config_file=args.config_file
        )
        if args.live
        else acquire_saved(args.saved, scope_label=label)
    )
    if isinstance(topology, LineageDiscoveryFailure):
        print(
            f"cja-lineage: {topology.code.value}; use CJA --list-datasets discovery JSON (not AA or component snapshots); see https://github.com/brian-a-au/sdr-visualizer/blob/main/docs/LINEAGE.md for compatibility and recovery.",
            file=sys.stderr,
        )
        return 3
    try:
        html = render(topology, title=label, color_pack=args.color_pack)
    except Exception:
        print(
            "cja-lineage: rendering failed; check discovery structure and report limits.",
            file=sys.stderr,
        )
        return 1
    failure = write_lineage_output(args.output, html, protected_paths=protected)
    if failure is not None:
        print(
            f"cja-lineage: {failure.code.value}; check output directory permissions and destination identity.",
            file=sys.stderr,
        )
        return 1
    if not args.quiet:
        print("cja-lineage: generated offline lineage report", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
