"""Mutation script tests (loaded via importlib; scripts/ is not a package)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"

spec = importlib.util.spec_from_file_location(
    "mutate_fixture", REPO / "scripts" / "mutate_fixture.py"
)
mutate_fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mutate_fixture)
mutate = mutate_fixture.mutate


def _clean_snapshot():
    return json.loads((FIXTURES / "cja_snapshot_clean.json").read_text(encoding="utf-8"))


def test_mutate_is_deterministic():
    a = mutate(_clean_snapshot())
    b = mutate(_clean_snapshot())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_iterative_mutation_keeps_component_ids_unique():
    snap = _clean_snapshot()
    for _ in range(5):
        snap = mutate(snap)
        ids = [r["id"] for r in snap["metrics"] if isinstance(r, dict)]
        assert len(ids) == len(set(ids)), "duplicate metric ids after iterative mutation"


def test_mutate_does_not_modify_its_input():
    snap = _clean_snapshot()
    before = json.dumps(snap, sort_keys=True)
    mutate(snap)
    assert json.dumps(snap, sort_keys=True) == before
