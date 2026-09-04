#!/usr/bin/env python3
"""Generate the private, fixed-name CJA lineage POC artifact."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sdr_visualizer.adapters.cja_lineage import MAX_SCOPE_LABEL_LENGTH
from sdr_visualizer.cli.lineage_output import (
    LineageOutputFailureCode,
    validate_lineage_destination,
    write_lineage_output,
)
from sdr_visualizer.input.lineage_discovery import (
    LineageDiscoveryFailure,
    acquire_live,
    acquire_saved,
)
from sdr_visualizer.render.color_packs import COLOR_PACK_CODES
from sdr_visualizer.render.lineage_renderer import render

OUTPUT_FILENAME = "visualize-cja-lineage-poc.html"
_PROFILE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_MAX_PATH_LENGTH = 4_096


class _PrivateParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:  # type: ignore[override]
        print("generate-cja-lineage-poc: invalid arguments", file=sys.stderr)
        raise SystemExit(3) from None


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _validate_arguments(parser, args)

    destination = Path.cwd() / OUTPUT_FILENAME
    protected = _protected_paths(args)
    preflight = validate_lineage_destination(destination, protected)
    if preflight is not None:
        print("generate-cja-lineage-poc: output rejected", file=sys.stderr)
        return 3

    try:
        if args.saved is not None:
            acquired = acquire_saved(Path(args.saved), scope_label=args.scope_label)
        else:
            acquired = acquire_live(
                Path(args.binary),
                scope_label=args.scope_label,
                profile=args.profile,
                config_file=Path(args.config_file) if args.config_file is not None else None,
            )
    except Exception:
        print("generate-cja-lineage-poc: acquisition failed", file=sys.stderr)
        return 1
    if isinstance(acquired, LineageDiscoveryFailure):
        print("generate-cja-lineage-poc: input rejected", file=sys.stderr)
        return 3

    try:
        html = render(acquired, title=args.scope_label, color_pack=args.color_pack)
    except Exception:
        print("generate-cja-lineage-poc: rendering failed", file=sys.stderr)
        return 1

    result = write_lineage_output(destination, html, protected_paths=protected)
    if result is not None:
        category = (
            "output rejected"
            if result.code is LineageOutputFailureCode.UNSAFE_DESTINATION
            else "output failed"
        )
        print(f"generate-cja-lineage-poc: {category}", file=sys.stderr)
        return 3 if result.code is LineageOutputFailureCode.UNSAFE_DESTINATION else 1

    print("generate-cja-lineage-poc: generated private lineage artifact", file=sys.stderr)
    return 0


def _build_parser() -> _PrivateParser:
    parser = _PrivateParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--saved")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--scope-label")
    parser.add_argument("--binary")
    parser.add_argument("--profile")
    parser.add_argument("--config-file")
    parser.add_argument("--color-pack", default="default")
    return parser


def _validate_arguments(parser: _PrivateParser, args: argparse.Namespace) -> None:
    if (args.saved is None) == (not args.live):
        parser.error("source")
    if args.color_pack not in COLOR_PACK_CODES:
        parser.error("color pack")
    if not _valid_scope_label(args.scope_label):
        parser.error("scope")
    if args.live:
        if (
            not _valid_absolute_path(args.binary)
            or (args.profile is not None and _PROFILE.fullmatch(args.profile) is None)
            or (args.config_file is not None and not _valid_absolute_path(args.config_file))
            or (args.profile is not None and args.config_file is not None)
        ):
            parser.error("live selectors")
    elif any(value is not None for value in (args.binary, args.profile, args.config_file)):
        parser.error("saved selectors")


def _valid_scope_label(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= MAX_SCOPE_LABEL_LENGTH
        and all(not (ord(character) < 32 or 127 <= ord(character) <= 159) for character in value)
        and all(not 0xD800 <= ord(character) <= 0xDFFF for character in value)
    )


def _valid_absolute_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= _MAX_PATH_LENGTH
        and "\x00" not in value
        and all(not (ord(character) < 32 or 127 <= ord(character) <= 159) for character in value)
        and Path(value).is_absolute()
    )


def _protected_paths(args: argparse.Namespace) -> tuple[Path, ...]:
    if args.saved is not None:
        return (Path(args.saved),)
    protected = [Path(args.binary)]
    if args.config_file is not None:
        protected.append(Path(args.config_file))
    return tuple(protected)


if __name__ == "__main__":
    raise SystemExit(main())
