"""Private, content-free output boundary for the CJA lineage POC."""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sdr_visualizer.cli.output_safety import paths_alias


class LineageOutputFailureCode(StrEnum):
    """Stable output failures that retain no external filesystem content."""

    UNSAFE_DESTINATION = "unsafe-destination"
    WRITE_FAILED = "write-failed"


@dataclass(frozen=True, slots=True)
class LineageOutputFailure:
    """A deliberately path-free output result."""

    code: LineageOutputFailureCode

    def __str__(self) -> str:
        return self.code.value

    def __repr__(self) -> str:
        return f"LineageOutputFailure(code={self.code.value!r})"


def validate_lineage_destination(
    destination: Path,
    protected_paths: Iterable[Path] = (),
) -> LineageOutputFailure | None:
    """Reject unsafe destination objects and protected identity aliases."""
    try:
        metadata = destination.lstat()
    except (FileNotFoundError, NotADirectoryError):
        metadata = None
    except (OSError, RuntimeError):
        return LineageOutputFailure(LineageOutputFailureCode.UNSAFE_DESTINATION)

    if metadata is not None and (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1):
        return LineageOutputFailure(LineageOutputFailureCode.UNSAFE_DESTINATION)

    for protected in protected_paths:
        alias = paths_alias(destination, protected)
        if alias is None or alias:
            return LineageOutputFailure(LineageOutputFailureCode.UNSAFE_DESTINATION)
    return None


def write_lineage_output(
    destination: Path,
    html: str,
    *,
    protected_paths: Iterable[Path] = (),
) -> LineageOutputFailure | None:
    """Atomically replace ``destination`` with complete owner-only UTF-8 data.

    All fallible durability and permission work happens before replacement so
    an observed failure can truthfully promise preservation of a prior artifact.
    No post-replacement directory fsync is attempted because its failure could
    not be rolled back without weakening that contract.
    """
    protected = tuple(protected_paths)
    preflight = validate_lineage_destination(destination, protected)
    if preflight is not None:
        return preflight
    try:
        payload = html.encode("utf-8", errors="strict")
    except (AttributeError, UnicodeError):
        return LineageOutputFailure(LineageOutputFailureCode.WRITE_FAILED)

    descriptor: int | None = None
    temporary: Path | None = None
    replaced = False
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None

        # Flush pre-existing directory state while rollback is still possible.
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_descriptor = os.open(destination.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)

        revalidation = validate_lineage_destination(destination, protected)
        if revalidation is not None:
            return revalidation
        os.replace(temporary, destination)
        replaced = True
        return None
    except Exception:
        return LineageOutputFailure(LineageOutputFailureCode.WRITE_FAILED)
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        if temporary is not None and not replaced:
            with suppress(OSError):
                temporary.unlink()


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError
        view = view[written:]


__all__ = [
    "LineageOutputFailure",
    "LineageOutputFailureCode",
    "validate_lineage_destination",
    "write_lineage_output",
]
