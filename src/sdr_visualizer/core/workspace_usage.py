"""Versioned, strictly bound Workspace evidence; independent of catalog references."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.models import Implementation

MAX_INPUT_BYTES = 2_097_152
MAX_PAYLOAD_BYTES = 1_048_576
DIGEST_ALGORITHM = "sdr-python-json-sha256-v1"
NO_RESULTS_LIMITATION = "No results were collected"
CLOCK_REVERSAL_LIMITATION = "Collection clock moved backwards; retrieval interval unavailable"


def _object(properties, optional=()):
    return {
        "type": "object",
        "properties": properties,
        "required": [k for k in properties if k not in optional],
        "additionalProperties": False,
    }


def _string(maximum=512, nullable=False, minimum=1, pattern=None):
    result = {
        "type": ["string", "null"] if nullable else "string",
        "minLength": minimum,
        "maxLength": maximum,
    }
    if pattern:
        result["pattern"] = pattern
    return result


def _enum(*values):
    return {"enum": list(values)}


def _array(items, maximum, minimum=0, unique=False):
    return {
        "type": "array",
        "items": items,
        "maxItems": maximum,
        "minItems": minimum,
        "uniqueItems": unique,
    }


ID = _string(pattern=r"^[^\u0000-\u001f\u007f-\u009f]+$")
LIMITATIONS = _array(_string(256), 20)
STATUS = _enum("complete", "partial", "failed")
FAILURE = _enum("permission_denied", "collection_error", "unsupported", "unknown")
COMPONENT = _object(
    {
        "type": _enum("metric", "dimension", "derived_field", "segment", "calculated_metric"),
        "id": ID,
    }
)
SCOPE = {
    "oneOf": [
        _object({"kind": _enum("accessible_projects")}),
        _object({"kind": _enum("explicit_projects"), "project_ids": _array(ID, 10_000, 1, True)}),
    ]
}
DIGEST = _object(
    {"algorithm": _enum(DIGEST_ALGORITHM), "value": _string(64, pattern=r"^[0-9a-f]{64}$")}
)
TARGET = {
    "oneOf": [
        _object(
            {
                "platform": _enum("cja"),
                "ims_org_id": ID,
                "data_view_id": ID,
                "snapshot_digest": DIGEST,
            }
        ),
        _object(
            {
                "platform": _enum("aa"),
                "ims_org_id": ID,
                "global_company_id": ID,
                "rsid": ID,
                "snapshot_digest": DIGEST,
            }
        ),
    ]
}
RETRIEVAL = _object(
    {
        "status": STATUS,
        "started_at": _string(64, True),
        "finished_at": _string(64, True),
        "include_type": _enum("all", "owned", "shared", "explicit"),
        **{
            key: {"type": "integer", "minimum": 0, "maximum": cap}
            for key, cap in [
                ("request_attempts", 256),
                ("pages_fetched", 20),
                ("projects_discovered", 10_000),
                ("projects_fetched", 200),
                ("projects_failed", 200),
            ]
        },
        "limitations": LIMITATIONS,
    }
)
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Workspace project usage v1",
    **_object(
        {
            "schema_version": {"type": "integer", "enum": [1]},
            "target": TARGET,
            "collection": _object(
                {
                    "status": STATUS,
                    "project_scope": SCOPE,
                    "permission_visibility": _enum("limited", "unknown"),
                    "limitations": LIMITATIONS,
                    "failure": FAILURE,
                    "source": _object(
                        {
                            "kind": _enum("sdk_candidates"),
                            "sdk": _enum("cjapy", "aanalytics2"),
                            "version": _string(64, True),
                        }
                    ),
                    "retrieval": RETRIEVAL,
                },
                ("failure", "source", "retrieval"),
            ),
            "requested_components": _array(COMPONENT, 2000, 1, True),
            "results": _array(
                _object(
                    {
                        "component": COMPONENT,
                        "status": STATUS,
                        "checked_at": _string(64, True, 0),
                        "match_basis": _enum("exact_component_id", "unverified_lookup"),
                        "projects": _array(_object({"id": ID, "name": _string(256, True)}), 10_000),
                        "limitations": LIMITATIONS,
                        "failure": FAILURE,
                    },
                    ("failure",),
                ),
                2000,
            ),
        }
    ),
}


def _reject(path, reason):
    raise InvalidSnapshotError(f"Workspace usage {path}: {reason}")


def validate_json_value(value, *, max_depth=20, max_nodes=100_000):
    """Iteratively bound native values before recursive serialization/validation."""
    stack = [(value, 0)]
    nodes = 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            _reject("$", "structure limit exceeded")
        if type(node) is dict:
            for key in node:
                if type(key) is not str:
                    _reject("$", "object keys must be strings")
                _unicode(key)
            stack.extend((child, depth + 1) for child in node.values())
        elif type(node) is list:
            stack.extend((child, depth + 1) for child in node)
        elif type(node) is str:
            _unicode(node)
        elif node is not None and type(node) not in (int, float, bool):
            _reject("$", "not a JSON value")
        elif type(node) is float and not math.isfinite(node):
            _reject("$", "non-finite number")


def _unicode(value):
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        _reject("$", "Unicode surrogate code point")


def _validate(value, schema, path="$"):
    if "oneOf" in schema:
        matches = 0
        for branch in schema["oneOf"]:
            try:
                _validate(value, branch, path)
                matches += 1
            except InvalidSnapshotError:
                pass
        if matches != 1:
            _reject(path, "invalid object variant")
        return
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    actual = {dict: "object", list: "array", str: "string", int: "integer", type(None): "null"}.get(
        type(value)
    )
    if kind and actual not in kinds:
        _reject(path, "invalid value type")
    if "enum" in schema and value not in schema["enum"]:
        _reject(path, "unsupported value")
    if actual == "object":
        if set(value) - schema["properties"].keys() or set(schema["required"]) - value.keys():
            _reject(path, "unknown or missing fields")
        for key, child in value.items():
            _validate(child, schema["properties"][key], f"{path}.{key}")
    elif actual == "array":
        if not schema["minItems"] <= len(value) <= schema["maxItems"]:
            _reject(path, "item count exceeds bounds")
        if schema["uniqueItems"] and len({json.dumps(v, sort_keys=True) for v in value}) != len(
            value
        ):
            _reject(path, "duplicate entries")
        for index, child in enumerate(value):
            _validate(child, schema["items"], f"{path}[{index}]")
    elif actual == "string":
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 512):
            _reject(path, "string length exceeds bounds")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            _reject(path, "invalid string")
    elif actual == "integer" and not schema.get("minimum", value) <= value <= schema.get(
        "maximum", value
    ):
        _reject(path, "count exceeds bounds")


def snapshot_digest(raw: dict[str, Any]) -> dict[str, str]:
    """Fingerprint the original parsed snapshot using Python JSON normalization."""
    validate_json_value(raw, max_depth=100, max_nodes=250_000)
    try:
        serialized = json.dumps(
            raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    except (ValueError, RecursionError, OverflowError) as exc:
        raise InvalidSnapshotError("Workspace usage snapshot cannot be fingerprinted") from exc
    return {"algorithm": DIGEST_ALGORITHM, "value": hashlib.sha256(serialized).hexdigest()}


def _time(value):
    if (
        not value
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value
        )
        is None
    ):
        return None
    if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def _failure(item, path):
    if (item["status"] == "failed" and "failure" not in item) or (
        item["status"] == "complete" and "failure" in item
    ):
        _reject(path, "failure category contradicts status")


def _retrieval(collection):
    r = collection.get("retrieval")
    if r is None:
        return
    explicit = collection["project_scope"]["kind"] == "explicit_projects"
    if (r["include_type"] == "explicit") != explicit:
        _reject("collection.retrieval", "scope mismatch")
    discovered, fetched, failed = (
        r[k] for k in ("projects_discovered", "projects_fetched", "projects_failed")
    )
    if (
        (not explicit and discovered > 1000)
        or (explicit and discovered != len(collection["project_scope"]["project_ids"]))
        or fetched + failed > min(200, discovered)
        or r["pages_fetched"] + fetched + failed > r["request_attempts"]
        or (explicit and r["pages_fetched"] != 0)
    ):
        _reject("collection.retrieval", "inconsistent counters")
    if r["status"] == "complete" and (fetched != discovered or failed or r["limitations"]):
        _reject("collection.retrieval", "incomplete retrieval claimed complete")
    start, end = r["started_at"], r["finished_at"]
    parsed_start, parsed_end = _time(start), _time(end)
    if start is None and end is None:
        if CLOCK_REVERSAL_LIMITATION not in r["limitations"]:
            _reject("collection.retrieval", "missing interval requires clock reversal limitation")
    elif (
        start is None
        or end is None
        or parsed_start is None
        or parsed_end is None
        or parsed_end < parsed_start
    ):
        _reject("collection.retrieval", "invalid retrieval interval")


def component_inventory(implementation: Implementation) -> list[dict[str, str]]:
    """Return full typed catalog identities in stable catalog order, before filtering."""
    return [
        {"type": kind, "id": c.id}
        for kind, components in [
            ("metric", implementation.metrics),
            ("dimension", implementation.dimensions),
            ("derived_field", implementation.derived_fields),
            ("segment", implementation.segments),
            ("calculated_metric", implementation.calculated_metrics),
        ]
        for c in components
    ]


def bind_workspace_usage(
    value: dict[str, Any],
    implementation: Implementation,
    *,
    organization_context: str,
    company_context: str | None = None,
) -> BoundWorkspaceUsage:
    """Validate and bind evidence atomically against the complete catalog inventory."""
    validate_json_value(value)
    _validate(value, SCHEMA)
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_INPUT_BYTES:
        _reject("$", "input byte limit exceeded")
    data = copy.deepcopy(value)
    target, collection = data["target"], data["collection"]
    platform = implementation.platform
    if (
        target["platform"] != platform
        or not organization_context
        or target["ims_org_id"] != organization_context
    ):
        _reject("target", "platform or organization mismatch")
    if platform == "aa":
        if not company_context or company_context != target["global_company_id"]:
            _reject("target.global_company_id", "company mismatch")
    elif company_context is not None:
        _reject("target", "company context forbidden for CJA")
    if (
        not implementation.instance_id
        or target["data_view_id" if platform == "cja" else "rsid"] != implementation.instance_id
    ):
        _reject("target", "instance mismatch")
    if target["snapshot_digest"] != snapshot_digest(implementation.raw):
        _reject("target.snapshot_digest", "snapshot mismatch")
    inventory = [(c["type"], c["id"]) for c in component_inventory(implementation)]
    counts = Counter(identity for _, identity in inventory)
    requested = [(c["type"], c["id"]) for c in data["requested_components"]]
    for kind, identity in requested:
        if (
            (kind, identity) not in inventory
            or counts[identity] != 1
            or (platform == "aa" and kind == "derived_field")
        ):
            _reject("requested_components", "unknown or ambiguous exact component identity")
    _failure(collection, "collection")
    _retrieval(collection)
    source = collection.get("source")
    if source and source["sdk"] != ("cjapy" if platform == "cja" else "aanalytics2"):
        _reject("collection.source", "SDK platform mismatch")
    seen, names, occurrences = set(), {}, 0
    for record in data["results"]:
        key = (record["component"]["type"], record["component"]["id"])
        if key not in requested or key in seen:
            _reject("results", "unrequested or duplicate component")
        seen.add(key)
        _failure(record, "results")
        if source and record["match_basis"] != "unverified_lookup":
            _reject("results.match_basis", "SDK candidates must remain unverified")
        if record["status"] == "partial" and not (
            record["limitations"] or collection["limitations"]
        ):
            _reject("results.limitations", "partial result requires limitation")
        if (
            collection["status"] == "complete"
            and record["status"] != "complete"
            or collection["status"] == "failed"
            and record["status"] != "failed"
        ):
            _reject("results.status", "collection status contradiction")
        unique = {}
        for project in record["projects"]:
            occurrences += 1
            identity, name = project["id"], project["name"]
            if identity in names and names[identity] != name:
                _reject("results.projects", "conflicting project names")
            names[identity] = name
            if (
                collection["project_scope"]["kind"] == "explicit_projects"
                and identity not in collection["project_scope"]["project_ids"]
            ):
                _reject("results.projects", "project outside declared scope")
            unique[identity] = project
        record["projects"] = [unique[k] for k in sorted(unique)]
    if occurrences > 10_000 or len(names) > 10_000:
        _reject("results.projects", "project occurrence limit exceeded")
    if collection["status"] == "complete" and len(seen) != len(requested):
        _reject("collection", "complete collection requires every result")
    if (
        collection["status"] == "partial"
        and not seen
        and NO_RESULTS_LIMITATION not in collection["limitations"]
    ):
        _reject("collection.limitations", "no results collected requires explicit limitation")
    return BoundWorkspaceUsage(json.dumps(data, ensure_ascii=False), tuple(inventory))


@dataclass(frozen=True)
class BoundWorkspaceUsage:
    """Validated evidence retained as immutable JSON; projections cannot mutate it."""

    _json: str
    _inventory: tuple[tuple[str, str], ...]

    @property
    def evidence(self):
        return json.loads(self._json)

    def project(self, generated_at: str) -> dict[str, Any]:
        generated = _time(generated_at)
        if generated is None:
            _reject("generated_at", "aware report timestamp required")
        data = self.evidence
        collection = data["collection"]
        retrieval = collection.get("retrieval")
        collection_limitations = list(collection["limitations"])
        if retrieval is not None:
            collection_limitations.extend(retrieval["limitations"])
        requested = {(c["type"], c["id"]) for c in data["requested_components"]}
        records, indices = {}, {}
        for index, record in enumerate(data["results"]):
            key = (record["component"]["type"], record["component"]["id"])
            records[key], indices[key] = record, index
        components = []
        for kind, identity in self._inventory:
            key = (kind, identity)
            r = records.get(key)
            row = {
                "component": {"type": kind, "id": identity},
                "state": "not_checked",
                "reason": "component_not_included",
                "time_quality": "missing",
                "checked_at_utc": None,
                "age_at_generation": None,
                "limitations": list(collection_limitations),
            }
            if r is None:
                if key in requested:
                    row["state"] = "failed" if collection["status"] == "failed" else "not_checked"
                    row["reason"] = (
                        "collection_failed" if row["state"] == "failed" else "no_result_collected"
                    )
                    if "failure" in collection:
                        row["failure"] = collection["failure"]
            else:
                checked = _time(r["checked_at"])
                quality = (
                    ("missing" if not r["checked_at"] else "invalid")
                    if checked is None
                    else ("future" if checked > generated else "valid")
                )
                row.update(
                    time_quality=quality,
                    result_index=indices[key],
                    match_basis=r["match_basis"],
                    status=r["status"],
                    checked_at=r["checked_at"],
                    project_count=len(r["projects"]),
                )
                row["limitations"].extend(r["limitations"])
                if "failure" in r or "failure" in collection:
                    row["failure"] = r.get("failure", collection.get("failure"))
                if checked:
                    row["checked_at_utc"] = checked.isoformat().replace("+00:00", "Z")
                if quality == "valid":
                    row["age_at_generation"] = (
                        "older_than_24h"
                        if (generated - checked).total_seconds() > 86400
                        else "within_24h"
                    )
                complete = (
                    collection["status"] == r["status"] == "complete"
                    and (retrieval is None or retrieval["status"] == "complete")
                    and not row["limitations"]
                )
                exact = r["match_basis"] == "exact_component_id"
                if r["status"] == "failed" and not r["projects"]:
                    state = "failed"
                elif r["projects"]:
                    state = "references_found" if exact and complete else "partial"
                else:
                    state = (
                        "no_references_found"
                        if complete and exact and quality == "valid"
                        else "partial"
                    )
                row.update(state=state, reason="attempted_result")
            components.append(row)
        summary = {
            status: sum(r["status"] == status for r in records.values())
            for status in ("complete", "partial", "failed")
        }
        summary.update(attempted=len(records), requested=len(requested))
        payload = {
            "schema_version": 1,
            "evidence": data,
            "generated_at": generated_at,
            "binding": {
                "organization_context": "operator_asserted",
                "snapshot": "matched",
                **(
                    {"company_context": "operator_asserted"}
                    if data["target"]["platform"] == "aa"
                    else {}
                ),
            },
            "summary": summary,
            "display": components,
        }
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_PAYLOAD_BYTES:
            _reject("$", "normalized payload byte limit exceeded; choose a narrower scope")
        return payload
