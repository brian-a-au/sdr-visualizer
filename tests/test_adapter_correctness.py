"""Adapter → analysis → schema payload regressions."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest
from adapter_cases import aa_case, cja_case

from sdr_visualizer.adapters.aa import adapt as aa_adapt
from sdr_visualizer.adapters.cja import adapt as cja_adapt
from sdr_visualizer.analysis.diff import diff_implementations
from sdr_visualizer.render.renderer import build_payload_with_options as build_payload

SCHEMA = json.loads(Path("docs/payload-schema.json").read_text())


@pytest.mark.parametrize(
    "case,adapt,source,targets",
    [
        (aa_case, aa_adapt, "calc/ratio", {"metrics/revenue", "metrics/visitors"}),
        (aa_case, aa_adapt, "segments/page", {"variables/page"}),
        (cja_case, cja_adapt, "segments/channel", {"variables/channel"}),
    ],
)
def test_actual_adapter_graph_payload(case, adapt, source, targets):
    payload = build_payload(adapt(case()))
    jsonschema.validate(payload, SCHEMA)
    assert {e["target"] for e in payload["graph"]["edges"] if e["source"] == source} == targets


def test_named_operand_comparison():
    old = aa_case()
    new = copy.deepcopy(old)
    new["calculated_metrics"][0]["definition"]["formula"]["col1"]["name"] = "metrics/orders"
    assert diff_implementations(aa_adapt(old), aa_adapt(old))["modified"] == []
    assert diff_implementations(aa_adapt(old), aa_adapt(new))["modified"]


@pytest.mark.parametrize("present", [True, False])
@pytest.mark.parametrize(
    "key,literal",
    [
        ("str", "metrics/documentation"),
        ("list", ["segments/example", "variables/example"]),
        ("glob", "calculatedMetrics/example*"),
    ],
)
def test_typed_segment_references_exclude_literals(present, key, literal):
    snap = aa_case()
    snap["dimensions"] = snap["dimensions"] if present else []
    snap["segments"][0]["definition"] = {
        "func": "streq",
        "val": {"func": "attr", "name": "variables/page"},
        key: literal,
        "description": "metrics/orders",
    }
    impl = aa_adapt(snap)
    assert impl.segments[0].references == ["variables/page"]
    assert impl.segments[0].reference_types == {"dimension": ["variables/page"]}
    payload = build_payload(impl)
    edges = [e for e in payload["graph"]["edges"] if e["source"] == "segments/page"]
    assert len(edges) == int(present)
    assert payload["segment_trees"]["segments/page"]["resolved_id"] == (
        "variables/page" if present else None
    )


@pytest.mark.parametrize("present", [True, False])
@pytest.mark.parametrize("outer", [True, False])
def test_saved_filters_preserved_in_formula_tree_comparison_and_trend(present, outer):
    from sdr_visualizer.analysis.trend import build_trend

    snap = aa_case()
    definition = snap["calculated_metrics"][0]["definition"]
    context = definition if outer else definition["formula"]
    context["filters"] = [
        {"func": "segment-ref", "id": "segments/page", "description": "metrics/label"}
    ]
    if not present:
        snap["segments"] = []
    old = aa_adapt(snap)
    metric = old.calculated_metrics[0]
    assert metric.formula == (definition if outer else definition["formula"])
    assert metric.references == ["metrics/revenue", "metrics/visitors", "segments/page"]
    payload = build_payload(old)
    tree = payload["formula_trees"][metric.id]
    assert tree["kind"] == "filtered_formula"
    assert tree["filters"][0]["resolved_id"] == ("segments/page" if present else None)
    assert "segments/page" in metric.formula_text
    reordered = copy.deepcopy(snap)
    reordered["calculated_metrics"][0]["definition"] = dict(reversed(list(definition.items())))
    assert diff_implementations(old, aa_adapt(reordered))["modified"] == []
    context["filters"][0]["id"] = "segments/other"
    new = aa_adapt(snap)
    assert {f["field"] for f in diff_implementations(old, new)["modified"][0]["fields"]} == {
        "formula_text",
        "references",
    }
    assert build_trend([old, new], capped=False)["intervals"][0]["modified"] == [metric.id]


@pytest.mark.parametrize("func", ["event", "metric"])
def test_segment_event_reference_and_anatomy(func):
    snap = aa_case()
    snap["segments"][0]["definition"] = {
        "func": "gt",
        "num": 0,
        "val": {"func": "total", "evt": {"func": func, "name": "metrics/revenue"}},
    }
    impl = aa_adapt(snap)
    assert impl.segments[0].reference_types == {"metric": ["metrics/revenue"]}
    tree = build_payload(impl)["segment_trees"]["segments/page"]
    assert tree["target_id"] == tree["resolved_id"] == "metrics/revenue"


@pytest.mark.parametrize(
    "inventory,ref,scope,target",
    [
        (
            ["variables/group/channel"],
            "dimensions/group/channel",
            "dimension",
            "variables/group/channel",
        ),
        (
            ["dimensions/group/channel"],
            "variables/group/channel",
            "dimension",
            "dimensions/group/channel",
        ),
        (
            ["variables/channel", "dimensions/channel"],
            "dimensions/channel",
            "dimension",
            "dimensions/channel",
        ),
        (["variables/channel"], "dimensions/group/channel", "dimension", None),
        (["variables/channel"], "metrics/channel", "dimension", None),
        (["variables/channel"], "dimensions/channel", "metric", None),
        ([], "dimensions/channel", "dimension", None),
    ],
)
def test_cja_full_aliases_preserve_namespaces_and_paths(inventory, ref, scope, target):
    snap = cja_case()
    snap["dimensions"] = [{"id": id_} for id_ in inventory]
    snap["metrics"] = [{"id": "metrics/channel"}]
    segment = snap["segments"]["segments"][0]
    segment.pop("dimension_references")
    segment[scope + "_references"] = [ref, ref]
    segment["definition_json"]["val"] = {
        "func": "attr" if scope == "dimension" else "metric",
        "name": ref,
    }
    impl = cja_adapt(snap)
    payload = build_payload(impl)
    assert impl.segments[0].references == [ref]
    assert [e["target"] for e in payload["graph"]["edges"]] == ([target] if target else [])
    tree = payload["segment_trees"]["segments/channel"]
    assert tree["target_id"] == ref
    assert tree["resolved_id"] == target
    assert payload["segments"][0]["out_degree"] == int(target is not None)
    from sdr_visualizer.analysis.trend import compute_aggregates

    aggregates = compute_aggregates(impl)
    assert aggregates["edges"] == int(target is not None)
    assert aggregates["orphans"] == aggregates["total"] - int(target is not None)


def test_cja_derived_references_use_same_full_alias_resolution():
    snap = cja_case()
    snap["derived_fields"] = {
        "fields": [
            {
                "component_id": "variables/derived",
                "component_references": '["dimensions/channel", "metrics/channel", "dimensions/missing"]',
            }
        ]
    }
    payload = build_payload(cja_adapt(snap))
    edges = [e for e in payload["graph"]["edges"] if e["source"] == "variables/derived"]
    assert [e["target"] for e in edges] == ["variables/channel"]
    assert (
        next(c for c in payload["components"] if c["id"] == "variables/channel")["in_degree"] == 2
    )


def test_outer_non_reference_filter_change_is_not_lost():
    snap = aa_case()
    definition = snap["calculated_metrics"][0]["definition"]
    definition["filters"] = [
        {"func": "streq", "val": {"func": "attr", "name": "variables/page"}, "str": "one"}
    ]
    old = aa_adapt(copy.deepcopy(snap))
    definition["filters"][0]["str"] = "two"
    new = aa_adapt(snap)
    changes = diff_implementations(old, new)["modified"]
    assert [f["field"] for f in changes[0]["fields"]] == ["formula_text"]


@pytest.mark.parametrize(
    "operand,scope,ref",
    [
        ({"func": "attr", "name": "variables/page"}, "dimension", "variables/page"),
        ({"func": "event", "name": "metrics/revenue"}, "metric", "metrics/revenue"),
        ({"func": "segment-ref", "id": "segments/page"}, "segment", "segments/page"),
        ("segments/page", "segment", "segments/page"),
        ("calculatedMetrics/other", "metric", "calculatedMetrics/other"),
    ],
)
def test_formula_wrappers_and_reference_kinds(operand, scope, ref):
    snap = aa_case()
    formula = {"func": "visualization-group", "col": {"func": "sum", "args": [operand]}}
    snap["calculated_metrics"][0]["definition"]["formula"] = formula
    impl = aa_adapt(snap)
    assert impl.calculated_metrics[0].reference_types == {scope: [ref]}
    tree = build_payload(impl)["formula_trees"]["calc/ratio"]["args"][0]["args"][0]
    assert tree.get("metric_id", tree.get("segment_id")) == ref
    assert tree["resolved_id"] == (None if ref == "calculatedMetrics/other" else ref)


def test_saved_segment_scope_and_malformed_event_keep_descriptive_fallback():
    snap = aa_case()
    snap["calculated_metrics"][0]["definition"]["formula"] = {
        "func": "segment",
        "name": "segments/page",
        "col": {"func": "metric", "name": "metrics/revenue"},
    }
    snap["segments"][0]["definition"] = {
        "func": "gt",
        "val": {"func": "total", "evt": None},
        "num": 1,
    }
    impl = aa_adapt(snap)
    assert impl.calculated_metrics[0].references == ["segments/page", "metrics/revenue"]
    tree = build_payload(impl)["segment_trees"]["segments/page"]
    assert tree["target_id"] is None


def test_typed_metric_cannot_link_dimension_with_matching_id():
    snap = aa_case()
    snap["calculated_metrics"][0]["definition"]["formula"] = {
        "func": "metric",
        "name": "variables/page",
    }
    payload = build_payload(aa_adapt(snap))
    assert payload["calculated_metrics"][0]["out_degree"] == 0
    assert payload["formula_trees"]["calc/ratio"]["resolved_id"] is None


def test_formula_summaries_preserve_operand_types():
    snap = aa_case()
    formula = {"func": "sum", "args": [1]}
    snap["calculated_metrics"][0]["definition"]["formula"] = formula
    old = aa_adapt(copy.deepcopy(snap))
    formula["args"] = ["1"]
    assert diff_implementations(old, aa_adapt(snap))["modified"]
    formula["args"] = [{"func": "metric", "name": "shared"}]
    old = aa_adapt(copy.deepcopy(snap))
    formula["args"][0]["func"] = "attr"
    assert diff_implementations(old, aa_adapt(snap))["modified"]


@pytest.mark.parametrize(
    "declared,scope,target",
    [
        ("Dimension", "dimension", "variables/derived"),
        ("Metric", "dimension", None),
        (None, None, "variables/derived"),
        (None, "dimension", None),
    ],
)
def test_alias_target_derived_field_kind_is_not_invented(declared, scope, target):
    from sdr_visualizer.analysis.references import build_reference_graph

    snap = cja_case()
    snap["derived_fields"] = {
        "fields": [{"component_id": "variables/derived", "component_type": declared}]
    }
    impl = cja_adapt(snap)
    segment = impl.segments[0]
    segment.references = ["dimensions/derived"]
    segment.reference_types = {scope: segment.references} if scope else {}
    graph = build_reference_graph(impl)
    assert [e["target"] for e in graph["edges"]] == ([target] if target else [])


@pytest.mark.parametrize("reference,target", [("saved", "saved"), ("segments/saved", None)])
def test_saved_filter_uses_exact_exported_identity(reference, target):
    snap = aa_case()
    snap["segments"][0]["id"] = "saved"
    snap["calculated_metrics"][0]["definition"]["filters"] = [
        {"func": "segment-ref", "id": reference}
    ]
    impl = aa_adapt(snap)
    assert reference in impl.calculated_metrics[0].references
    tree = build_payload(impl)["formula_trees"]["calc/ratio"]["filters"][0]
    assert tree["segment_id"] == reference
    assert tree["resolved_id"] == target


@pytest.mark.parametrize(
    "definition", [42, "invalid", [1], [[1]], [{"func": "metric", "name": "metrics/revenue"}]]
)
def test_malformed_aa_definition_retains_empty_fallback(definition):
    snap = aa_case()
    snap["calculated_metrics"][0]["definition"] = definition
    impl = aa_adapt(snap)
    metric = impl.calculated_metrics[0]
    assert metric.formula == {}
    assert metric.formula_text == ""
    assert metric.references == []
    build_payload(impl)


def test_malformed_segment_definition_does_not_invent_references():
    snap = aa_case()
    snap["segments"][0]["definition"] = [{"func": "attr", "name": "variables/page"}]
    segment = aa_adapt(snap).segments[0]
    assert segment.definition == {}
    assert segment.references == []
