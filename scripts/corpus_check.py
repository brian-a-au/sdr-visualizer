"""Corpus sweep (0.6.0; the 1.0.0 release gate runs this over the real corpus).

Point it at a directory tree of real cja_auto_sdr / aa_auto_sdr snapshots;
every *.json under it is built through the full production pipeline
in-process. Per snapshot it asserts:

  - the adapter accepts it (platform auto-detected),
  - the payload survives json.dumps(allow_nan=False),
  - the rendered HTML's embedded payload extracts and parses back,
  - the embedded payload validates against docs/payload-schema.json,
  - with --check-budgets: the HTML size fits the SPEC §6 tier for the
    snapshot's component count (no budget above the 2,000 tier — output
    there is valid but degraded by design).

One line per snapshot, failure summary at the end. Local tool by design:
the corpus is private and stays off GitHub; this is NOT a CI job.

Run via:

    uv run python scripts/corpus_check.py ~/corpora/sdr-snapshots --check-budgets
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from sdr_visualizer.core.exceptions import InvalidSnapshotError, UnknownPlatformError  # noqa: E402
from sdr_visualizer.core.visualizer import build_implementation  # noqa: E402
from sdr_visualizer.render.renderer import build_payload_with_options, render_payload  # noqa: E402

try:
    from jsonschema import Draft202012Validator
except ImportError:  # dev-only dependency; the sweep still runs without it
    Draft202012Validator = None

_SCHEMA_PATH = REPO / "docs" / "payload-schema.json"
_VALIDATOR = (
    Draft202012Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))
    if Draft202012Validator is not None
    else None
)

_SDR_DATA_RE = re.compile(
    r'<script id="sdr-data" type="application/json">(?P<json>.*?)</script>',
    re.DOTALL,
)

# SPEC §6 size budgets by component-count tier (MB). Above 2,000 the output
# is valid but degraded by design — no budget is asserted.
_TIERS = ((100, 0.5), (500, 2.0), (1000, 4.0), (2000, 8.0))


def _tier_budget_mb(component_count: int) -> float | None:
    for ceiling, budget in _TIERS:
        if component_count <= ceiling:
            return budget
    return None


def _check_one(path: Path, *, check_budgets: bool) -> tuple[str | None, str]:
    """Return (failure_reason, ok_detail). Exactly one of the two is set."""
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"unreadable or invalid JSON: {exc}", ""
    try:
        impl = build_implementation(snapshot, source=str(path))
        payload = build_payload_with_options(impl)
    except (InvalidSnapshotError, UnknownPlatformError) as exc:
        return f"rejected by pipeline: {exc}", ""
    except Exception as exc:  # noqa: BLE001 — a crash IS the finding
        return f"crashed: {type(exc).__name__}: {exc}", ""
    try:
        json.dumps(payload, allow_nan=False)
    except ValueError as exc:
        # Invalid input, not a tool crash: bare NaN/Infinity in the
        # snapshot (the audit-H2 class).
        return f"payload not JSON-serializable (NaN/Infinity in snapshot): {exc}", ""
    try:
        html = render_payload(payload)
    except (InvalidSnapshotError, UnknownPlatformError) as exc:
        return f"rejected by pipeline: {exc}", ""
    except Exception as exc:  # noqa: BLE001
        return f"crashed: {type(exc).__name__}: {exc}", ""
    match = _SDR_DATA_RE.search(html)
    if match is None:
        return "embedded payload block not found in rendered HTML", ""
    try:
        embedded = json.loads(match.group("json"))
    except json.JSONDecodeError as exc:
        return f"embedded payload does not parse: {exc}", ""
    if _VALIDATOR is not None:
        error = next(iter(_VALIDATOR.iter_errors(embedded)), None)
        if error is not None:
            return (
                f"payload violates docs/payload-schema.json at {error.json_path}: {error.message}",
                "",
            )
    size_mb = len(html.encode("utf-8")) / (1024 * 1024)
    count = payload["meta"]["component_count"]
    if check_budgets:
        budget = _tier_budget_mb(count)
        if budget is not None and size_mb > budget:
            return (
                f"{size_mb:.2f}MB exceeds the {budget}MB budget for {count} components",
                "",
            )
        return None, f"  ({size_mb:.2f}MB, {count} components)"
    return None, ""


def sweep(corpus: Path, *, check_budgets: bool) -> int:
    snapshots = sorted(p for p in corpus.rglob("*.json") if p.is_file())
    if not snapshots:
        print(f"no .json snapshots found under {corpus}", file=sys.stderr)
        return 2
    failed: list[tuple[Path, str]] = []
    for path in snapshots:
        reason, ok_detail = _check_one(path, check_budgets=check_budgets)
        rel = path.relative_to(corpus)
        if reason is None:
            print(f"OK   {rel}{ok_detail}")
        else:
            failed.append((path, reason))
            print(f"FAIL {rel}: {reason}")
    print(f"\n{len(snapshots) - len(failed)} ok, {len(failed)} failed of {len(snapshots)}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sweep a snapshot corpus through the build.")
    parser.add_argument("corpus", help="Directory tree of *.json snapshots")
    parser.add_argument(
        "--check-budgets",
        action="store_true",
        help="Also assert the SPEC §6 size budget for each snapshot's tier",
    )
    args = parser.parse_args(argv)
    corpus = Path(args.corpus)
    if not corpus.is_dir():
        print(f"not a directory: {corpus}", file=sys.stderr)
        return 2
    return sweep(corpus, check_budgets=args.check_budgets)


if __name__ == "__main__":
    raise SystemExit(main())
