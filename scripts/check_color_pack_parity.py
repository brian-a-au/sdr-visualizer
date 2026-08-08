"""Compare visualizer and grader color-pack contracts without executing code.

Each registry exposes its shared contract as three literal assignments. This
script parses those declarations from source with :func:`ast.literal_eval`; it
does not import either package or execute either repository's Python code.
"""

from __future__ import annotations

import argparse
import ast
import json
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


class ContractCheckError(RuntimeError):
    """The sibling checkout or its exported contract cannot be inspected."""


def _literal_contract(path: Path, label: str) -> dict[str, object]:
    """Read only the contract's literal assignments from one source file."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise ContractCheckError(
            f"could not parse {label} color-pack module {path}: {type(exc).__name__}: {exc}"
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


def _read_contract(root: Path, label: str) -> dict[str, object]:
    path = root / MODULE_PATHS[label]
    if not path.is_file():
        raise ContractCheckError(f"{label} color-pack module not found: {path}")

    raw = _literal_contract(path, label)
    return _validate_contract(raw, label=label)


def check_color_pack_parity(visualizer_root: Path, grader_root: Path) -> list[str]:
    """Return the names of well-formed contract fields that differ."""
    visualizer = _read_contract(visualizer_root, "visualizer")
    grader = _read_contract(grader_root, "grader")
    return [field for field in CONTRACT_FIELDS if visualizer[field] != grader[field]]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare shared color-pack contracts with a sibling sdr-grader checkout."
    )
    parser.add_argument(
        "--grader-root",
        required=True,
        type=Path,
        help="Path to the sibling sdr-grader checkout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    grader_root = args.grader_root.resolve()
    if not grader_root.is_dir():
        print(f"grader checkout not found: {grader_root}", file=sys.stderr)
        return 2

    try:
        visualizer = _read_contract(REPO_ROOT, "visualizer")
        grader = _read_contract(grader_root, "grader")
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
