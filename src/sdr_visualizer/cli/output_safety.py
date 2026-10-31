"""Shared, side-effect-free output destination identity checks."""

from __future__ import annotations

import unicodedata
from pathlib import Path


def paths_alias(left: Path, right: Path) -> bool | None:
    """Return whether paths share identity, or ``None`` when identity is unknowable."""
    try:
        if left.resolve(strict=False) == right.resolve(strict=False):
            return True
        left_exists = _path_exists(left)
        right_exists = _path_exists(right)
        if left_exists and right_exists:
            return left.samefile(right)
        # A destination that does not exist yet has no identity to compare.
        # Case-insensitive filesystems (the macOS default) still map names that
        # differ only in case or Unicode normalization to one file, so treat
        # them as aliases in the same directory.
        return _folded(left.name) == _folded(right.name) and _same_directory(
            left.parent, right.parent
        )
    except (OSError, RuntimeError):
        return None


def path_within(path: Path, directory: Path) -> bool:
    """Return whether ``path`` lies inside ``directory`` by filesystem identity.

    Comparing existing ancestors by identity also catches spellings that differ
    only in case on case-insensitive filesystems.
    """
    if path.absolute().is_relative_to(directory.absolute()):
        return True
    if path.resolve().is_relative_to(directory.resolve()):
        return True
    return any(
        _path_exists(ancestor) and ancestor.samefile(directory)
        for ancestor in path.absolute().parents
    )


def _folded(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def _same_directory(left: Path, right: Path) -> bool:
    return _path_exists(left) and _path_exists(right) and left.samefile(right)


def _path_exists(path: Path) -> bool:
    try:
        path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    return True


__all__ = ["path_within", "paths_alias"]
