"""Contract tests for normalized CJA dataset lineage discovery."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sdr_visualizer.adapters.cja_lineage import adapt
from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.lineage import (
    Availability,
    Coverage,
    DatasetDataSource,
    ReportedValue,
)
from sdr_visualizer.core.structure_limits import MAX_STRUCTURE_DEPTH, MAX_STRUCTURE_NODES

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _record(
    *,
    data_view_id: str = "dv-1",
    data_view_name: str = "View one",
    connection_id: str | None = "conn-1",
    connection_name: str | None = "Connection one",
    datasets: list[dict] | None = None,
) -> dict:
    return {
        "id": data_view_id,
        "name": data_view_name,
        "connection": {"id": connection_id, "name": connection_name},
        "datasets": [] if datasets is None else datasets,
    }


def _snapshot(*records: dict, warning: object = None) -> dict:
    value = {"dataViews": list(records), "count": len(records)}
    if warning is not None:
        value["warning"] = warning
    return value


def _nested(depth: int) -> object:
    value: object = 0
    for _ in range(depth):
        value = {"child": value}
    return value


def test_shared_topology_deduplicates_entities_edges_and_retains_provenance() -> None:
    topology = adapt(_load("cja_lineage_shared.json"), scope_label="Synthetic sandbox")

    assert topology.scope_label == "Synthetic sandbox"
    assert topology.coverage is Coverage.ACCESSIBLE_SCOPE
    assert [dataset.id for dataset in topology.datasets] == ["ds-mobile", "ds-web"]
    assert [connection.id for connection in topology.connections] == ["conn-shared"]
    assert [view.id for view in topology.data_views] == ["dv-exploration", "dv-production"]

    connection = topology.connections[0]
    assert connection.detail_availability is Availability.AVAILABLE
    assert connection.dataset_availability is Availability.AVAILABLE
    assert connection.dataset_ids == ("ds-mobile", "ds-web")
    assert connection.source_record_indexes == (0, 1)

    assert len(topology.dataset_connections) == 2
    assert all(edge.source_record_indexes == (0, 1) for edge in topology.dataset_connections)
    assert [(edge.connection_id, edge.data_view_id) for edge in topology.connection_data_views] == [
        ("conn-shared", "dv-exploration"),
        ("conn-shared", "dv-production"),
    ]
    assert [edge.source_record_indexes for edge in topology.connection_data_views] == [(1,), (0,)]


def test_legacy_dataset_relationships_have_unknown_connection_metadata() -> None:
    topology = adapt(_load("cja_lineage_shared.json"), scope_label="Synthetic sandbox")

    assert all(edge.connection_metadata is None for edge in topology.dataset_connections)


def test_connection_metadata_is_relationship_scoped_and_preserves_reported_values() -> None:
    topology = adapt(_load("cja_lineage_enriched.json"), scope_label="Synthetic sandbox")
    edges = {(edge.dataset_id, edge.connection_id): edge for edge in topology.dataset_connections}

    assert {edge.connection_metadata.role.value for edge in edges.values()} == {
        "event",
        "profile",
        "lookup",
        "summary",
    }
    event = edges[("ds-shared", "conn-event")].connection_metadata
    profile = edges[("ds-shared", "conn-profile")].connection_metadata
    assert event is not None and profile is not None
    assert event.role == ReportedValue("event")
    assert profile.role == ReportedValue("profile")
    assert event.schema.value.name == ReportedValue("Web Event Schema")
    assert event.schema.value.ref.value.content_type == ReportedValue(
        "application/vnd.adobe.xed-full+json;version=1"
    )
    assert event.identity.value.use_primary_id_namespace == ReportedValue(False)
    assert event.ingestion.value.streaming == ReportedValue(True)
    assert event.ingestion.value.backfill_summary.value.failed == ReportedValue(0)
    assert event.ingestion.value.backfill_summary.value.invalid == ReportedValue(False)
    assert profile.identity.value.namespace == ReportedValue(None)
    assert profile.identity.value.namespace_column == ReportedValue("")
    assert profile.data_source == ReportedValue(DatasetDataSource())
    lookup = edges[("ds-lookup", "conn-lookup")].connection_metadata.lookup.value
    assert lookup.key_field == ReportedValue("accountId")
    assert lookup.parent_fields == ReportedValue(("accountId", "accountName"))
    assert lookup.parent_dataset_id == ReportedValue("ds-shared")
    summary = edges[("ds-summary", "conn-summary")].connection_metadata
    assert summary.lookup.value.parent_fields == ReportedValue(())


@pytest.mark.parametrize("connection_metadata", [None, [], "metadata", 7, True])
def test_malformed_connection_metadata_container_is_treated_as_unavailable(
    connection_metadata: object,
) -> None:
    topology = adapt(
        _snapshot(
            _record(
                datasets=[
                    {
                        "id": "ds-1",
                        "name": "Dataset one",
                        "connectionMetadata": connection_metadata,
                    }
                ]
            )
        ),
        scope_label="Synthetic sandbox",
    )

    assert topology.dataset_connections[0].connection_metadata is None


def test_null_and_malformed_nested_values_remain_best_effort() -> None:
    metadata = {
        "role": "bad\u202evalue",
        "schema": None,
        "identity": {
            "timestampId": None,
            "visitorId": 9,
            "usePrimaryIdNamespace": None,
            "identityMap": None,
        },
        "lookup": {
            "keyField": None,
            "parentFields": None,
            "parentDatasetId": ["bad"],
        },
        "ingestion": {
            "streaming": None,
            "backfillSummary": {
                "total": None,
                "failed": True,
                "inProgress": "unknown",
                "invalid": None,
            },
            "lastIngestedTime": None,
            "streamingEnabledAt": 7,
        },
        "dataSource": None,
    }
    topology = adapt(
        _snapshot(
            _record(
                datasets=[
                    {
                        "id": "ds-1",
                        "name": "Dataset one",
                        "connectionMetadata": metadata,
                    }
                ]
            )
        ),
        scope_label="Synthetic sandbox",
    )
    parsed = topology.dataset_connections[0].connection_metadata

    assert parsed.role is None
    assert parsed.schema == ReportedValue(None)
    assert parsed.identity.value.timestamp_id == ReportedValue(None)
    assert parsed.identity.value.visitor_id is None
    assert parsed.identity.value.use_primary_id_namespace == ReportedValue(None)
    assert parsed.lookup.value.key_field == ReportedValue(None)
    assert parsed.lookup.value.parent_fields == ReportedValue(None)
    assert parsed.lookup.value.parent_dataset_id is None
    assert parsed.ingestion.value.streaming == ReportedValue(None)
    assert parsed.ingestion.value.backfill_summary.value.total == ReportedValue(None)
    assert parsed.ingestion.value.backfill_summary.value.failed is None
    assert parsed.ingestion.value.backfill_summary.value.in_progress is None
    assert parsed.ingestion.value.backfill_summary.value.invalid == ReportedValue(None)
    assert parsed.ingestion.value.last_ingested_time == ReportedValue(None)
    assert parsed.ingestion.value.streaming_enabled_at is None
    assert parsed.data_source == ReportedValue(None)


def test_malformed_optional_metadata_is_ignored_without_losing_base_relationship() -> None:
    malformed = _snapshot(
        _record(
            datasets=[
                {
                    "id": "ds-1",
                    "name": "Dataset one",
                    "connectionMetadata": {
                        "role": ["event"],
                        "schema": "not-an-object",
                        "identity": {"identityMap": "yes", "namespace": "ECID"},
                        "lookup": {"parentFields": ["valid", 7]},
                        "ingestion": {
                            "streaming": 1,
                            "backfillSummary": {"total": -1, "completed": 0},
                        },
                        "dataSource": {"id": "source", "description": {"bad": True}},
                        "unknownFutureKey": {"anything": [1, 2, 3]},
                    },
                }
            ]
        )
    )

    topology = adapt(malformed, scope_label="Synthetic sandbox")
    edge = topology.dataset_connections[0]

    assert (edge.dataset_id, edge.connection_id) == ("ds-1", "conn-1")
    metadata = edge.connection_metadata
    assert metadata is not None
    assert metadata.role is None and metadata.schema is None
    assert metadata.identity.value.identity_map is None
    assert metadata.identity.value.namespace == ReportedValue("ECID")
    assert metadata.lookup.value.parent_fields is None
    assert metadata.ingestion.value.streaming is None
    assert metadata.ingestion.value.backfill_summary.value.total is None
    assert metadata.ingestion.value.backfill_summary.value.completed == ReportedValue(0)
    assert metadata.data_source.value.id == ReportedValue("source")
    assert metadata.data_source.value.description is None


def test_repeated_relationship_metadata_merges_additively_without_cross_connection_leaks() -> None:
    event_dataset = {
        "id": "ds-shared",
        "name": "Shared",
        "connectionMetadata": {"role": "event", "identity": {"namespace": "ECID"}},
    }
    second_occurrence = copy.deepcopy(event_dataset)
    second_occurrence["connectionMetadata"] = {
        "role": "event",
        "ingestion": {"streaming": False},
    }
    profile_dataset = copy.deepcopy(event_dataset)
    profile_dataset["connectionMetadata"] = {"role": "profile"}
    records = (
        _record(data_view_id="dv-a", datasets=[event_dataset]),
        _record(data_view_id="dv-b", datasets=[second_occurrence]),
        _record(
            data_view_id="dv-c",
            connection_id="conn-2",
            connection_name="Connection two",
            datasets=[profile_dataset],
        ),
    )

    topology = adapt(_snapshot(*records), scope_label="Synthetic sandbox")
    edges = {(edge.dataset_id, edge.connection_id): edge for edge in topology.dataset_connections}

    conn_one = edges[("ds-shared", "conn-1")].connection_metadata
    conn_two = edges[("ds-shared", "conn-2")].connection_metadata
    assert conn_one.role == ReportedValue("event")
    assert conn_one.identity.value.namespace == ReportedValue("ECID")
    assert conn_one.ingestion.value.streaming == ReportedValue(False)
    assert conn_two.role == ReportedValue("profile")
    assert conn_two.identity is None


def test_repeated_relationship_conflicts_are_order_independent_and_remain_unknown() -> None:
    def observation(data_view_id: str, role: str) -> dict:
        return _record(
            data_view_id=data_view_id,
            datasets=[
                {
                    "id": "ds-shared",
                    "name": "Shared",
                    "connectionMetadata": {
                        "role": role,
                        "identity": {"namespace": "ECID"},
                    },
                }
            ],
        )

    records = (
        observation("dv-a", "event"),
        observation("dv-b", "profile"),
        observation("dv-c", "event"),
    )
    forward = adapt(_snapshot(*records), scope_label="Synthetic sandbox")
    reverse = adapt(_snapshot(*reversed(records)), scope_label="Synthetic sandbox")

    forward_metadata = forward.dataset_connections[0].connection_metadata
    reverse_metadata = reverse.dataset_connections[0].connection_metadata
    assert forward_metadata == reverse_metadata
    assert forward_metadata.role is None
    assert forward_metadata.identity.value.namespace == ReportedValue("ECID")


def test_null_connection_name_degrades_record_without_relying_on_global_warning() -> None:
    topology = adapt(
        _snapshot(_record(connection_id="conn-restricted", connection_name=None)),
        scope_label="Partial access",
    )

    assert topology.coverage is Coverage.PERMISSION_DEGRADED
    connection = topology.connections[0]
    view = topology.data_views[0]
    assert connection.id == "conn-restricted"
    assert connection.name is None
    assert connection.detail_availability is Availability.UNAVAILABLE
    assert connection.dataset_availability is Availability.UNAVAILABLE
    assert connection.dataset_ids == ()
    assert view.connection_detail_availability is Availability.UNAVAILABLE
    assert view.dataset_availability is Availability.UNAVAILABLE
    assert topology.connection_data_views[0].source_record_indexes == (0,)
    assert topology.dataset_connections == ()


def test_degraded_fixture_keeps_real_parent_and_suppresses_missing_parent_sentinel() -> None:
    topology = adapt(_load("cja_lineage_degraded.json"), scope_label="Partial access")

    assert topology.coverage is Coverage.PERMISSION_DEGRADED
    assert [connection.id for connection in topology.connections] == ["conn-restricted"]
    assert topology.connections[0].source_record_indexes == (0,)
    assert [(view.id, view.connection_id) for view in topology.data_views] == [
        ("dv-known-parent", "conn-restricted"),
        ("dv-missing-parent", None),
    ]
    assert [(edge.connection_id, edge.data_view_id) for edge in topology.connection_data_views] == [
        ("conn-restricted", "dv-known-parent")
    ]


def test_global_warning_maps_to_controlled_degraded_coverage_only() -> None:
    snapshot = _snapshot(_record(), warning="<script>raw upstream diagnostic</script>")

    topology = adapt(snapshot, scope_label="Synthetic sandbox")

    assert topology.coverage is Coverage.PERMISSION_DEGRADED
    assert not hasattr(topology, "warning")
    assert "raw upstream diagnostic" not in repr(topology)


def test_present_connection_details_make_empty_dataset_list_reported_empty() -> None:
    topology = adapt(_snapshot(_record()), scope_label="Synthetic sandbox")

    connection = topology.connections[0]
    view = topology.data_views[0]
    assert topology.coverage is Coverage.ACCESSIBLE_SCOPE
    assert connection.dataset_availability is Availability.REPORTED_EMPTY
    assert view.dataset_availability is Availability.REPORTED_EMPTY
    assert connection.dataset_ids == ()


def test_empty_data_views_is_a_valid_empty_topology() -> None:
    topology = adapt({"dataViews": [], "count": 0}, scope_label="No accessible views")

    assert topology.coverage is Coverage.ACCESSIBLE_SCOPE
    assert topology.data_views == ()
    assert topology.connections == ()
    assert topology.datasets == ()
    assert topology.connection_data_views == ()
    assert topology.dataset_connections == ()


@pytest.mark.parametrize("sentinel", [None, "N/A", " n/a "])
def test_missing_parent_sentinel_never_creates_a_node_or_edge(sentinel: str | None) -> None:
    topology = adapt(
        _snapshot(_record(connection_id=sentinel, connection_name=None)),
        scope_label="Synthetic sandbox",
    )

    assert topology.connections == ()
    assert topology.connection_data_views == ()
    assert topology.data_views[0].connection_id is None
    assert topology.data_views[0].connection_detail_availability is Availability.UNAVAILABLE
    assert topology.data_views[0].dataset_availability is Availability.UNAVAILABLE


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda value: value["dataViews"].append(
                _record(data_view_id="dv-1", data_view_name="Conflicting view")
            ),
            "conflicting data view name",
        ),
        (
            lambda value: value["dataViews"].append(
                _record(data_view_id="dv-2", connection_name="Conflicting connection")
            ),
            "conflicting connection name",
        ),
    ],
)
def test_real_ids_reject_conflicting_identity_names(mutate, match: str) -> None:
    snapshot = _snapshot(
        _record(datasets=[{"id": "ds-1", "name": "Dataset one"}]),
    )
    mutate(snapshot)
    snapshot["count"] = len(snapshot["dataViews"])

    with pytest.raises(InvalidSnapshotError, match=match):
        adapt(snapshot, scope_label="Synthetic sandbox")


def test_dataset_name_aliases_merge_to_a_deterministic_canonical_name() -> None:
    records = (
        _record(
            data_view_id="dv-2",
            connection_id="conn-2",
            connection_name="Connection two",
            datasets=[{"id": "ds-1", "name": "Renamed dataset"}],
        ),
        _record(datasets=[{"id": "ds-1", "name": "Dataset one"}]),
    )

    forward = adapt(_snapshot(*records), scope_label="Synthetic sandbox")
    reverse = adapt(_snapshot(*reversed(records)), scope_label="Synthetic sandbox")

    assert forward.coverage is Coverage.ACCESSIBLE_SCOPE
    assert forward.datasets[0].name == "Dataset one"
    assert reverse.datasets[0].name == forward.datasets[0].name
    assert forward.datasets[0].source_record_indexes == (0, 1)


def test_identical_duplicate_data_view_record_is_deduplicated_with_both_indexes() -> None:
    record = _record(datasets=[{"id": "ds-1", "name": "Dataset one"}])
    topology = adapt(_snapshot(record, copy.deepcopy(record)), scope_label="Synthetic sandbox")

    assert len(topology.data_views) == 1
    assert topology.data_views[0].source_record_indexes == (0, 1)
    assert len(topology.connection_data_views) == 1
    assert topology.connection_data_views[0].source_record_indexes == (0, 1)


@pytest.mark.parametrize(
    ("snapshot", "match"),
    [
        ([], "top-level JSON object"),
        ({}, "dataViews"),
        ({"dataViews": {}, "count": 0}, "dataViews.*list"),
        ({"dataViews": [], "count": True}, "count.*integer"),
        ({"dataViews": [], "count": 1}, "count.*does not match"),
        (_snapshot("not-an-object"), "record 0.*object"),
        (
            _snapshot({"id": "dv-1", "name": "View", "connection": {}, "datasets": []}),
            "connection.id",
        ),
        (
            _snapshot(
                _record(
                    connection_id="N/A",
                    connection_name=None,
                    datasets=[{"id": "ds-1", "name": "Invented edge"}],
                )
            ),
            "record 0.*datasets.*missing parent",
        ),
        (
            _snapshot(_record(connection_name=None, datasets=[{"id": "ds-1", "name": "Dataset"}])),
            "record 0.*datasets.*unavailable connection",
        ),
        (
            _snapshot(_record(datasets=[{"id": "N/A", "name": "Dataset"}])),
            "dataset.id",
        ),
    ],
)
def test_malformed_shapes_and_invalid_relationships_are_rejected(snapshot, match: str) -> None:
    with pytest.raises(InvalidSnapshotError, match=match):
        adapt(snapshot, scope_label="Synthetic sandbox")


def test_missing_datasets_is_only_allowed_when_connection_details_are_unavailable() -> None:
    degraded = _record(connection_id="conn-1", connection_name=None)
    degraded.pop("datasets")
    topology = adapt(_snapshot(degraded), scope_label="Synthetic sandbox")
    assert topology.connections[0].dataset_availability is Availability.UNAVAILABLE

    available = _record()
    available.pop("datasets")
    with pytest.raises(InvalidSnapshotError, match="record 0.*datasets.*list"):
        adapt(_snapshot(available), scope_label="Synthetic sandbox")


def test_hostile_markup_stays_data_and_valid_unicode_is_preserved() -> None:
    topology = adapt(_load("cja_lineage_hostile.json"), scope_label="Scope <script> 😀")

    assert topology.scope_label == "Scope <script> 😀"
    assert topology.data_views[0].name == "<img src=x onerror=alert(1)> 😀"
    assert topology.connections[0].name == "</script><script>alert(2)</script>"
    assert topology.datasets[0].name == "<svg onload=alert(3)> café"


def test_ordinary_right_to_left_text_is_preserved() -> None:
    topology = adapt(
        _snapshot(
            _record(
                data_view_id="תצוגה-1",
                data_view_name="תצוגת נתונים",
                connection_id="اتصال-1",
                connection_name="اتصال البيانات",
                datasets=[{"id": "مجموعة-1", "name": "مجموعة البيانات"}],
            )
        ),
        scope_label="نطاق التحليل",
    )

    assert topology.scope_label == "نطاق التحليل"
    assert topology.data_views[0].name == "תצוגת נתונים"
    assert topology.connections[0].name == "اتصال البيانات"
    assert topology.datasets[0].name == "مجموعة البيانات"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["dataViews"][0].__setitem__("id", "dv\u202e-1"),
        lambda value: value["dataViews"][0].__setitem__("name", "view\u2066name"),
        lambda value: value["dataViews"][0]["connection"].__setitem__("id", "conn\u200f-1"),
        lambda value: value["dataViews"][0]["connection"].__setitem__(
            "name", "connection\u202aname"
        ),
        lambda value: value["dataViews"][0]["datasets"][0].__setitem__("id", "dataset\u2069-1"),
        lambda value: value["dataViews"][0]["datasets"][0].__setitem__("name", "dataset\u061cname"),
    ],
)
def test_entity_bidi_controls_fail_without_echoing_content(mutate) -> None:
    snapshot = _snapshot(_record(datasets=[{"id": "ds-1", "name": "Dataset one"}]))
    mutate(snapshot)

    with pytest.raises(InvalidSnapshotError, match="bidirectional control") as exc_info:
        adapt(snapshot, scope_label="Synthetic sandbox")

    assert not any(
        character in str(exc_info.value) for character in "\u061c\u200f\u202a\u202e\u2066\u2069"
    )


@pytest.mark.parametrize("scope_label", ["scope\u202dlabel", "scope\u2068label"])
def test_scope_bidi_controls_fail_without_echoing_content(scope_label: str) -> None:
    with pytest.raises(InvalidSnapshotError, match="bidirectional control") as exc_info:
        adapt(_snapshot(), scope_label=scope_label)

    assert scope_label not in str(exc_info.value)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["dataViews"][0].__setitem__("name", "line\nbreak"),
        lambda value: value["dataViews"][0]["connection"].__setitem__("id", "conn\u009b"),
        lambda value: value["dataViews"][0]["datasets"][0].__setitem__("name", "bad\ud800"),
    ],
)
def test_control_characters_and_lone_surrogates_fail_without_echoing_content(mutate) -> None:
    snapshot = _load("cja_lineage_hostile.json")
    mutate(snapshot)

    with pytest.raises(InvalidSnapshotError) as exc_info:
        adapt(snapshot, scope_label="Synthetic sandbox")

    message = str(exc_info.value)
    assert "line\nbreak" not in message
    assert "\u009b" not in message
    assert not any(0xD800 <= ord(character) <= 0xDFFF for character in message)


def test_per_field_limits_reject_overlong_external_strings() -> None:
    snapshot = _snapshot(_record(data_view_name="x" * 2_049))
    with pytest.raises(InvalidSnapshotError, match="dataView.name.*2,048"):
        adapt(snapshot, scope_label="Synthetic sandbox")

    with pytest.raises(InvalidSnapshotError, match="scope label.*512"):
        adapt(_snapshot(), scope_label="x" * 513)


def test_existing_structure_depth_and_node_limits_are_applied() -> None:
    too_deep = _snapshot()
    too_deep["ignored"] = _nested(MAX_STRUCTURE_DEPTH)
    with pytest.raises(InvalidSnapshotError, match="maximum structure depth"):
        adapt(too_deep, scope_label="Synthetic sandbox")

    too_many = {"dataViews": [], "count": 0, "ignored": [0] * MAX_STRUCTURE_NODES}
    with pytest.raises(InvalidSnapshotError, match="250,000 nodes"):
        adapt(too_many, scope_label="Synthetic sandbox")


def test_reordered_equivalent_records_keep_entity_and_edge_order_deterministic() -> None:
    first = _load("cja_lineage_shared.json")
    second = copy.deepcopy(first)
    second["dataViews"].reverse()
    for record in second["dataViews"]:
        record["datasets"].reverse()

    topology_a = adapt(first, scope_label="Synthetic sandbox")
    topology_b = adapt(second, scope_label="Synthetic sandbox")

    assert [item.id for item in topology_a.datasets] == [item.id for item in topology_b.datasets]
    assert [item.id for item in topology_a.connections] == [
        item.id for item in topology_b.connections
    ]
    assert [item.id for item in topology_a.data_views] == [
        item.id for item in topology_b.data_views
    ]
    assert [(edge.dataset_id, edge.connection_id) for edge in topology_a.dataset_connections] == [
        (edge.dataset_id, edge.connection_id) for edge in topology_b.dataset_connections
    ]
    assert [
        (edge.connection_id, edge.data_view_id) for edge in topology_a.connection_data_views
    ] == [(edge.connection_id, edge.data_view_id) for edge in topology_b.connection_data_views]


@pytest.mark.parametrize(
    "change",
    [
        {"connection": []},
        {"connection": {"id": "c"}},
        {"connection": {"id": None, "name": None}, "datasets": {}},
        {"connection": {"id": "c", "name": None}, "datasets": {}},
        {"datasets": [None]},
        {"name": 4},
        {"name": ""},
        {"name": " padded "},
        {"connection": {"id": 4, "name": "C"}},
        {"connection": {"id": " padded ", "name": "C"}},
        {"connection": {"id": "c", "name": 4}},
        {"connection": {"id": "c", "name": " padded "}},
        {"name": "x" * 5000},
    ],
)
def test_malformed_discovery_records_are_rejected(change):
    record = _record()
    record.update(change)
    with pytest.raises(InvalidSnapshotError):
        adapt(_snapshot(record), scope_label="Synthetic")


def test_missing_parent_without_datasets_and_sentinel_name_degrade():
    record = _record(connection_id=None, connection_name=None)
    record.pop("datasets")
    assert adapt(_snapshot(record), scope_label="Scope").datasets == ()
    record = _record(connection_name="N/A")
    assert (
        adapt(_snapshot(record), scope_label="Scope").connections[0].detail_availability
        == Availability.UNAVAILABLE
    )


def test_conflicting_relationship_claims_are_rejected():
    first = _record(datasets=[{"id": "d", "name": "D"}])
    for second in [_record(data_view_id="dv-2"), _record(connection_id="other")]:
        with pytest.raises(InvalidSnapshotError):
            adapt(_snapshot(first, second), scope_label="Scope")


@pytest.mark.parametrize(
    "lookup", [{}, {"parentFields": "bad"}, {"parentFields": [4]}, {"parentFields": ["x" * 5000]}]
)
def test_invalid_optional_lookup_fields_do_not_drop_relationships(lookup):
    record = _record(datasets=[{"id": "d", "name": "D", "connectionMetadata": {"lookup": lookup}}])
    topology = adapt(_snapshot(record), scope_label="Scope")
    assert len(topology.dataset_connections) == 1
    assert topology.dataset_connections[0].connection_metadata.lookup.value.parent_fields is None


def test_conflicting_schema_null_and_object_become_unknown():
    first = _record(datasets=[{"id": "d", "name": "D", "connectionMetadata": {"schema": None}}])
    second = copy.deepcopy(first)
    second["datasets"][0]["connectionMetadata"]["schema"] = {"id": "s"}
    topology = adapt(_snapshot(first, second), scope_label="Scope")
    assert topology.dataset_connections[0].connection_metadata.schema is None
