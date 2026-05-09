"""Shared pytest fixtures for sdr-visualizer tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LARGE_FIXTURE = REPO / "tests" / "fixtures" / "cja_snapshot_large.json"
GENERATOR = REPO / "scripts" / "generate_large_fixture.py"


def pytest_configure(config):  # noqa: ARG001
    """Make sure the large fixture exists before perf tests run.

    The fixture is generated content (~340KB) — we keep it out of git and
    materialize it on demand. CI also generates it explicitly via the
    workflow, but this hook keeps `uv run pytest` working in a clean
    checkout without manual setup.
    """
    if LARGE_FIXTURE.exists():
        return
    subprocess.check_call([sys.executable, str(GENERATOR)])
