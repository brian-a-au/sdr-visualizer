# sdr-visualizer

Static-output visual catalog generator for Adobe Customer Journey Analytics (CJA) and Adobe Analytics (AA) implementations. Consumes JSON snapshots from [`cja_auto_sdr`](https://github.com/brian-a-au/cja_auto_sdr) and [`aa_auto_sdr`](https://github.com/brian-a-au/aa_auto_sdr) and produces a single self-contained HTML file with a searchable component catalog, an interactive reference graph, and per-segment / per-calculated-metric anatomy diagrams.

It is the visual companion to [`sdr-grader`](https://github.com/brian-a-au/sdr-grader). Where the grader answers "is this implementation good?", the visualizer answers "what does this implementation look like?".

## Status

Pre-release. Phase 1 (models, CJA adapter, fixtures) is in place; the catalog, graph, and anatomy views are not yet implemented. See `SPEC-VISUALIZER.md` (kept locally, not committed) for the build roadmap.

## Develop

```bash
uv sync                # Set up environment
uv run pytest          # Run tests
uv run ruff check      # Lint
uv run ruff format     # Auto-format
```

## See also

- [`sdr-grader`](https://github.com/brian-a-au/sdr-grader) — deterministic, rule-based linter for the same input format.
- [`cja_auto_sdr`](https://github.com/brian-a-au/cja_auto_sdr) — generates CJA snapshots.
- [`aa_auto_sdr`](https://github.com/brian-a-au/aa_auto_sdr) — generates AA snapshots.

## License

MIT
