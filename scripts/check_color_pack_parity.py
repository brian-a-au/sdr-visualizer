"""Compare the visualizer and grader color-pack source contracts.

This script loads each repository's source module directly under an isolated
module name. It intentionally does not import either installed package.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_FIELDS = ("catalog", "source_swatches", "required_roles")
MODULE_PATHS = {
    "visualizer": Path("src/sdr_visualizer/render/color_packs.py"),
    "grader": Path("src/sdr_grader/render/color_packs.py"),
}


class ContractCheckError(RuntimeError):
    """The sibling checkout or its exported contract cannot be inspected."""


def _load_source_module(path: Path, label: str) -> ModuleType:
    module_name = f"_sdr_color_pack_contract_{label}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ContractCheckError(f"could not load {label} color-pack module: {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ContractCheckError(
            f"could not load {label} color-pack module {path}: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        sys.modules.pop(module_name, None)
    return module


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

    module = _load_source_module(path, label)
    snapshot = getattr(module, "color_pack_contract_snapshot", None)
    if not callable(snapshot):
        raise ContractCheckError(
            f"{label} color-pack module does not export color_pack_contract_snapshot: {path}"
        )
    try:
        raw = snapshot()
    except Exception as exc:
        raise ContractCheckError(
            f"could not read {label} color-pack contract: {type(exc).__name__}: {exc}"
        ) from exc
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
