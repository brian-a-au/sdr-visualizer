"""Top-level orchestrator: input -> adapter -> render -> HTML.

Used by the CLI and by `scripts/generate_examples.py` so they go through a
single code path. Pure function: same inputs -> same output (the only
nondeterminism is `meta.generated_at`, which renderer callers can post-
process out for golden tests if needed).
"""

from __future__ import annotations

from typing import Any

from sdr_visualizer.adapters.aa import adapt as aa_adapt
from sdr_visualizer.adapters.cja import adapt as cja_adapt
from sdr_visualizer.core.exceptions import InvalidSnapshotError
from sdr_visualizer.core.models import Implementation
from sdr_visualizer.input.detect import detect_platform
from sdr_visualizer.render.renderer import render


def visualize(
    snapshot: dict[str, Any],
    *,
    source: str = "<unknown>",
    platform: str | None = None,
    title: str | None = None,
) -> str:
    """Adapt a parsed snapshot and return the rendered HTML string."""
    impl = build_implementation(snapshot, source=source, platform=platform)
    return render(impl, title=title)


def build_implementation(
    snapshot: dict[str, Any],
    *,
    source: str = "<unknown>",
    platform: str | None = None,
) -> Implementation:
    if platform is None:
        platform = detect_platform(snapshot)
    if platform == "cja":
        return cja_adapt(snapshot, source=source)
    if platform == "aa":
        return aa_adapt(snapshot, source=source)
    raise InvalidSnapshotError(f"unknown platform {platform!r}; expected 'cja' or 'aa'")
