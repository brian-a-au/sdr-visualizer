"""AA adapter tests (SPEC-VISUALIZER §10 Phase 7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdr_visualizer.adapters.aa import adapt
from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.input.detect import detect_platform
from sdr_visualizer.render.renderer import render

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def messy_aa():
    return json.loads((FIXTURES / "aa_snapshot_messy.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def clean_aa():
    return json.loads((FIXTURES / "aa_snapshot_clean.json").read_text(encoding="utf-8"))


def test_detect_recognizes_aa_snapshot(messy_aa):
    assert detect_platform(messy_aa) == "aa"


def test_detect_recognizes_cja_snapshot():
    cja = json.loads((FIXTURES / "cja_snapshot_messy.json").read_text(encoding="utf-8"))
    assert detect_platform(cja) == "cja"


def test_aa_adapter_basic_shape(messy_aa):
    impl = adapt(messy_aa)
    assert impl.platform == "aa"
    assert impl.instance_id == "messy.prod"
    assert impl.instance_name == "Messy Production"
    assert impl.adapter_version == "1.0.0"
    assert impl.derived_fields == []  # CJA-only concept


def test_aa_adapter_combines_evars_and_props_into_dimensions(messy_aa):
    impl = adapt(messy_aa)
    evars = [d for d in impl.dimensions if d.id.startswith("variables/evar")]
    props = [d for d in impl.dimensions if d.id.startswith("variables/prop")]
    assert len(evars) == 40
    assert len(props) == 20
    # eVars carry their AA-specific allocation in platform_specific.extra.
    sample = next(d for d in evars if d.id == "variables/evar2")
    assert sample.platform_specific.get("extra", {}).get("allocation") == "most-recent"


def test_aa_adapter_lifts_classifications_to_tags(messy_aa):
    impl = adapt(messy_aa)
    evar1 = next(d for d in impl.dimensions if d.id == "variables/evar1")
    assert "Campaign Metadata" in evar1.tags


def test_aa_adapter_calc_metric_references(messy_aa):
    impl = adapt(messy_aa)
    cm = next(c for c in impl.calculated_metrics if c.id == "cm_conversion_rate")
    assert cm.references == ["metrics/orders", "metrics/visits"]
    assert cm.formula_text.startswith("divide(")


def test_aa_adapter_segment_nesting_depth_and_contexts(messy_aa):
    impl = adapt(messy_aa)
    nested = next(s for s in impl.segments if s.id == "s_returning")
    # Definition nests visitors > visits with a sibling hits container —
    # 3 distinct contexts, deepest container chain = 2.
    assert set(nested.container_types) == {"visitors", "visits", "hits"}
    assert nested.nesting_depth == 2


def test_aa_adapter_dash_descriptions_normalize_to_none():
    snapshot = {
        "report_suite": {"rsid": "test"},
        "dimensions": [{"id": "variables/evar1", "name": "X", "description": "-"}],
        "metrics": [],
    }
    impl = adapt(snapshot)
    assert impl.dimensions[0].description is None


def test_aa_adapter_rejects_snapshot_without_report_suite():
    with pytest.raises(InvalidSnapshotError, match="report_suite"):
        adapt({"dimensions": [], "metrics": []})


def test_aa_adapter_rejects_snapshot_without_rsid():
    with pytest.raises(InvalidSnapshotError, match="rsid"):
        adapt({"report_suite": {}, "dimensions": [], "metrics": []})


def test_aa_clean_has_no_missing_descriptions(clean_aa):
    impl = adapt(clean_aa)
    components = [*impl.metrics, *impl.dimensions]
    assert all(c.description is not None for c in components)


def test_nesting_depth_counts_container_nesting_only():
    snapshot = {
        "report_suite": {"rsid": "test"},
        "segments": [
            {
                "id": "s_one",
                "name": "One container",
                "definition": {
                    "container": {
                        "func": "container",
                        "context": "hits",
                        "pred": {"func": "streq", "str": "x"},
                    }
                },
            },
            {
                "id": "s_zero",
                "name": "No containers",
                "definition": {"func": "streq", "str": "x"},
            },
            {
                "id": "s_two",
                "name": "Nested containers",
                "definition": {
                    "func": "container",
                    "context": "visits",
                    "pred": {
                        "func": "container",
                        "context": "hits",
                        "pred": {"func": "streq", "str": "x"},
                    },
                },
            },
        ],
    }
    impl = adapt(snapshot)
    depths = {s.id: s.nesting_depth for s in impl.segments}
    assert depths == {"s_one": 1, "s_zero": 0, "s_two": 2}


def test_formula_text_renders_nested_formulas_readably():
    snapshot = {
        "report_suite": {"rsid": "test"},
        "calculated_metrics": [
            {
                "id": "cm_nested",
                "name": "Nested",
                "definition": {
                    "formula": {
                        "func": "divide",
                        "args": [
                            {"func": "add", "args": ["metrics/orders", "metrics/units"]},
                            "metrics/visits",
                        ],
                    }
                },
            }
        ],
    }
    impl = adapt(snapshot)
    cm = impl.calculated_metrics[0]
    assert cm.formula_text == "divide(add(metrics/orders, metrics/units), metrics/visits)"
    assert "{" not in cm.formula_text  # no Python repr leaking to users


def test_classification_without_name_or_id_is_skipped():
    from sdr_visualizer.adapters.aa import _index_classifications

    idx = _index_classifications(
        [
            {"parent": "variables/evar1"},
            {"parent": "variables/evar1", "name": "Campaign"},
        ]
    )
    assert idx == {"variables/evar1": ["Campaign"]}


# ---------------------------------------------------------------------------
# Fuzz-found regressions: malformed optional fields must degrade gracefully,
# never raise a bare TypeError/ValueError (see tests/test_adapter_fuzz.py).
# ---------------------------------------------------------------------------


def test_truthy_non_list_tags_coerce_to_empty():
    snap = json.loads((FIXTURES / "aa_snapshot_clean.json").read_text(encoding="utf-8"))
    snap["dimensions"][0]["tags"] = 7  # not a list
    impl = adapt(snap)  # must not raise "'int' object is not iterable"
    assert impl.dimensions[0].tags == []


def test_present_non_list_optional_section_rejected_not_bare_error():
    # _optional_list (vendored from sdr-grader): a null/absent section is [],
    # but a present non-list value is a malformed export -> InvalidSnapshotError,
    # never a bare "'int' object is not iterable". Matches the grader and the
    # CJA adapter's own _section_records.
    snap = json.loads((FIXTURES / "aa_snapshot_clean.json").read_text(encoding="utf-8"))
    snap["calculated_metrics"] = 7  # present but not a list
    with pytest.raises(InvalidSnapshotError):
        adapt(snap)


def test_absent_optional_sections_are_empty():
    snap = json.loads((FIXTURES / "aa_snapshot_clean.json").read_text(encoding="utf-8"))
    snap["calculated_metrics"] = None
    snap.pop("segments", None)
    impl = adapt(snap)
    assert impl.calculated_metrics == []
    assert impl.segments == []


def test_non_numeric_complexity_score_rejected_as_invalid_not_bare_error():
    # A present-but-unconvertible numeric scalar is a malformed snapshot: it
    # must surface as InvalidSnapshotError (the trend loader skips it; a single
    # snapshot exits 3), never a bare ValueError/TypeError.
    snap = json.loads((FIXTURES / "aa_snapshot_clean.json").read_text(encoding="utf-8"))
    snap["calculated_metrics"][0]["complexity_score"] = "high"  # not float()-able
    with pytest.raises(InvalidSnapshotError):
        adapt(snap)


def test_scalar_formula_args_render_without_crashing():
    # Fuzz-found (1.0.1): a calc metric whose definition.formula.args is a
    # truthy scalar (e.g. 7) must not crash formula-tree building during
    # render — render-or-InvalidSnapshotError, never a bare TypeError.
    snap = json.loads((FIXTURES / "aa_snapshot_clean.json").read_text(encoding="utf-8"))
    snap["calculated_metrics"][0]["definition"] = {"formula": {"func": "add", "args": 7}}
    html = render(adapt(snap))
    assert "<html" in html.lower()


# ---------------------------------------------------------------------------
# sdr-grader parity: stringified JSON tag lists parse (SPEC §11/§15).
# ---------------------------------------------------------------------------


def test_stringified_tags_are_parsed_not_dropped():
    snap = json.loads((FIXTURES / "aa_snapshot_clean.json").read_text(encoding="utf-8"))
    snap["dimensions"][0]["tags"] = '["x", "y"]'
    impl = adapt(snap)
    assert impl.dimensions[0].tags == ["x", "y"]


def test_nan_complexity_score_passes_through_adapter_for_renderer_to_reject():
    # Deliberate divergence from sdr-grader: the visualizer passes NaN through
    # so the renderer's allow_nan=False guard rejects the snapshot (audit H2)
    # rather than silently substituting 0.0.
    import math

    snap = json.loads((FIXTURES / "aa_snapshot_clean.json").read_text(encoding="utf-8"))
    snap["calculated_metrics"][0]["complexity_score"] = float("nan")
    impl = adapt(snap)
    assert math.isnan(impl.calculated_metrics[0].complexity_score)


# ---------------------------------------------------------------------------
# Q5 (1.0.0): generator-version compatibility warning helper. Warn-only,
# never refuse. Mirrored to sdr-grader (SPEC §11/§15).
# ---------------------------------------------------------------------------


def test_newer_generator_version_warns():
    from sdr_visualizer.adapters.aa import (
        TESTED_THROUGH_GENERATOR_VERSION,
        generator_version_warning,
    )

    msg = generator_version_warning("99.0.0")
    assert msg is not None
    assert TESTED_THROUGH_GENERATOR_VERSION in msg
    assert "99.0.0" in msg


def test_equal_older_or_unparseable_versions_do_not_warn():
    from sdr_visualizer.adapters.aa import (
        TESTED_THROUGH_GENERATOR_VERSION,
        generator_version_warning,
    )

    assert generator_version_warning(TESTED_THROUGH_GENERATOR_VERSION) is None
    assert generator_version_warning("0.0.1") is None
    assert generator_version_warning("unknown") is None
    assert generator_version_warning("") is None
    assert generator_version_warning("3.5.x") is None


def test_tuple_length_mismatch_versions_compare_correctly():
    from sdr_visualizer.adapters.aa import generator_version_warning

    assert generator_version_warning("1.19") is not None
    assert generator_version_warning("1.18") is None
