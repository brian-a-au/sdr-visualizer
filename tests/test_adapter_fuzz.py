"""Property-based fuzz tests for the AA + CJA adapters and the render path.

Ported from sdr-grader's tests/test_adapter_fuzz.py (vendoring rule:
sdr_grader -> sdr_visualizer; keep the adapter sections semantically
identical so the sibling suites stay comparable). Extended here with a
render-path property the grader has no equivalent of: any snapshot the
adapter accepts must either render to parseable HTML or raise
InvalidSnapshotError — never a bare TypeError/KeyError/AttributeError, and
never emit an embedded payload the browser cannot parse (the NaN/Infinity
class the 2026-07 audit caught as H2).

The contract: any input that isn't a valid snapshot must raise
InvalidSnapshotError. Nothing in the pipeline is allowed to crash with an
unexpected exception type — that would be a missing guard the user can't
usefully recover from.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from conftest import extract_payload_text
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from sdr_visualizer.adapters import aa as aa_adapter
from sdr_visualizer.adapters import cja as cja_adapter
from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.models import Implementation
from sdr_visualizer.render.renderer import render

FIXTURES = Path(__file__).parent / "fixtures"

ALLOWED_EXCEPTIONS = (InvalidSnapshotError,)

_SCHEMA_VALIDATOR = Draft202012Validator(
    json.loads(
        (Path(__file__).parent.parent / "docs" / "payload-schema.json").read_text(encoding="utf-8")
    )
)


def _scalars() -> st.SearchStrategy[Any]:
    return st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-(2**31), max_value=2**31),
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        st.text(max_size=40),
    )


def _json_values() -> st.SearchStrategy[Any]:
    return st.recursive(
        _scalars(),
        lambda children: st.one_of(
            st.lists(children, max_size=4),
            st.dictionaries(st.text(max_size=10), children, max_size=4),
        ),
        max_leaves=8,
    )


@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=200, deadline=None)
@given(payload=_json_values())
@pytest.mark.parametrize("adapter", [aa_adapter, cja_adapter])
def test_adapter_never_crashes_on_random_input(adapter, payload):
    """No matter what JSON we feed in, the adapter raises InvalidSnapshotError
    or returns an Implementation — nothing else."""
    try:
        result = adapter.adapt(payload, source="<fuzz>")
    except ALLOWED_EXCEPTIONS:
        return  # expected path
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"{adapter.__name__} raised {type(exc).__name__} on random input — "
            "should be InvalidSnapshotError or success"
        ) from exc
    assert isinstance(result, Implementation)


# ---------------------------------------------------------------------------
# Mutation fuzz: start from a good fixture, perturb, ensure we still fail
# gracefully or succeed.
# ---------------------------------------------------------------------------


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _all_paths(node: Any, prefix: tuple = ()) -> list[tuple]:
    out: list[tuple] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out.append(prefix + (k,))
            out.extend(_all_paths(v, prefix + (k,)))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.append(prefix + (i,))
            out.extend(_all_paths(v, prefix + (i,)))
    return out


def _set_at(root: Any, path: tuple, value: Any) -> None:
    cur = root
    for step in path[:-1]:
        cur = cur[step]
    cur[path[-1]] = value


def _delete_at(root: Any, path: tuple) -> None:
    cur = root
    for step in path[:-1]:
        cur = cur[step]
    if isinstance(cur, dict):
        cur.pop(path[-1], None)
    elif isinstance(cur, list):
        import contextlib

        with contextlib.suppress(IndexError):
            cur.pop(path[-1])


_MUTATIONS = [
    "delete",
    "replace_none",
    "replace_int",
    "replace_str",
    "replace_truthy_int",
    "replace_json_list_string",
]

# The render path additionally faces NaN injection: Python's json.loads
# happily parses bare NaN literals, so real snapshots can carry them
# (audit H2). The adapters coerce most numerics, so this mutation mostly
# exercises the renderer's allow_nan=False guard.
_RENDER_MUTATIONS = [*_MUTATIONS, "replace_nan"]

_FIXTURE_ADAPTERS = [
    ("aa_snapshot_clean.json", aa_adapter),
    ("aa_snapshot_messy.json", aa_adapter),
    ("cja_snapshot_clean.json", cja_adapter),
    ("cja_snapshot_messy.json", cja_adapter),
]


def _apply_mutation(doc: Any, target: tuple, mutation: str) -> None:
    if mutation == "delete":
        _delete_at(doc, target)
    elif mutation == "replace_none":
        _set_at(doc, target, None)
    elif mutation == "replace_int":
        _set_at(doc, target, 0)
    elif mutation == "replace_str":
        _set_at(doc, target, "")
    elif mutation == "replace_truthy_int":
        _set_at(doc, target, 7)
    elif mutation == "replace_json_list_string":
        _set_at(doc, target, '["fuzzed"]')
    elif mutation == "replace_nan":
        _set_at(doc, target, float("nan"))


@pytest.mark.parametrize(("fixture_name", "adapter"), _FIXTURE_ADAPTERS)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    mutation=st.sampled_from(_MUTATIONS),
)
def test_adapter_survives_mutated_fixture(fixture_name, adapter, seed, mutation):
    """Take a valid fixture, mutate one path, confirm graceful handling."""
    import random

    rng = random.Random(seed)
    doc = copy.deepcopy(_load(fixture_name))
    paths = _all_paths(doc)
    if not paths:
        return
    target = rng.choice(paths)
    _apply_mutation(doc, target, mutation)

    try:
        result = adapter.adapt(doc, source=f"<mutation:{mutation}:{target}>")
    except ALLOWED_EXCEPTIONS:
        return
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"{adapter.__name__} crashed with {type(exc).__name__} after mutating "
            f"path={target} via {mutation}: {exc}"
        ) from exc
    assert isinstance(result, Implementation)


# ---------------------------------------------------------------------------
# Render-path fuzz (visualizer-only extension): whatever the adapter
# accepts must either render to HTML whose embedded payload parses, or
# raise InvalidSnapshotError. Never anything else.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("fixture_name", "adapter"), _FIXTURE_ADAPTERS)
@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    mutation=st.sampled_from(_RENDER_MUTATIONS),
)
def test_render_path_survives_mutated_fixture(fixture_name, adapter, seed, mutation):
    import random

    rng = random.Random(seed)
    doc = copy.deepcopy(_load(fixture_name))
    paths = _all_paths(doc)
    if not paths:
        return
    target = rng.choice(paths)
    _apply_mutation(doc, target, mutation)

    try:
        impl = adapter.adapt(doc, source=f"<mutation:{mutation}:{target}>")
    except ALLOWED_EXCEPTIONS:
        return

    try:
        html = render(impl)
    except ALLOWED_EXCEPTIONS:
        return  # e.g. NaN reaching the payload raises InvalidSnapshotError
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"render crashed with {type(exc).__name__} after mutating "
            f"path={target} via {mutation}: {exc}"
        ) from exc

    # The embedded payload must be parseable — a report that renders but
    # cannot boot in the browser is the audit-H2 failure class.
    payload = json.loads(extract_payload_text(html))
    # ...and must satisfy the published contract schema: a report whose
    # payload violates docs/payload-schema.json is a contract bug even
    # when it renders (the class behind the 1.0.0 polarity/option-field/
    # trend-taken_at findings).
    error = next(iter(_SCHEMA_VALIDATOR.iter_errors(payload)), None)
    assert error is None, f"payload violates schema at {error.json_path}: {error.message}"
