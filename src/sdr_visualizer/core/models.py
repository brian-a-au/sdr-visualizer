"""Normalized internal model.

The contract every adapter produces. Downstream layers (analysis, render,
data payload) write generic logic against this model.

See SPEC-VISUALIZER §8. The shapes here are load-bearing and intentionally
identical to sdr-grader's: adding fields is fine, renaming or removing them
breaks the data contract shared with the sibling project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Platform = Literal["cja", "aa"]
ComponentType = Literal["metric", "dimension", "derived_field"]
Polarity = Literal["positive", "negative", "neutral"]


@dataclass
class Component:
    """Generic component: dimension, metric, or derived field."""

    id: str
    name: str
    description: str | None
    component_type: ComponentType
    data_type: str | None
    polarity: Polarity | None
    created_at: str | None
    modified_at: str | None
    owner: str | None
    tags: list[str] = field(default_factory=list)
    platform_specific: dict[str, Any] = field(default_factory=dict)


@dataclass
class Segment:
    id: str
    name: str
    description: str | None
    definition: dict[str, Any]
    nesting_depth: int
    container_types: list[str]
    references: list[str] = field(default_factory=list)
    created_at: str | None = None
    modified_at: str | None = None
    owner: str | None = None


@dataclass
class CalculatedMetric:
    id: str
    name: str
    description: str | None
    formula: dict[str, Any]
    formula_text: str
    attribution_model: str | None
    allocation: str | None
    complexity_score: float
    references: list[str] = field(default_factory=list)
    created_at: str | None = None
    modified_at: str | None = None
    owner: str | None = None


@dataclass
class Implementation:
    """Top-level container for an implementation snapshot."""

    platform: Platform
    instance_id: str
    instance_name: str
    snapshot_taken_at: str | None
    snapshot_source: str
    adapter_version: str
    metrics: list[Component]
    dimensions: list[Component]
    segments: list[Segment]
    calculated_metrics: list[CalculatedMetric]
    derived_fields: list[Component]
    raw: dict[str, Any]
    # Optional supplementary inputs (Launch property exports, Workspace project
    # exports, AEP governance API outputs, etc.) keyed by user-supplied name.
    # Consumers read from this when the appropriate key is present; absent
    # keys are simply skipped.
    supplementary_data: dict[str, Any] = field(default_factory=dict)
