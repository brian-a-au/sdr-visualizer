"""Determinism tests for tracked example generation."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "generate_examples.py"

spec = importlib.util.spec_from_file_location("generate_examples", SCRIPT)
generate_examples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate_examples)


def _payload(html: str) -> dict:
    match = re.search(
        r'<script id="sdr-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def test_generate_example_is_byte_deterministic_and_path_independent(tmp_path):
    first = generate_examples._generate(
        "cja_snapshot_messy.json",
        "first.html",
        output_dir=tmp_path,
    )
    second = generate_examples._generate(
        "cja_snapshot_messy.json",
        "second.html",
        output_dir=tmp_path,
    )

    assert first.read_bytes() == second.read_bytes()
    meta = _payload(first.read_text(encoding="utf-8"))["meta"]
    assert meta["snapshot_source"] == "tests/fixtures/cja_snapshot_messy.json"
    assert meta["generated_at"] == generate_examples.EXAMPLE_GENERATED_AT
    assert str(REPO) not in first.read_text(encoding="utf-8")
