"""AA adapter tests (SPEC-VISUALIZER §10 Phase 7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdr_visualizer.adapters.aa import adapt
from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.input.detect import detect_platform

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
