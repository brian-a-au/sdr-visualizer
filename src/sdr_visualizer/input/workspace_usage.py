"""Bounded regular-file loader for supplementary Workspace evidence."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.workspace_usage import MAX_INPUT_BYTES, validate_json_value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidSnapshotError("Workspace usage contains duplicate JSON keys")
        result[key] = value
    return result


def _constant(value):
    raise InvalidSnapshotError("Workspace usage contains a non-finite number")


def load_workspace_usage(path: str | Path) -> dict:
    """Read at most the cap plus one byte, rejecting special files and JSON ambiguity."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise InvalidSnapshotError("Workspace usage must be a regular JSON file")
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise InvalidSnapshotError("Workspace usage exceeds input byte limit")
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
        validate_json_value(value)
        if type(value) is not dict:
            raise InvalidSnapshotError("Workspace usage must be a JSON object")
        return value
    except (OSError, ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise InvalidSnapshotError(
            "Workspace usage could not be read as bounded UTF-8 JSON"
        ) from exc
