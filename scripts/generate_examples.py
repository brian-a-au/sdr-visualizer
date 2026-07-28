"""Regenerate examples/cja-typical.html and aa-typical.html.

Reads the bundled fixtures (the messy CJA fixture and the AA messy fixture)
and writes them through the renderer. Run via:

    uv run python scripts/generate_examples.py
"""

from __future__ import annotations

import json
from pathlib import Path

from sdr_visualizer.core.visualizer import build_implementation
from sdr_visualizer.render.renderer import build_payload_with_options, render_payload

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"
OUT = REPO / "examples"
EXAMPLE_GENERATED_AT = "2026-04-25T09:14:00Z"


def _generate(fixture: str, output_name: str, *, output_dir: Path = OUT) -> Path:
    snapshot = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    impl = build_implementation(snapshot, source=f"tests/fixtures/{fixture}")
    payload = build_payload_with_options(impl)
    payload["meta"]["generated_at"] = EXAMPLE_GENERATED_AT
    html = render_payload(payload)
    output_dir.mkdir(exist_ok=True)
    target = output_dir / output_name
    target.write_text(html, encoding="utf-8")
    return target


def main() -> None:
    for fixture, output in [
        ("cja_snapshot_messy.json", "cja-typical.html"),
        ("aa_snapshot_messy.json", "aa-typical.html"),
    ]:
        target = _generate(fixture, output)
        print(f"wrote {target}")


if __name__ == "__main__":
    main()
