# Architecture

`sdr-visualizer` follows a one-way data flow:

```
snapshot JSON
      ↓  input/loader.py  (Mode 1: file, Mode 2: dir, Mode 3: shell-out, Mode 4: stdin)
parsed dict + source label
      ↓  input/detect.py  (auto-detect platform from top-level shape)
platform = "cja" | "aa"
      ↓  adapters/cja.py | adapters/aa.py
core/models.py::Implementation       ← the contract that downstream layers consume
      ↓  analysis/{references,segment_tree,formula_tree}.py
analysis structures (graph, segment trees, formula trees)
      ↓  render/data_payload.py
embedded JSON payload (denormalized, JSON-serializable)
      ↓  render/renderer.py + Jinja templates
single self-contained HTML
```

No layer reaches across. The renderer never sees an `Implementation`; it only sees the embedded payload. This is enforceable: if you delete the adapters, the renderer still works against fabricated payloads.

## Module map

```
src/sdr_visualizer/
├── cli/                     # argparse entry point + exit codes
├── core/
│   ├── models.py            # Implementation, Component, Segment, CalculatedMetric
│   ├── visualizer.py        # build_implementation orchestrator
│   └── exceptions.py
├── input/
│   ├── loader.py            # Modes 1, 2, 4
│   ├── detect.py            # platform auto-detect
│   └── shell_out.py         # Mode 3
├── adapters/
│   ├── base.py              # protocol
│   ├── cja.py               # cja_auto_sdr JSON → Implementation
│   └── aa.py                # aa_auto_sdr  JSON → Implementation
├── analysis/
│   ├── references.py        # build_reference_graph(impl) -> nodes/edges/degrees
│   ├── segment_tree.py      # parse_segment_tree(seg) -> renderable tree
│   └── formula_tree.py      # parse_formula_tree(cm)  -> renderable tree
└── render/
    ├── data_payload.py      # build_payload(impl) -> dict (the embedded JSON)
    ├── renderer.py          # render(impl) -> str (HTML)
    ├── templates/
    │   ├── index.html.j2
    │   ├── catalog.html.j2
    │   └── graph.html.j2
    └── static/
        ├── visualizer.css   # all styling, inlined into output
        ├── visualizer.js    # all client-side logic, inlined into output
        └── d3.min.js        # vendored D3 v7 for the graph view, inlined into output
```

## Design principles

1. **Static output, dynamic interaction.** Python builds one HTML file with embedded JSON, embedded CSS, embedded JS. The client just reads, filters, and renders — no fetches, no API.

2. **Server-side build, client-side render.** Do work in Python (where seconds are fine). Pre-compute reference counts, pre-flatten segment definitions, pre-build the lowercased catalog index. The client must finish in milliseconds.

3. **Vanilla JS, no framework.** D3 only for the force simulation. Otherwise plain DOM with event delegation.

4. **Performance is enforced, not aspirational.** The budgets in [`PERFORMANCE.md`](PERFORMANCE.md) are gated by CI via `scripts/perf_check.py`. An implementation that takes 5 seconds to render 500 components is broken regardless of how it looks.

5. **Descriptive, not evaluative.** No grades, no findings, no opinions. The visualizer renders what exists; it doesn't propose changes. Anything evaluative belongs in [`sdr-grader`](https://github.com/brian-a-au/sdr-grader).

## Vendoring relationship with sdr-grader

The normalized model (`core/models.py`), the adapters, and the input layer are vendored from `sdr-grader` per [`SPEC-VISUALIZER.md`](../SPEC-VISUALIZER.md) §11 — not shared as a Python package. The duplication is intentional: a solo open-source maintainer benefits more from each project standing alone than from architectural elegance, and the duplicated surface (~1,000 lines) changes infrequently. Files diverge over time only when the divergence is deliberate (the visualizer has expanded `analysis/`; the grader has `rules/`, `core/grader.py`, `trend/`).

If a third tool joins the family, factor a shared `sdr-core` package then.

## Adding a new view

1. Add a partial under `render/templates/` for the view's scaffold.
2. `{% include %}` it from `render/templates/index.html.j2`.
3. Add a `<button class="view-button" data-view="..."` to the nav.
4. Extend `render/static/visualizer.js`'s `showView()` to toggle the new section's `hidden`, and add an init function that runs lazily on first switch.
5. Append CSS for the view to `render/static/visualizer.css`.
6. Add structural assertions in `tests/test_renderer.py` (e.g. the section id is present, the data the view consumes is in the payload).

The data the view needs should already be in `data_payload.build_payload`'s output. If not, that's the place to denormalize it — keep client-side work to a minimum.
