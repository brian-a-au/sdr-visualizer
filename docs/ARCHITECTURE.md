# Architecture

`sdr-visualizer` follows a one-way, static-output data flow:

```text
file / directory / stdin / live generator
      ↓  input/{loader,series,shell_out}.py
parsed snapshot(s) + source labels
      ↓  input/detect.py + adapters/{cja,aa}.py
core/models.py::Implementation
      ↓  analysis/{references,segment_tree,formula_tree,diff,trend}.py
denormalized analysis structures
      ↓  render/data_payload.py + render/trend_charts.py
schema-valid JSON payload + precomputed SVG chart paths
      ↓  render/renderer.py + Jinja templates + embedded static assets
one self-contained HTML report
```

The CLI orchestrates the optional branches:

- ordinary input adapts one snapshot;
- `--compare-to` adapts a baseline and passes both implementations through
  `analysis/diff.py`; and
- `--trend` uses `input/series.py` to select up to 60 usable snapshots before
  `analysis/trend.py` builds aggregates and interval changes.

No browser view reads a snapshot or Python model directly. The renderer accepts
the denormalized payload, and the browser reads only the embedded JSON. This
boundary is enforced by renderer and payload tests.

## Module map

```text
src/sdr_visualizer/
├── cli/
│   ├── main.py               # arguments, mode orchestration, safe output, exits
│   └── exit_codes.py         # public 0 / 1 / 3 contract
├── core/
│   ├── models.py             # normalized Implementation and component models
│   ├── visualizer.py         # detect/adapt and ordinary visualization entry points
│   ├── structure_limits.py   # iterative hostile-input depth/node budgets
│   └── exceptions.py
├── input/
│   ├── loader.py             # file, directory, stdin, and cutoff selection
│   ├── series.py             # usable-snapshot trend selection and 60-window cap
│   ├── detect.py             # CJA/AA top-level shape detection
│   └── shell_out.py          # live cja_auto_sdr / aa_auto_sdr execution
├── adapters/
│   ├── base.py               # adapter protocol
│   ├── cja.py                # CJA snapshot → Implementation
│   └── aa.py                 # AA snapshot → Implementation
├── analysis/
│   ├── references.py         # graph edges and in/out degrees
│   ├── segment_tree.py       # bounded segment anatomy tree
│   ├── formula_tree.py       # bounded calculated-metric formula tree
│   ├── diff.py               # typed, field-level snapshot comparison
│   └── trend.py              # aggregate series and interval changes
└── render/
    ├── data_payload.py       # sparse public payload
    ├── trend_charts.py       # precomputed trend SVG geometry
    ├── color_packs.py        # immutable semantic HTML color registry
    ├── renderer.py           # JSON guard, templates, and self-contained HTML
    ├── templates/
    │   ├── index.html.j2
    │   ├── catalog.html.j2
    │   ├── graph.html.j2
    │   ├── changes.html.j2
    │   └── trend.html.j2
    └── static/
        ├── visualizer.css
        ├── visualizer.js     # bounded, lazy browser views and URL state
        └── d3.min.js         # vendored D3 v7, used only by the graph
```

## Design principles

1. **Static output, dynamic interaction.** Python builds one HTML file with
   embedded JSON, CSS, and JavaScript. The report makes no fetches and needs no
   application server.

2. **Precompute analysis, bound presentation.** Python computes graph degrees,
   anatomy trees, comparison fields, trend aggregates, and chart geometry.
   Browser views filter complete data but materialize bounded DOM batches.

3. **Vanilla JavaScript, with D3 only for the graph.** There is no frontend
   framework or client build pipeline.

4. **Performance is a contract.** Both Python build/output budgets and
   browser-measured render/filter/graph budgets are gated as documented in
   [`PERFORMANCE.md`](PERFORMANCE.md).

5. **Descriptions, not judgments.** The visualizer renders what exists. Grades,
   findings, and recommendations belong in
   [`sdr-grader`](https://github.com/brian-a-au/sdr-grader).

6. **Snapshots are untrusted.** Public adaptation and direct tree-analysis
   boundaries enforce the limits in
   [`PRODUCT_CONTRACT.md`](PRODUCT_CONTRACT.md#integrity-and-resource-bounds).
   Payload JSON rejects non-finite numbers, filenames are sanitized, and
   terminal control bytes are rendered visibly.

7. **Color is presentation-only.** `render/color_packs.py` resolves one
   immutable pack per render and serializes semantic CSS roles. Selection does
   not enter the embedded payload, so HTML and JSON contracts stay separated.
   Labels and other non-color cues remain authoritative.

## Vendoring relationship with sdr-grader

The normalized model, adapters, and parts of the input layer originated in
`sdr-grader` rather than a shared Python package. The duplication lets each
small tool install and evolve independently. Shared defensive behavior must be
evaluated and mirrored in the same release cycle, while intentional
visualizer-only differences stay documented and tested in
[`ADAPTER_GUIDE.md`](ADAPTER_GUIDE.md#vendoring-parity-with-sdr-grader).

`render/color_packs.py` is also a shared runtime path. Its
`color_pack_contract_snapshot()` exposes only the ordered catalog, ordered
source swatches for every catalog entry, and ordered required-role names. It
deliberately excludes derived role values so each project can render its own
presentation while sharing the source contract. Release qualification loads
both registry blobs from explicit visualizer and grader commit SHAs with no
package dependency or working-tree read, then compares those fields using
`scripts/check_color_pack_parity.py`.

If a third tool creates sustained demand for the same layer, reconsider a
shared package then; do not introduce one merely to eliminate modest,
deliberately reviewed duplication.

## Adding a new view

1. Add a partial under `render/templates/` for the view scaffold.
2. Include it from `render/templates/index.html.j2`.
3. Add the view button and URL-state behavior in `render/static/visualizer.js`.
4. Initialize expensive work only on first entry and define an objective DOM
   bound before adding data-dependent markup.
5. Add styling to `render/static/visualizer.css`.
6. Put any new denormalization in `render/data_payload.py` or a focused render
   helper rather than re-analyzing raw definitions in JavaScript.
7. Add payload/schema, renderer, browser-functional, and browser-performance
   coverage proportional to the new path.

## Adding or changing an input platform

Follow [`ADAPTER_GUIDE.md`](ADAPTER_GUIDE.md#adding-a-new-platform), preserve
the stable surfaces in [`PRODUCT_CONTRACT.md`](PRODUCT_CONTRACT.md), and
complete the current-generator and sibling-parity evidence in
[`RELEASING.md`](RELEASING.md) before changing public compatibility claims.
