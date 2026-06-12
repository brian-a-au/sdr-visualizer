# Performance

Per [`SPEC-VISUALIZER.md`](../SPEC-VISUALIZER.md) §6 the visualizer must hit these targets:

| Implementation size | Build time | HTML output size | Initial render time | Filter/search latency |
|---------------------|------------|------------------|---------------------|----------------------|
| 100 components      | < 1 s      | < 500 KB         | < 200 ms            | < 50 ms              |
| 500 components      | < 3 s      | < 2 MB           | < 500 ms            | < 100 ms             |
| 1,000 components    | < 6 s      | < 4 MB           | < 1 s               | < 150 ms             |
| 2,000 components    | < 12 s     | < 8 MB           | < 2 s               | < 300 ms             |

Above 2,000 components the visualizer still produces valid output but uses simpler rendering strategies (the graph view, in particular, defaults to a "render anyway" placeholder above 1,000 nodes — configurable via `--max-graph-nodes`).

## How the budgets are enforced

Two CI gates cover all four §6 columns:

- **`scripts/perf_check.py`** — build time + HTML size. Runs the bundled CJA (1,200 components) and AA (~900) fixtures against the 1,000-component budgets, plus a generated ~2,000-component XL fixture (`generate_large_fixture.py --scale 1.67`) against the 2,000-component budgets.
- **`scripts/perf_browser_check.py`** — initial render time + filter/search latency + graph-init main-thread block, measured in headless Chromium via Playwright (`uv sync --group browser`, `uv run playwright install chromium`). Navigates the rendered file, waits for the first catalog row, then drives the embedded `window.__sdrPerf.timeFilter()` hook (which bypasses the input debounce so the budget measures actual work; median of 5 runs). Asserts the 2,000-component budgets (< 2 s render, < 300 ms filter) for both the 1,200 and ~2,000-component fixtures, plus a 700 ms cap on how long entering the graph view may block the main thread — script time plus a forced style/layout flush of the inserted SVG subtree. Both fixtures exceed the 1,000-node threshold, so this times the worst-case "Render anyway" path, and the gate fails if that path ever stops being exercised.

CI runs both after `pytest`; a regression that exceeds any budget fails the build.

## What we measure

```bash
$ uv run python scripts/perf_check.py
[CJA] build time: 0.01s   (budget 6.0s)
[CJA] HTML size : 0.71MB  (budget 4.0MB)
[AA] build time: 0.01s   (budget 6.0s)
[AA] HTML size : 0.61MB  (budget 4.0MB)
[CJA-XL] build time: 0.01s   (budget 12.0s)
[CJA-XL] HTML size : 0.98MB  (budget 8.0MB)
OK: all budgets met
```

The bundled large fixture intentionally over-shoots the 1,000-component budget tier (it carries 1,200 components) so the gate tells you about regressions a few hundred components before the spec's hard limit.

## Where the speed comes from

- **Pre-computation in Python.** Reference edges, per-entry in/out-degree counts, segment trees, formula trees, and `modified_ts` (epoch ms) live in the embedded payload. The client never walks raw definition JSON, recomputes reference counts, or parses dates in sort/filter paths.
- **One-time client indexing, then cheap passes.** At load the client builds the lowercased search blob and sort keys in a single O(n) pass. Row HTML is cached per entry (it's a pure function of the entry). The master list is kept pre-sorted and only re-sorted when the sort key changes, so a keystroke costs one filtered pass over precomputed strings.
- **Bounded DOM.** Search input is debounced (120 ms) and at most 1,000 rows render at once — beyond that a "Showing 1,000 of N · Show all" row appears, keeping innerHTML parse + layout flat regardless of catalog size.
- **Slim payload.** Null/empty fields are omitted and nothing ships twice — no server-built search index, no duplicate graph node list or degree maps (~40% smaller than 0.1.0), so `JSON.parse` at load stays fast.
- **Graph tuned for 1,000 nodes, bounded beyond.** The force simulation is warm-started synchronously (60–120 ticks) so the first paint is near-settled — but the warm-up is time-boxed at 150 ms, so entering the graph view never freezes the page regardless of node count (a fixed tick count blocked ~2 s at 5,000 nodes); large graphs finish settling asynchronously, one tick per frame. Above 1,000 nodes (the opt-in "Render anyway" zone) the simulation also uses a coarser Barnes-Hut theta and faster alpha decay — ~30% cheaper ticks, earlier settling. Graphs over 200 nodes label only the top-60 in-degree nodes until you zoom past 1.4× (or hover). D3 only for the simulation; init is lazy on first view switch.
- **One paint pass per frame.** Hover and filter changes don't repaint synchronously: filter state (visibility, query matches against a per-node lowercased blob built once at init) is recomputed only when a filter input changes, painting applies every node/link class in a single pass over each selection (link endpoints are resolved node objects, so visibility reads straight off them), and paints are coalesced through `requestAnimationFrame` — sweeping the pointer across a dense graph costs at most one pass per frame instead of one per mouseover/mouseout. The graph search box is debounced (120 ms) like the catalog's.
