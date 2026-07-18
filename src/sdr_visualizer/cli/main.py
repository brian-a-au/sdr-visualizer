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
from sdr_visualizer.adapters import aa as aa_adapter
from sdr_visualizer.adapters import cja as cja_adapter
from sdr_visualizer.analysis.diff import diff_implementations
from sdr_visualizer.analysis.trend import build_trend
from sdr_visualizer.cli.exit_codes import (
    INPUT_VALIDATION_ERROR,
    RUNTIME_ERROR,
    SUCCESS,
)
from sdr_visualizer.core.exceptions import (
    InvalidSnapshotError,
    UnknownPlatformError,
)
from sdr_visualizer.core.models import Implementation
from sdr_visualizer.core.visualizer import build_implementation
from sdr_visualizer.input.loader import STDIN_TOKEN, load_snapshot
from sdr_visualizer.input.series import list_snapshot_series
from sdr_visualizer.input.shell_out import shell_aa, shell_cja
from sdr_visualizer.render.renderer import build_payload_with_options, render_payload

# Q4 (1.0.0): above this the report is still valid but visibly degraded
# (simplified rendering; the graph view already needs --max-graph-nodes
# opt-in past 1,000 nodes). Warn — never refuse — on valid input.
EXTREME_SIZE_WARNING = 5000


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
    if args.trend and args.compare_to:
        parser.error("--trend and --compare-to are mutually exclusive")
    if args.trend and (args.dataview or args.rsid):
        parser.error("--trend applies only to snapshot directories")
    if (args.dataview or args.rsid) and args.platform:
        # Mode 3 already fixes the platform (--dataview -> CJA, --rsid -> AA);
        # honoring --platform here could force a mismatched adapter. Ignore it
        # with a warning, mirroring how --at is handled for these modes.
        print(
            "sdr-visualizer: --platform does not apply to --dataview / --rsid "
            "(the mode selects the platform); ignoring",
            file=sys.stderr,
        )
        args.platform = None

    try:
        trend = None
        if args.trend:
            impl, trend = _load_trend(args)
            baseline = None
        else:
            snapshot, source = _load(args)
            impl = build_implementation(
                snapshot,
                source=source,
                platform=args.platform,
            )
            baseline = _load_baseline(args, impl) if args.compare_to else None
        adapter = cja_adapter if impl.platform == "cja" else aa_adapter
        compat = adapter.generator_version_warning(impl.adapter_version)
        if compat:
            print(f"sdr-visualizer: warning: {compat}", file=sys.stderr)
        payload = build_payload_with_options(
            impl,
            exclude_orphans=args.exclude_orphans,
            max_graph_nodes=args.max_graph_nodes,
        )
        if baseline is not None:
            payload["changes"] = diff_implementations(baseline, impl)
            payload["meta"]["compared_to"] = payload["changes"]["baseline"]
        if trend is not None:
            payload["trend"] = trend
        count = payload["meta"]["component_count"]
        if count >= EXTREME_SIZE_WARNING:
            print(
                f"sdr-visualizer: warning: {count:,} components — the report is "
                "valid but degrades at this size; the graph view stays behind its "
                "opt-in (--max-graph-nodes)",
                file=sys.stderr,
            )
        html = render_payload(payload, title=args.title)
    except (InvalidSnapshotError, UnknownPlatformError) as exc:
        print(f"sdr-visualizer: {exc}", file=sys.stderr)
        return INPUT_VALIDATION_ERROR
    except Exception as exc:
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


def _load_baseline(args: argparse.Namespace, impl: Implementation) -> Implementation:
    """Load and validate the --compare-to baseline.

    Raised InvalidSnapshotError maps to exit 3 in main()'s except clause."""
    if args.compare_to == STDIN_TOKEN:
        raise InvalidSnapshotError(
            "--compare-to does not accept stdin ('-'); pass a file or directory"
        )
    # --at resolves a baseline *directory* the same way it resolves the primary
    # directory (to the snapshot at or before the target); a file baseline
    # ignores it without a spurious "ignoring" warning.
    compare_at = args.at if Path(args.compare_to).is_dir() else None
    snapshot, source = load_snapshot(args.compare_to, at=compare_at)
    baseline = build_implementation(snapshot, source=source, platform=args.platform)
    if baseline.platform != impl.platform:
        raise InvalidSnapshotError(
            f"--compare-to platform mismatch: baseline is {baseline.platform}, "
            f"primary snapshot is {impl.platform}"
        )
    if baseline.instance_id != impl.instance_id:
        if not args.allow_instance_mismatch:
            raise InvalidSnapshotError(
                f"--compare-to instance mismatch: baseline is {baseline.instance_id}, "
                f"primary snapshot is {impl.instance_id}; compare snapshots of the same "
                "data view / report suite (or pass --allow-instance-mismatch)"
            )
        print(
            "sdr-visualizer: warning: comparing different instances "
            f"({baseline.instance_id} vs {impl.instance_id}); --allow-instance-mismatch set",
            file=sys.stderr,
        )
    return baseline


def _load_trend(args: argparse.Namespace) -> tuple[Implementation, dict]:
    """Load, adapt, and validate a single-implementation --trend series.

    Returns (newest usable Implementation, trend payload section). Raised
    InvalidSnapshotError maps to exit 3 in main()'s except clause."""
    entries, capped = list_snapshot_series(args.path, at=args.at)
    impls: list[Implementation] = []
    for snapshot, source in entries:
        try:
            impls.append(build_implementation(snapshot, source=source, platform=args.platform))
        except (InvalidSnapshotError, UnknownPlatformError, ValueError, TypeError) as exc:
            # Broad on purpose: any snapshot the adapter cannot turn into a valid
            # Implementation — a bad platform, or a scalar-coercion failure such
            # as a non-numeric nesting_depth surfacing as ValueError/TypeError —
            # is a skippable unusable snapshot, not a reason to abort the whole
            # trend. The stderr warning keeps a genuine adapter regression visible.
            print(f"sdr-visualizer: warning: skipping {source}: {exc}", file=sys.stderr)
    if impls:
        # A trend must be a single implementation: one platform and one data
        # view / report suite. Both dimensions are refused when mixed, the same
        # way --compare-to refuses a mismatch, rather than diffing unrelated
        # inventories. Platform is declarable, so its message points at
        # --platform; instance has no flag, so the fix is a cleaner directory.
        # (With --platform set, non-matching snapshots fail to adapt above and
        # never reach here.)
        platforms = sorted({i.platform for i in impls})
        if len(platforms) > 1:
            raise InvalidSnapshotError(
                f"--trend directory mixes platforms ({', '.join(platforms)}); "
                "pass --platform cja|aa to select one, or use a single-platform directory"
            )
        instances = sorted({i.instance_id for i in impls})
        if len(instances) > 1:
            if not args.allow_instance_mismatch:
                raise InvalidSnapshotError(
                    "--trend directory mixes data views / report suites "
                    f"({', '.join(instances)}); use snapshots of a single implementation "
                    "(or pass --allow-instance-mismatch)"
                )
            print(
                "sdr-visualizer: warning: --trend directory mixes data views / report "
                f"suites ({', '.join(instances)}); --allow-instance-mismatch set",
                file=sys.stderr,
            )
    if len(impls) < 2:
        raise InvalidSnapshotError(
            "--trend needs at least 2 usable snapshots after skipping unusable ones"
        )
    return impls[-1], build_trend(impls, capped=capped)


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
            "For a directory (the path or a --compare-to baseline), pick the snapshot "
            "closest to (and not after) this timestamp."
        ),
    )
    p.add_argument(
        "--compare-to",
        help=(
            "Baseline snapshot to compare against: a file, or a directory "
            "(resolves to its latest snapshot). Adds a Changes view to the report."
        ),
    )
    p.add_argument(
        "--trend",
        action="store_true",
        help=(
            "When path is a snapshot directory, chart aggregates and per-interval "
            "changes across its snapshots (adds a Trend view)."
        ),
    )
    p.add_argument(
        "--allow-instance-mismatch",
        action="store_true",
        help=(
            "Permit --compare-to / --trend to span different data views or report "
            "suites (an instance mismatch otherwise exits 3). The diff or trend then "
            "spans unrelated inventories; a warning is printed. Platform mismatches "
            "are always rejected."
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
