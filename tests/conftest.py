"""Shared pytest fixtures for sdr-visualizer tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GENERATED_FIXTURES = [
    (
        REPO / "tests" / "fixtures" / "cja_snapshot_large.json",
        REPO / "scripts" / "generate_large_fixture.py",
    ),
    (
        REPO / "tests" / "fixtures" / "aa_snapshot_large.json",
        REPO / "scripts" / "generate_aa_large_fixture.py",
    ),
]


def pytest_configure(config):  # noqa: ARG001
    """Materialize generated fixtures on demand.

    The large CJA + AA fixtures are generated content — we keep them out
    of git and create them on first test run. Keeps `uv run pytest`
    working in a clean checkout without manual setup.
    """
    for fixture, generator in GENERATED_FIXTURES:
        if fixture.exists():
            continue
        subprocess.check_call([sys.executable, str(generator)])
