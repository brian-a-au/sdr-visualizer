"""Compare color-pack contracts from explicit, immutable sibling commits.

The comparator reads only ``git show <sha>:<path>`` blobs. It never imports a
registry or reads either checkout's working tree, so local edits cannot make a
release parity check pass accidentally.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_FIELDS = ("catalog", "source_swatches", "required_roles")
LITERAL_DECLARATIONS = {
    "COLOR_PACK_CODES": "catalog",
    "_SOURCE_SWATCHES": "source_swatches",
    "REQUIRED_COLOR_ROLES": "required_roles",
}
MODULE_PATHS = {
    "visualizer": Path("src/sdr_visualizer/render/color_packs.py"),
    "grader": Path("src/sdr_grader/render/color_packs.py"),
}
_FULL_COMMIT_SHA = re.compile(r"[0-9a-f]{40}\Z")


class ContractCheckError(RuntimeError):
    """The sibling checkout or its exported contract cannot be inspected."""


def _literal_contract(source: str, label: str, *, source_name: str) -> dict[str, object]:
    """Read only the contract's literal assignments from one source blob."""
    try:
        tree = ast.parse(source, filename=source_name)
    except SyntaxError as exc:
        raise ContractCheckError(
            f"could not parse {label} color-pack module {source_name}: {type(exc).__name__}: {exc}"
        ) from exc

    declarations: dict[str, ast.expr] = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if isinstance(target, ast.Name) and target.id in LITERAL_DECLARATIONS:
            if target.id in declarations:
                raise ContractCheckError(
                    f"malformed {label} color-pack contract: duplicate literal "
                    f"declaration {target.id}"
                )
            declarations[target.id] = statement.value

    missing = [name for name in LITERAL_DECLARATIONS if name not in declarations]
    if missing:
        raise ContractCheckError(
            f"malformed {label} color-pack contract: missing literal declarations {missing!r}"
        )

    raw: dict[str, object] = {}
    for declaration, field in LITERAL_DECLARATIONS.items():
        try:
            raw[field] = ast.literal_eval(declarations[declaration])
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as exc:
            raise ContractCheckError(
                f"malformed {label} color-pack contract: {declaration} must be a literal"
            ) from exc
    return raw


def _as_string_sequence(value: object, *, field: str, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not all(isinstance(item, str) for item in value)
    ):
        raise ContractCheckError(
            f"malformed {label} color-pack contract: {field} must be a string list"
        )
    return tuple(value)


def _validate_contract(raw: object, *, label: str) -> dict[str, object]:
    if not isinstance(raw, dict) or tuple(raw) != CONTRACT_FIELDS:
        keys = tuple(raw) if isinstance(raw, dict) else type(raw).__name__
        raise ContractCheckError(
            f"malformed {label} color-pack contract: expected fields in order "
            f"{CONTRACT_FIELDS!r}, got {keys!r}"
        )

    catalog = _as_string_sequence(raw["catalog"], field="catalog", label=label)
    if not catalog or len(set(catalog)) != len(catalog):
        raise ContractCheckError(
            f"malformed {label} color-pack contract: catalog must be non-empty and unique"
        )

    source_swatches = raw["source_swatches"]
    if not isinstance(source_swatches, dict) or tuple(source_swatches) != catalog:
        keys = tuple(source_swatches) if isinstance(source_swatches, dict) else None
        raise ContractCheckError(
            f"malformed {label} color-pack contract: source_swatches keys must match "
            f"catalog order; got {keys!r}"
        )
    normalized_swatches = {
        code: _as_string_sequence(
            source_swatches[code],
            field=f"source_swatches[{code!r}]",
            label=label,
        )
        for code in catalog
    }
    if any(not swatches for swatches in normalized_swatches.values()):
        raise ContractCheckError(
            f"malformed {label} color-pack contract: every pack needs source swatches"
        )

    required_roles = _as_string_sequence(raw["required_roles"], field="required_roles", label=label)
    if not required_roles or len(set(required_roles)) != len(required_roles):
        raise ContractCheckError(
            f"malformed {label} color-pack contract: required_roles must be non-empty and unique"
        )

    return {
        "catalog": catalog,
        "source_swatches": normalized_swatches,
        "required_roles": required_roles,
    }


def _run_git(root: Path, label: str, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            encoding="utf-8",
        )
    except OSError as exc:
        raise ContractCheckError(f"could not run git for {label} checkout: {exc}") from exc
    if completed.returncode:
        detail = (
            completed.stderr.strip().splitlines()[0] if completed.stderr.strip() else "git failed"
        )
        raise ContractCheckError(f"git failed for {label} checkout: {detail}")
    return completed.stdout


def _validate_checkout_and_sha(root: Path, revision: str, label: str) -> None:
    if not root.is_dir():
        raise ContractCheckError(f"{label} checkout not found: {root}")
    try:
        is_worktree = _run_git(root, label, "rev-parse", "--is-inside-work-tree").strip()
    except ContractCheckError as exc:
        raise ContractCheckError(f"{label} checkout is not a Git repository: {root}") from exc
    if is_worktree != "true":
        raise ContractCheckError(f"{label} checkout is not a Git repository: {root}")
    if _FULL_COMMIT_SHA.fullmatch(revision) is None:
        raise ContractCheckError(
            f"{label} commit SHA must be a full 40-character lowercase hex SHA"
        )
    try:
        _run_git(root, label, "cat-file", "-e", f"{revision}^{{commit}}")
    except ContractCheckError as exc:
        raise ContractCheckError(f"{label} commit SHA not found: {revision}") from exc


def _read_contract(root: Path, revision: str, label: str) -> dict[str, object]:
    _validate_checkout_and_sha(root, revision, label)
    module_path = MODULE_PATHS[label].as_posix()
    try:
        source = _run_git(root, label, "show", f"{revision}:{module_path}")
    except ContractCheckError as exc:
        raise ContractCheckError(
            f"{label} color-pack module not found in commit {revision}: {module_path}"
        ) from exc
    raw = _literal_contract(source, label, source_name=f"{label}@{revision}:{module_path}")
    return _validate_contract(raw, label=label)


def check_color_pack_parity(
    visualizer_root: Path,
    visualizer_sha: str,
    grader_root: Path,
    grader_sha: str,
) -> list[str]:
    """Return the names of well-formed commit-pinned contract fields that differ."""
    visualizer = _read_contract(visualizer_root, visualizer_sha, "visualizer")
    grader = _read_contract(grader_root, grader_sha, "grader")
    return [field for field in CONTRACT_FIELDS if visualizer[field] != grader[field]]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare color-pack contracts from explicit sibling Git commits."
    )
    parser.add_argument(
        "--visualizer-root",
        default=REPO_ROOT,
        type=Path,
        help="Path to the visualizer checkout (defaults to this checkout).",
    )
    parser.add_argument(
        "--visualizer-sha",
        required=True,
        help="Full visualizer commit SHA to inspect.",
    )
    parser.add_argument(
        "--grader-root",
        required=True,
        type=Path,
        help="Path to the sibling sdr-grader checkout.",
    )
    parser.add_argument(
        "--grader-sha",
        required=True,
        help="Full sdr-grader commit SHA to inspect.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    visualizer_root = args.visualizer_root.resolve()
    grader_root = args.grader_root.resolve()

    try:
        visualizer = _read_contract(visualizer_root, args.visualizer_sha, "visualizer")
        grader = _read_contract(grader_root, args.grader_sha, "grader")
    except ContractCheckError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    mismatches = [field for field in CONTRACT_FIELDS if visualizer[field] != grader[field]]
    if mismatches:
        for field in mismatches:
            print(f"color-pack parity mismatch: {field}", file=sys.stderr)
            print(
                f"  visualizer: {json.dumps(visualizer[field], sort_keys=False)}",
                file=sys.stderr,
            )
            print(
                f"  grader:     {json.dumps(grader[field], sort_keys=False)}",
                file=sys.stderr,
            )
        return 1

    print("color-pack contracts match for catalog, source_swatches, and required_roles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
