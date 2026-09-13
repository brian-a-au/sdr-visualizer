"""CJA 0.3.1 behavior, not claims of exact or complete matching."""

import copy

from test_workspace_usage_sdk import project

from sdr_visualizer.usage.sdk_worker import match_projects


def test_cja_regex_prefix_and_first_workspace():
    first = project("fooXbar-extra")
    second = project("hidden")["definition"]["workspaces"][0]
    first["definition"]["workspaces"].append(second)
    records = match_projects(
        "cja",
        [first],
        [{"type": "dimension", "id": value} for value in ["foo.bar", "fooX", "hidden"]],
        None,
    ).results
    assert [bool(r["projects"]) for r in records] == [True, True, False]
    assert all(r["match_basis"] == "unverified_lookup" for r in records)


def test_cja_multiple_panel_contexts_are_not_excluded():
    definition = project("elsewhere")
    panel = copy.deepcopy(definition["definition"]["workspaces"][0]["panels"][0])
    panel["id"] = "another-panel"
    panel["rsid"] = "another-data-view"
    panel["subPanels"][0]["reportlet"]["freeformTable"]["dimension"]["id"] = "target"
    definition["definition"]["workspaces"][0]["panels"].append(panel)
    result = match_projects("cja", [definition], [{"type": "dimension", "id": "target"}], None)
    assert result.results[0]["projects"]


def test_cja_mobile_guided_missing_type_and_parser_error_keep_other_positive():
    mobile = project(project_id="mobile")
    mobile["definition"]["device"] = "cell"
    guided = {
        "id": "guided",
        "name": "Guided",
        "type": "guidedAnalysis",
        "definition": {"events": [], "peopleSegments": []},
    }
    missing = project(project_id="missing")
    del missing["type"]
    malformed = project(project_id="malformed")
    malformed["definition"]["workspaces"] = []
    result = match_projects(
        "cja",
        [mobile, guided, missing, malformed, project()],
        [{"type": "dimension", "id": "variables/evar1"}],
        None,
    )
    assert result.results[0]["projects"] == [{"id": "p1", "name": "Synthetic project"}]
    assert result.limitations


def test_cja_regex_error_retains_completed_and_leaves_later_absent():
    result = match_projects(
        "cja",
        [project("0good")],
        [{"type": "dimension", "id": value} for value in ["0good", "[", "zlater"]],
        None,
    )
    assert len(result.results) == 2
    assert result.results[0]["projects"]
    assert result.results[1]["failure"] == "collection_error"
