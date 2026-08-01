"""Live mode: shell out to cja_auto_sdr / aa_auto_sdr.

The visualizer does not call Adobe APIs directly. To run against a live
data view or report suite, it asks the upstream snapshot tool for JSON
and parses the emitted snapshot as if it were a Mode 1 file.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from sdr_visualizer.core.exceptions import InvalidSnapshotError

SHELL_OUT_TIMEOUT_SECONDS = 600


def shell_cja(
    dataview_id: str, *, extra_args: list[str] | None = None
) -> tuple[dict[str, Any], str]:
    """Shell out to cja_auto_sdr against a CJA data view ID."""
    try:
        with tempfile.TemporaryDirectory(prefix="sdr-visualizer-cja-") as output_dir:
            return _shell_out(
                "cja_auto_sdr",
                [
                    dataview_id,
                    "--format",
                    "json",
                    "--output-dir",
                    output_dir,
                    "--include-all-inventory",
                    "--quiet",
                    *(extra_args or []),
                ],
                flag="--dataview",
                json_output_dir=Path(output_dir),
            )
    except OSError as exc:
        raise InvalidSnapshotError(f"cja_auto_sdr temporary output handling failed: {exc}") from exc


def shell_aa(rsid: str, *, extra_args: list[str] | None = None) -> tuple[dict[str, Any], str]:
    """Shell out to aa_auto_sdr against an AA report suite ID."""
    return _shell_out(
        "aa_auto_sdr",
        [rsid, "--format", "json", "--output", "-", *(extra_args or [])],
        flag="--rsid",
    )


def _shell_out(
    tool: str,
    argv: list[str],
    *,
    flag: str,
    json_output_dir: Path | None = None,
) -> tuple[dict[str, Any], str]:
    binary = shutil.which(tool)
    if not binary:
        raise InvalidSnapshotError(
            f"{tool} not found on PATH; install it before using {flag}, or "
            "pass a snapshot file path / stdin instead."
        )
    cmd = [binary, *argv]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=SHELL_OUT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise InvalidSnapshotError(
            f"{tool} exceeded {SHELL_OUT_TIMEOUT_SECONDS}-second timeout"
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        raise InvalidSnapshotError(
            f"{tool} exited {exc.returncode}: {stderr.strip() or '(no stderr)'}"
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise InvalidSnapshotError(f"{tool} could not be invoked: {exc}") from exc

    if json_output_dir is None:
        snapshot_text = result.stdout
    else:
        try:
            json_outputs = [path for path in json_output_dir.glob("*.json") if path.is_file()]
        except OSError as exc:
            raise InvalidSnapshotError(
                f"{tool} JSON outputs could not be inspected: {exc}"
            ) from exc
        if len(json_outputs) != 1:
            raise InvalidSnapshotError(
                f"{tool} produced {len(json_outputs)} JSON outputs; expected exactly one"
            )
        try:
            snapshot_text = json_outputs[0].read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise InvalidSnapshotError(f"{tool} JSON output could not be read: {exc}") from exc

    try:
        snapshot = json.loads(snapshot_text)
    except json.JSONDecodeError as exc:
        raise InvalidSnapshotError(f"{tool} produced output that is not valid JSON: {exc}") from exc
    except ValueError as exc:
        raise InvalidSnapshotError(f"{tool} produced output that is not valid JSON: {exc}") from exc
    except RecursionError as exc:
        raise InvalidSnapshotError(f"{tool} output JSON exceeds nesting limits") from exc
    return snapshot, f"shell-out:{tool} {argv[0]}"
