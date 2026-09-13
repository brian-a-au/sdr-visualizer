"""Offline synthetic evidence for resource gates; never queries an SDK or API."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from sdr_visualizer.core.workspace_usage import (
    MAX_INPUT_BYTES,
    bind_workspace_usage,
    component_inventory,
    snapshot_digest,
)
from sdr_visualizer.input.workspace_usage import load_workspace_usage


def usage_json(implementation, *, project_count=10_000, component_count=1, pad_input=False):
    """Return complete synthetic evidence, optionally at the accepted file-byte cap."""
    components = component_inventory(implementation)[:component_count]
    assert len(components) == component_count
    platform = implementation.platform
    target = {
        "platform": platform,
        "ims_org_id": "synthetic-org",
        "snapshot_digest": snapshot_digest(implementation.raw),
        "data_view_id" if platform == "cja" else "rsid": implementation.instance_id,
    }
    if platform == "aa":
        target["global_company_id"] = "synthetic-company"
    projects = [
        {"id": f"p{index:05d}", "name": f"Synthetic project {index:05d}"}
        for index in range(project_count)
    ]
    evidence = {
        "schema_version": 1,
        "target": target,
        "collection": {
            "status": "complete",
            "project_scope": {"kind": "accessible_projects"},
            "permission_visibility": "unknown",
            "limitations": [],
        },
        "requested_components": components,
        "results": [
            {
                "component": component,
                "status": "complete",
                "checked_at": "2026-09-12T12:00:00Z",
                "match_basis": "exact_component_id",
                "projects": projects,
                "limitations": [],
            }
            for component in components
        ],
    }
    encoded = json.dumps(evidence, separators=(",", ":")).encode("utf-8")
    if pad_input:
        assert len(encoded) <= MAX_INPUT_BYTES
        encoded += b" " * (MAX_INPUT_BYTES - len(encoded))
    return encoded


def attach_usage(implementation, encoded):
    """Exercise real file decoding and binding, including their validation costs."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "synthetic.workspace-usage.json"
        path.write_bytes(encoded)
        evidence = load_workspace_usage(path)
    implementation.supplementary_data["workspace_usage"] = bind_workspace_usage(
        evidence,
        implementation,
        organization_context="synthetic-org",
        company_context="synthetic-company" if implementation.platform == "aa" else None,
    )
