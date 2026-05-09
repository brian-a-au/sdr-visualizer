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

`scripts/perf_check.py` runs the bundled large fixture (`tests/fixtures/cja_snapshot_large.json`, 1,200 components) through `render()` and asserts the build time + HTML size budgets at the 1,000-component class. CI calls it after `pytest`, so a regression that exceeds the budget fails the build.

The budgets that depend on the consumer's browser (initial render time, filter/search latency) aren't gated by Python tests. If you change the catalog or graph render path, eyeball them in a browser using the rendered example and the embedded JSON payload size.

## What we measure

```bash
$ uv run python scripts/perf_check.py
components: 1200
build time: 0.02s   (budget 6.0s)
HTML size : 1.04MB  (budget 4.0MB)
OK: all budgets met
```

The bundled large fixture intentionally over-shoots the 1,000-component budget tier (it carries 1,200 components) so the gate tells you about regressions a few hundred components before the spec's hard limit.

## How the speed comes from

- **Pre-computation in Python.** The reference graph (nodes/edges/in_degree/out_degree), segment trees, formula trees, and a lowercased per-component search blob all live in the embedded payload. The client never has to walk the raw definition JSON or recompute reference counts.
- **Vanilla JS DOM, no framework.** No Virtual DOM diffing, no reconciliation cost. The catalog re-renders rows by rebuilding a single `innerHTML` string when filters change — faster than per-row diffing for the table sizes we hit.
- **D3 only for the force simulation.** The rest of the JS is plain DOM, kept tight. D3 itself is ~280KB minified — vendored and inlined.
- **Lazy graph init.** The D3 simulation only runs when the user switches to the graph view for the first time. The catalog view is interactive immediately.
