"""Shared, side-effect-free output destination identity checks."""

from __future__ import annotations

from pathlib import Path


def paths_alias(left: Path, right: Path) -> bool | None:
    """Return whether paths share identity, or ``None`` when identity is unknowable."""
    try:
        if left.resolve(strict=False) == right.resolve(strict=False):
            return True
        left_exists = _path_exists(left)
        right_exists = _path_exists(right)
        return left_exists and right_exists and left.samefile(right)
    except (OSError, RuntimeError):
        return None


def _path_exists(path: Path) -> bool:
    try:
        path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    return True


__all__ = ["paths_alias"]
