"""Shared pytest fixtures for sdr-visualizer tests."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

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


CREDENTIAL_VARIABLES = (
    "ORG_ID",
    "CLIENT_ID",
    "SECRET",
    "SCOPES",
    "SANDBOX",
    "AA_PROFILE",
    "CJA_PROFILE",
)


@pytest.fixture(autouse=True)
def _no_developer_credentials(monkeypatch):
    """Keep the developer's own credential variables out of every test."""
    for name in CREDENTIAL_VARIABLES:
        monkeypatch.delenv(name, raising=False)


SDR_DATA_RE = re.compile(
    r'<script id="sdr-data" type="application/json">(?P<json>.*?)</script>',
    re.DOTALL,
)


def extract_payload_text(html: str) -> str:
    """Return the raw text of the embedded sdr-data block."""
    match = SDR_DATA_RE.search(html)
    assert match is not None, "sdr-data block not found in rendered HTML"
    return match.group("json")


def extract_payload(html: str) -> dict:
    """Parse the embedded sdr-data payload out of rendered HTML."""
    return json.loads(extract_payload_text(html))
