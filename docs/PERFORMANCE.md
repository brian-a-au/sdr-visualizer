# Performance

This page answers two related questions:

1. How large can an implementation be while `sdr-visualizer` still promises
   responsive output?
2. What does the report do when an implementation grows beyond the comfortable
   range?

The short answer is: reports through 2,000 components and 8,000 reference edges
are inside the published performance envelope. Larger reports are still valid,
but become best-effort and use display safeguards to avoid eagerly building an
unbounded browser DOM.

A **component** is one catalog entry: a metric, dimension, derived field,
segment, or calculated metric. A **reference edge** is one directed relationship
between two components that both exist in the implementation.

## Published performance budgets

These budgets are part of the stable
[`PRODUCT_CONTRACT.md`](PRODUCT_CONTRACT.md#stable-public-surfaces). The
visualizer must hit all four targets for the applicable tier:

| Implementation size | Build time | HTML output size | Initial render time | Filter/search latency |
|---------------------|------------|------------------|---------------------|----------------------|
| 100 components      | < 1 s      | < 500 KB         | < 200 ms            | < 50 ms              |
| 500 components      | < 3 s      | < 2 MB           | < 500 ms            | < 100 ms             |
| 1,000 components    | < 6 s      | < 4 MB           | < 1 s               | < 150 ms             |
| 2,000 components    | < 12 s     | < 8 MB           | < 2 s               | < 300 ms             |

In plain terms:

- **Build time** is how long Python takes to adapt the snapshot, analyze it,
  and generate the self-contained HTML report.
- **HTML output size** is the size of that one report file, including its data,
  CSS, JavaScript, and vendored D3 runtime.
- **Initial render time** is how long a real Chromium browser takes to open the
  file and show the catalog.
- **Filter/search latency** is the delay users feel after changing a catalog
  filter or search query.

The guarantees cover reports with at most 8,000 reference edges. A report above
that edge envelope remains valid, but graph rendering requires explicit opt-in
and the published size and latency budgets do not apply. The release corpus gate
reports an edge-envelope violation so maintainers can compare this boundary with
current production data before publishing.

## How to read the size boundaries

The thresholds describe different levels of support; they are not all hard
input limits.

| Report shape | What is promised | What the user sees |
|---|---|---|
| Up to 1,000 components and 8,000 edges | The applicable performance tier | At the default setting, the graph can initialize automatically. |
| 1,001–2,000 components and up to 8,000 edges | The 2,000-component performance tier | The catalog remains covered; the graph asks for explicit “Render anyway” confirmation by default. |
| More than 2,000 components | Valid output, without published speed or file-size guarantees | Bounded and lazy rendering still protect the initial view; graph rendering remains opt-in by default. |
| 5,000 or more components | Valid but expected to be visibly degraded | The CLI prints a warning; rendering the graph requires a deliberate opt-in unless its node threshold was explicitly raised. |
| More than 8,000 edges at any component count | Valid output, outside the published envelope | The graph asks for explicit confirmation before creating its SVG nodes and edges. |

There is no fixed component count at which an otherwise valid snapshot is
rejected. Hard input rejection is instead based on JSON structure: maximum
depth 100, maximum 250,000 nodes in a snapshot, and maximum 10,000 nodes in each
decoded segment definition, formula, tag value, or reference value. Crossing a
hard structure limit is invalid input, exits with code 3, and produces no report.
See [Integrity and resource bounds](PRODUCT_CONTRACT.md#integrity-and-resource-bounds).

This distinction matters: 1,000 is the default graph opt-in threshold, 2,000 is
the largest published performance tier, and the structural budgets are the hard
accept/reject limits.

## What happens when a view reaches its display limit

Display limits reduce browser work; they do not remove entries from the
embedded payload.

- **Catalog:** search and filters inspect the complete catalog, but only the
  first 1,000 matching rows render initially. A “Show all” action is available;
  choosing it may make a very large table slower.
- **Reference graph:** above 1,000 nodes by default, above a lower configured
  `--max-graph-nodes` value, or above 8,000 edges, the view shows a “Render
  anyway” placeholder. The flag changes the node threshold only; it does not
  remove the edge safeguard. After opt-in, the graph creates SVG for the full
  graph.
- **Large graph layout:** above 1,000 nodes, the force simulation trades some
  layout precision for cheaper ticks and faster settling. Above 200 nodes, only
  the 60 highest-in-degree labels show until the user zooms in or hovers.
- **Changes:** the complete comparison is filtered in memory, but rows appear
  in batches of 250 and no more than 1,000 matching changes render. Users refine
  the search to reach matches outside that display window.
- **Trend:** at most the 60 newest usable snapshots are retained, which yields
  at most 59 interval summaries. Older usable history is omitted with a warning.
  Changed component IDs appear only after an interval is opened, in batches of
  100 per added, removed, or modified group.
- **Anatomy:** the browser creates a segment or calculated-metric anatomy DOM
  when its detail panel opens. Structure validation bounds each decoded
  definition, but anatomy nodes are not separately paginated; an unusually
  large valid definition can still make that one detail panel expensive.

The catalog, Changes, and Trend views continue operating on the complete data
despite their presentation bounds. The graph opt-in is also a pause, not a data
truncation rule.

## What the performance evidence covers

The public budgets are the promise. The automated fixtures are repeatable,
representative evidence for that promise rather than an exhaustive sample of
every possible snapshot.

The fixtures cover ordinary and deeply nested segments, calculated metrics,
sparse graphs, a graph near the 8,000-edge boundary, a high-churn comparison,
and a 60-snapshot trend. Very long text fields or many individually large but
valid anatomy definitions can increase file size and memory use even when the
component count is unchanged. If a valid report inside the published component
and edge envelope misses a budget, that is a performance regression; outside
the envelope, the report is best-effort.

Input loading is not streaming: a snapshot is read and parsed in memory before
adaptation. The structural node limits are therefore not the same thing as a
file-byte or memory limit.

## How the budgets are enforced

Two CI gates cover all four budget columns.

### Python build and output gate

`scripts/perf_check.py` measures build time and HTML size at all four tiers:

- generated 100- and 500-component fixtures exercise the small tiers;
- bundled CJA (1,200 components) and AA (~900 components) fixtures exercise the
  1,000-component budget;
- a generated 2,004-component fixture exercises the 2,000-component budget;
- a deterministic graph case stays just inside the 8,000-edge envelope;
- a comparison runs the large CJA fixture against a mutated baseline, with a
  build budget of 1.5 times the 1,000-component tier and 0.5 MB of additional
  size allowance; and
- a six-snapshot trend allows one second of build time per snapshot and 0.5 MB
  of additional size.

Build time is the median of three runs.

### Browser responsiveness gate

`scripts/perf_browser_check.py` opens generated reports in headless Chromium
through Playwright. It measures initial render time, cold and warm catalog
filtering, and the main-thread pause when the graph initializes.

The browser gate exercises all declared size tiers and enforces a 700 ms graph
initialization cap, including a deterministic graph of roughly 1,000 nodes and
8,000 edges. It also proves that:

- a high-churn comparison creates no Changes rows before the view is opened and
  materializes at most 250 rows per batch; and
- a 60-snapshot high-churn trend creates no interval summaries or changed-ID
  chips eagerly, emits at most 59 summaries when opened, and keeps the first
  expanded interval ID-bounded.

Run the browser gate locally with:

```bash
uv sync --group browser
uv run playwright install chromium
uv run python scripts/perf_browser_check.py
```

CI runs `perf_check.py` after `pytest` in the test job. The browser gate runs in
the separate `browser-perf` job after browser functional tests. A regression
that exceeds any budget fails the build.

## What we measure

One representative Python-side run looks like this:

```text
[CJA] build time: 0.01s   (budget 6.0s)
[CJA] HTML size : 0.71MB  (budget 4.0MB)
[AA] build time: 0.01s   (budget 6.0s)
[AA] HTML size : 0.61MB  (budget 4.0MB)
[CJA-XL] build time: 0.01s   (budget 12.0s)
[CJA-XL] HTML size : 0.98MB  (budget 8.0MB)
OK: all budgets met
```

Exact timings vary by machine; the budgets, rather than the sample numbers, are
the contract. The bundled CJA fixture deliberately carries 1,200 components and
is measured against the 1,000-component budget. That gives CI early warning
before regressions approach the upper 2,000-component tier.

## Where the speed comes from

- **Python prepares browser-ready data.** Reference edges, in/out degree,
  anatomy trees, comparison fields, trend aggregates, and sortable timestamps
  are computed before the HTML is written. The browser does not repeat that
  analysis.
- **The browser indexes once.** At load, it prepares lowercase search text and
  sort keys in one pass. It caches each row's HTML and only sorts again when the
  sort choice changes. Normal search input therefore needs one filtered pass
  over already-prepared strings.
- **The DOM stays bounded.** Catalog rows, Changes rows, Trend intervals, and
  changed-ID chips use caps, lazy initialization, or batches so opening the
  report does not create every possible element at once.
- **The payload avoids duplicates.** Empty fields are omitted, while graph node
  and degree data are derived from catalog entries rather than shipped twice.
  This keeps the embedded JSON smaller and faster to parse.
- **Graph work starts only when requested.** D3 initializes on first entry to
  the graph view. Its synchronous warm-up stops when the layout is nearly
  settled or after 150 ms, then unfinished work continues asynchronously, one
  tick per animation frame.
- **Large graphs spend less on precision.** Above 1,000 nodes, the simulation
  uses a coarser Barnes-Hut approximation and faster alpha decay. Labels are
  also limited until zoom or hover.
- **Painting is coalesced by frame.** Graph hover and filter changes update
  visibility in one pass and schedule painting through `requestAnimationFrame`,
  avoiding a full repaint for every rapid pointer event.

These choices favor a fast catalog-first experience while still making richer
views available on demand.
