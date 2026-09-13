"""AA 0.5.3.post1 is characterized separately from CJA."""

import copy

from test_workspace_usage_sdk import project

from sdr_visualizer.usage.sdk_worker import match_projects


def test_aa_prefix_boundary_and_metacharacter_behavior():
    result = match_projects(
        "aa",
        [project("variables/evar10")],
        [
            {"type": "dimension", "id": value}
            for value in ["variables/evar1", "variables/evar1.", "variables/evar10"]
        ],
        None,
    )
    assert [bool(r["projects"]) for r in result.results] == [False, True, True]
    assert all(r["status"] == "partial" for r in result.results)


def test_aa_first_workspace_multi_context_and_mobile():
    definition = project("first")
    panel = copy.deepcopy(definition["definition"]["workspaces"][0]["panels"][0])
    panel["id"] = "second"
    panel["rsid"] = "different-suite"
    panel["subPanels"][0]["reportlet"]["freeformTable"]["dimension"]["id"] = "another"
    definition["definition"]["workspaces"][0]["panels"].append(panel)
    definition["definition"]["workspaces"].append(project("hidden")["definition"]["workspaces"][0])
    mobile = project("mobile", project_id="mobile")
    mobile["definition"]["device"] = "cell"
    result = match_projects(
        "aa",
        [definition, mobile],
        [{"type": "dimension", "id": value} for value in ["another", "first", "hidden", "mobile"]],
        None,
    )
    assert [bool(r["projects"]) for r in result.results] == [True, True, False, False]
    assert result.limitations


def test_aa_saved_segment_and_non_s_template_remain_candidates_only():
    definition = project()
    panel = definition["definition"]["workspaces"][0]["panels"][0]
    panel["segmentGroups"] = [
        {"dynamicDimension": {"type": "Segment", "id": value}}
        for value in ["sSaved", "templateSegment"]
    ]
    result = match_projects(
        "aa",
        [definition],
        [{"type": "segment", "id": value} for value in ["sSaved", "templateSegment"]],
        None,
    )
    assert result.results[0]["projects"]
    assert not result.results[1]["projects"]
    assert all(r["status"] == "partial" for r in result.results)


def test_aa_invalid_regex_stops_without_erasing_completed():
    result = match_projects(
        "aa",
        [project("0good")],
        [{"type": "dimension", "id": value} for value in ["0good", "[", "zlater"]],
        None,
    )
    assert len(result.results) == 2
    assert result.results[0]["projects"]
    assert result.results[1]["failure"] == "collection_error"


def test_aa_calculated_metric_does_not_add_transitive_saved_segment():
    definition = project()
    reportlet = definition["definition"]["workspaces"][0]["panels"][0]["subPanels"][0]["reportlet"]
    reportlet["columnTree"]["nodes"] = [
        {"component": {"type": "CalculatedMetric", "id": "cmSaved"}, "nodes": []}
    ]
    result = match_projects(
        "aa",
        [definition],
        [{"type": "calculated_metric", "id": "cmSaved"}, {"type": "segment", "id": "sSaved"}],
        None,
    )
    assert result.results[0]["projects"]
    assert not result.results[1]["projects"]
    assert result.results[1]["status"] == "partial"
