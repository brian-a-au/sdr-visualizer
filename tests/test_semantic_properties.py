"""Bounded semantic variations with expectations independent of the resolver/diff.

AA operands/filters/constants and browser navigation already have adapter_cases
regressions. These properties cover CJA declarations and comparison boundaries.
"""

import copy
from itertools import permutations

import pytest
from adapter_cases import cja_case

from sdr_visualizer.adapters.cja import adapt
from sdr_visualizer.analysis.diff import diff_implementations
from sdr_visualizer.analysis.references import build_reference_graph
from sdr_visualizer.analysis.trend import build_trend
from sdr_visualizer.render.renderer import build_payload_with_options as build_payload


def _consumer_case(kind):
    snapshot = cja_case()
    if kind == "segment":
        record = snapshot["segments"]["segments"][0]
        record.pop("dimension_references")
        return snapshot, record, "segments/channel", "dimension"
    snapshot["metrics"] = [{"id": "metrics/revenue"}, {"id": "metrics/orders"}]
    snapshot["segments"] = {"segments": []}
    record = {
        "metric_id": "calc/consumer",
        "formula_summary": "Exported summary",
        "definition_json": {"func": "metric", "name": "metrics/revenue"},
    }
    snapshot["calculated_metrics"] = {"metrics": [record]}
    return snapshot, record, "calc/consumer", "metric"


@pytest.mark.parametrize("kind", ["segment", "calculated_metric"])
@pytest.mark.parametrize("explicit_empty", [False, True], ids=["omitted", "empty"])
@pytest.mark.parametrize("reverse", [False, True])
def test_raw_omission_and_empty_arrays_have_available_normalized_scopes(
    kind, explicit_empty, reverse
):
    snapshot, record, consumer, scope = _consumer_case(kind)
    if explicit_empty:
        keys = (
            ("dimension_references", "metric_references", "other_segment_references")
            if kind == "segment"
            else ("metric_references", "segment_references")
        )
        record.update(dict.fromkeys(keys, []))
    empty = adapt(copy.deepcopy(snapshot))
    entity = empty.segments[0] if kind == "segment" else empty.calculated_metrics[0]
    assert entity.references == []
    assert entity.reference_types == (
        {"dimension": [], "metric": [], "segment": []}
        if kind == "segment"
        else {"metric": [], "segment": []}
    )
    record[scope + "_references"] = ["source-id"]
    populated = adapt(snapshot)
    old, new = (populated, empty) if reverse else (empty, populated)
    added, removed = ([], ["source-id"]) if reverse else (["source-id"], [])
    changes = diff_implementations(old, new)
    assert changes["added"] == changes["removed"] == []
    assert changes["modified"] == [
        {
            "id": consumer,
            "name": consumer,
            "type": kind,
            "fields": [
                {"field": "references", "added": added, "removed": removed},
                {"field": f"reference_types.{scope}", "added": added, "removed": removed},
            ],
        }
    ]
    assert build_trend([old, new], capped=False)["intervals"][0]["modified"] == [consumer]


# Dimension/metric pairs are already pinned in test_adapter_correctness.
@pytest.mark.parametrize(
    "old_scope,new_scope",
    [(a, b) for a, b in permutations(("dimension", "metric", "segment"), 2) if "segment" in (a, b)],
)
@pytest.mark.parametrize("present", [False, True])
def test_segment_scope_transitions_preserve_source_and_exact_destinations(
    old_scope, new_scope, present
):
    snapshot, record, consumer, _ = _consumer_case("segment")
    destinations = {
        "dimension": "variables/shared",
        "metric": "metrics/shared",
        "segment": "segments/shared",
    }
    snapshot["dimensions"] = [{"id": "variables/shared"}] if present else []
    snapshot["metrics"] = [{"id": "metrics/shared"}] if present else []
    if present:
        snapshot["segments"]["segments"].append({"segment_id": "segments/shared"})
    keys = {
        "dimension": "dimension_references",
        "metric": "metric_references",
        "segment": "other_segment_references",
    }
    record[keys[old_scope]] = ["shared"]
    old = adapt(copy.deepcopy(snapshot))
    record.pop(keys[old_scope])
    record[keys[new_scope]] = ["shared"]
    new = adapt(snapshot)
    for implementation, scope in ((old, old_scope), (new, new_scope)):
        assert implementation.segments[0].references == ["shared"]
        graph = build_reference_graph(implementation)
        assert graph["edges"] == (
            [{"source": consumer, "target": destinations[scope], "kind": "references"}]
            if present
            else []
        )
        assert graph["unresolved"] == (
            []
            if present
            else [
                {
                    "source": consumer,
                    "reference": "shared",
                    "reference_type": scope,
                    "reason": "missing",
                }
            ]
        )
    changes = diff_implementations(old, new)
    assert changes["added"] == changes["removed"] == []
    assert changes["modified"] == [
        {
            "id": consumer,
            "name": consumer,
            "type": "segment",
            "fields": sorted(
                [
                    {"field": f"reference_types.{old_scope}", "added": [], "removed": ["shared"]},
                    {"field": f"reference_types.{new_scope}", "added": ["shared"], "removed": []},
                ],
                key=lambda field: field["field"],
            ),
        }
    ]
    assert build_trend([old, new], capped=False)["intervals"][0]["modified"] == [consumer]


@pytest.mark.parametrize("order", list(permutations(("a", "b", "c"))))
def test_declared_reference_permutations_and_duplicates_preserve_membership(order):
    snapshot, record, consumer, _ = _consumer_case("segment")
    snapshot["dimensions"] = [{"id": f"variables/{name}"} for name in ("a", "b", "c")]
    record["dimension_references"] = ["a", "b", "c"]
    old = adapt(copy.deepcopy(snapshot))
    record["dimension_references"] = [*order, order[0], order[-1]]
    new = adapt(snapshot)
    assert new.segments[0].references == list(order)
    graph = build_reference_graph(new)
    assert {(edge["source"], edge["target"]) for edge in graph["edges"]} == {
        (consumer, "variables/a"),
        (consumer, "variables/b"),
        (consumer, "variables/c"),
    }
    assert len(graph["edges"]) == graph["out_degree"][consumer] == 3
    changes = diff_implementations(old, new)
    assert changes["added"] == changes["removed"] == changes["modified"] == []
    assert build_trend([old, new], capped=False)["intervals"][0]["modified"] == []


@pytest.mark.parametrize("kind", ["segment", "calculated_metric"])
def test_raw_definition_changes_do_not_override_cja_declarations_or_comparison(kind):
    snapshot, record, consumer, scope = _consumer_case(kind)
    declared, first, second = (
        ("dimensions/declared", "dimensions/channel", "dimensions/other")
        if kind == "segment"
        else ("metrics/declared", "metrics/revenue", "metrics/orders")
    )
    if kind == "segment":
        snapshot["dimensions"].append({"id": "variables/other"})
    record[scope + "_references"] = [declared]
    old = adapt(copy.deepcopy(snapshot))
    definition = record["definition_json"]
    (definition["val"] if kind == "segment" else definition)["name"] = second
    new = adapt(snapshot)
    tree_key = "segment_trees" if kind == "segment" else "formula_trees"
    source_key = "target_id" if kind == "segment" else "metric_id"
    for implementation, source in ((old, first), (new, second)):
        payload = build_payload(implementation)
        assert payload["graph"]["edges"] == []
        assert build_reference_graph(implementation)["unresolved"] == [
            {
                "source": consumer,
                "reference": declared,
                "reference_type": scope,
                "reason": "missing",
            }
        ]
        tree = payload[tree_key][consumer]
        assert tree[source_key] == source
        assert tree["resolved_id"] == source.replace("dimensions/", "variables/")
    changes = diff_implementations(old, new)
    assert changes["added"] == changes["removed"] == changes["modified"] == []
    assert build_trend([old, new], capped=False)["intervals"][0]["modified"] == []
