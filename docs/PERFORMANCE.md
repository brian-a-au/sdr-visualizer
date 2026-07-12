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

- **`scripts/perf_check.py`** — build time + HTML size, all four §6 tiers. Generated 100- and 500-component fixtures (`generate_large_fixture.py --scale 0.083` / `--scale 0.417`) run against the small-tier budgets, the bundled CJA (1,200 components) and AA (~900) fixtures against the 1,000-component budgets, and a generated ~2,000-component XL fixture (`--scale 1.67`) against the 2,000-component budgets. Build time is the median of 3 runs. A comparative case builds the large CJA fixture against a deterministically mutated copy (`scripts/mutate_fixture.py`) through the full `--compare-to` path; budget: 1.5x the 1,000-component build budget and the tier size budget + 0.5 MB.
- **`scripts/perf_browser_check.py`** — initial render time + filter/search latency + graph-init main-thread block, measured in headless Chromium via Playwright (`uv sync --group browser`, `uv run playwright install chromium`). Navigates the rendered file, waits for the first catalog row, then drives the embedded `window.__sdrPerf.timeFilter()` hook (which bypasses the input debounce so the budget measures actual work; median of 5 runs). Asserts the 1,000-component budgets (< 1 s render, < 150 ms filter) on the bundled CJA (1,200-component) and AA (~900) fixtures, and the 2,000-component budgets (< 2 s, < 300 ms) on the XL fixture, plus a 700 ms cap on how long entering the graph view may block the main thread — script time plus a forced style/layout flush of the inserted SVG subtree. The CJA fixtures exceed the 1,000-node threshold, so their graph timing takes the worst-case "Render anyway" path (the gate fails if that stops holding); the AA fixture sits under the threshold and must render without the gate. The comparative report is also rendered once, asserting the 1,000-component initial-render budget with the Changes view populated (it renders at load, so its cost is inside that number).

CI runs `perf_check.py` after `pytest` in the test job; the browser gate runs in the separate `browser-perf` job after the browser functional tests. A regression that exceeds any budget fails the build.

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
- **Graph tuned for 1,000 nodes, bounded beyond.** The force simulation is warm-started synchronously until near-settled (an alpha threshold) or a 150 ms budget elapses, so the warm-up — previously a fixed tick count that blocked ~2 s at 5,000 nodes — no longer scales the view-switch freeze with node count. Graphs that can't settle in budget (large graphs anywhere, or smaller ones on slow hardware) finish asynchronously, one tick per frame. The remaining view-switch cost that does scale linearly (building the SVG DOM) is what the CI gate's 700 ms block budget watches. Above 1,000 nodes — or a lower `--max-graph-nodes` opt-in threshold — the simulation also uses a coarser Barnes-Hut theta and faster alpha decay: ~30% cheaper ticks, earlier settling. Graphs over 200 nodes label only the top-60 in-degree nodes until you zoom past 1.4× (or hover). D3 only for the simulation; init is lazy on first view switch.
- **One paint pass per frame.** Hover and filter changes don't repaint synchronously: filter state (visibility, query matches against a per-node lowercased blob built once at init) is recomputed only when a filter input changes, painting applies every node/link class in a single pass over each selection (link endpoints are resolved node objects, so visibility reads straight off them), and paints are coalesced through `requestAnimationFrame` — sweeping the pointer across a dense graph costs at most one pass per frame instead of one per mouseover/mouseout. The graph search box is debounced (120 ms) like the catalog's.
