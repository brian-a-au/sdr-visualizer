"""Regenerate examples/cja-typical.html and aa-typical.html.

Reads the bundled fixtures (the messy CJA fixture and the AA messy fixture)
and writes them through the renderer. Run via:

    uv run python scripts/generate_examples.py
"""

from __future__ import annotations

import json
from pathlib import Path

from sdr_visualizer.core.visualizer import build_implementation
from sdr_visualizer.render.renderer import render

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"
OUT = REPO / "examples"


def _generate(fixture: str, output_name: str) -> Path:
    snapshot = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    impl = build_implementation(snapshot, source=str(FIXTURES / fixture))
    html = render(impl)
    target = OUT / output_name
    target.write_text(html, encoding="utf-8")
    return target


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for fixture, output in [
        ("cja_snapshot_messy.json", "cja-typical.html"),
        ("aa_snapshot_messy.json", "aa-typical.html"),
    ]:
        target = _generate(fixture, output)
        print(f"wrote {target}")


if __name__ == "__main__":
    main()
