"""Small allowlisted boundary between project definitions and SDK candidates."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.structure_limits import (
    validate_snapshot_structure,
    validate_unicode_scalars,
)

MAX_IPC_BYTES = 16 * 1024 * 1024
SDK_VERSIONS = {"cja": ("cjapy", "0.3.1"), "aa": ("aanalytics2", "0.5.3.post1")}
EXCLUDED_PROJECTS_LIMITATION = "Malformed or unsupported projects were excluded from SDK matching"
CANDIDATE_LIMITATION = (
    "SDK matching is incomplete; exact component and environment match remain unverified"
)


@dataclass
class MatchResult:
    results: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def bounded_json(value: Any, maximum: int = MAX_IPC_BYTES) -> bytes:
    """Check structure/scalars before allocating a bounded encoded representation."""
    validate_snapshot_structure(value, label="Workspace SDK input")
    validate_unicode_scalars(value, label="Workspace SDK input")
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise InvalidSnapshotError("Workspace SDK input requires string keys")
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str):
            if len(item) > 2 * 1024 * 1024:
                raise InvalidSnapshotError("Workspace SDK input string exceeds limit")
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise InvalidSnapshotError("Workspace SDK input contains a non-JSON value")
        elif isinstance(item, float) and not math.isfinite(item):
            raise InvalidSnapshotError("Workspace SDK input contains a nonfinite value")
    output = bytearray()
    for part in json.JSONEncoder(
        ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).iterencode(value):
        encoded = part.encode("ascii")
        if len(output) + len(encoded) > maximum:
            raise InvalidSnapshotError("Workspace SDK JSON exceeds byte limit")
        output.extend(encoded)
    return bytes(output)


def identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 512
        and not any(
            ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in value
        )
    )


def sanitize_projects(platform: str, projects: list[dict]) -> tuple[list[dict], list[str]]:
    if platform not in SDK_VERSIONS or not isinstance(projects, list) or len(projects) > 200:
        raise InvalidSnapshotError("Workspace SDK platform or project count is invalid")
    # Bound even ignored fields before sanitization, without serializing owner metadata.
    validate_snapshot_structure(projects, label="Workspace SDK projects")
    validate_unicode_scalars(projects, label="Workspace SDK projects")
    accepted = {}
    excluded = False
    for project in projects:
        if (
            not isinstance(project, dict)
            or not identifier(project.get("id"))
            or not (
                project.get("name") is None
                or isinstance(project.get("name"), str)
                and 1 <= len(project["name"]) <= 256
            )
            or "name" not in project
            or not isinstance(project.get("definition"), dict)
            or platform == "cja"
            and project.get("type") not in ("project", "guidedAnalysis")
        ):
            excluded = True
            continue
        clean = {
            key: project[key]
            for key in (
                "id",
                "name",
                "definition",
                "modified",
                "externalReferences",
                "rsid",
                "dataId",
            )
            if key in project
        }
        if platform == "cja":
            clean["type"] = project["type"]
        clean["owner"] = {}
        if clean["id"] in accepted and accepted[clean["id"]] != clean:
            raise InvalidSnapshotError("Workspace SDK project identities conflict")
        accepted[clean["id"]] = clean
    result = [accepted[key] for key in sorted(accepted)]
    bounded_json(result)
    return result, [EXCLUDED_PROJECTS_LIMITATION] if excluded else []


def validate_components(platform: str, components: list[dict]) -> list[dict]:
    kinds = {"metric", "dimension", "segment", "calculated_metric"}
    if platform == "cja":
        kinds.add("derived_field")
    if not isinstance(components, list) or not 1 <= len(components) <= 2000:
        raise InvalidSnapshotError("Workspace SDK component count is invalid")
    seen = set()
    for component in components:
        if (
            not isinstance(component, dict)
            or set(component) != {"type", "id"}
            or not isinstance(component["type"], str)
            or component["type"] not in kinds
            or not identifier(component["id"])
        ):
            raise InvalidSnapshotError("Workspace SDK component identity is invalid")
        key = component["type"], component["id"]
        if key in seen:
            raise InvalidSnapshotError("Workspace SDK component identities repeat")
        seen.add(key)
    return [{"type": kind, "id": identity} for kind, identity in sorted(seen)]


def candidate_record(
    component: dict, checked_at: str | None, projects: list[dict], failure: str | None = None
) -> dict:
    record = {
        "component": component,
        "status": "failed" if failure else "partial",
        "checked_at": checked_at,
        "match_basis": "unverified_lookup",
        "projects": projects,
        "limitations": [CANDIDATE_LIMITATION],
    }
    if failure:
        record["failure"] = failure
    return record


def normalize_findings(raw: Any, component: dict, metadata: dict[str, dict]) -> list[dict]:
    """Pinned helpers return component IDs -> projects -> one-entry name/ID maps."""
    if not isinstance(raw, dict) or set(raw) != {component["id"]}:
        raise ValueError("Invalid SDK result")
    value = raw[component["id"]]
    if not isinstance(value, dict) or not isinstance(value.get("projects"), list):
        raise ValueError("Invalid SDK projects")
    if len(value["projects"]) > 10_000:
        raise ValueError("Too many SDK project occurrences")
    found = {}
    for entry in value["projects"]:
        if not isinstance(entry, dict) or len(entry) != 1:
            raise ValueError("Invalid SDK project")
        name, project_id = next(iter(entry.items()))
        if not identifier(project_id) or project_id not in metadata:
            raise ValueError("Unknown SDK project")
        if name != metadata[project_id]["name"]:
            raise ValueError("Conflicting SDK project name")
        found[project_id] = {"id": project_id, "name": name}
    return [found[key] for key in sorted(found)]
