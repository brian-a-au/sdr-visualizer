"""Optional evidence projection and output budgets, independent of graph analysis."""

from __future__ import annotations

import json

from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.workspace_usage import (
    MAX_PAYLOAD_BYTES,
    BoundWorkspaceUsage,
    bind_workspace_usage,
)


def project_usage(implementation, generated_at):
    bound = implementation.supplementary_data["workspace_usage"]
    if not isinstance(bound, BoundWorkspaceUsage):
        raise InvalidSnapshotError("Workspace usage reserved data must be validated evidence")
    evidence = bound.evidence
    target = evidence["target"]
    # An Implementation is mutable: recheck its current identity before projecting.
    current = bind_workspace_usage(
        evidence,
        implementation,
        organization_context=target["ims_org_id"],
        company_context=target.get("global_company_id"),
    )
    return current.project(generated_at)


def check_artifact_size(payload, text, *, kind):
    """Apply optional-usage limits without changing legacy report acceptance."""
    if "workspace_usage" not in payload:
        return
    usage_size = len(json.dumps(payload["workspace_usage"], ensure_ascii=False).encode("utf-8"))
    if usage_size > MAX_PAYLOAD_BYTES:
        _oversize("normalized usage", usage_size, MAX_PAYLOAD_BYTES)
    limit = 16_000_000
    exclusive = False
    if kind == "html":
        count = payload["meta"]["component_count"]
        if count <= 2000 and len(payload["graph"]["edges"]) <= 8000:
            limit = next(
                cap
                for size, cap in (
                    (100, 500_000),
                    (500, 2_000_000),
                    (1000, 4_000_000),
                    (2000, 8_000_000),
                )
                if count <= size
            )
            if "changes" in payload or "trend" in payload:
                limit += 500_000
            exclusive = True
    size = len(text.encode("utf-8"))
    if size > limit or (exclusive and size == limit):
        _oversize(kind, size, limit)


def _oversize(kind, size, limit):
    raise InvalidSnapshotError(
        f"Workspace usage {kind} is {size:,} bytes; limit {limit:,}. "
        "Choose a narrower component/project scope or omit optional usage."
    )
