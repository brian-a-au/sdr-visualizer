# CLAUDE.md

Guidance for Claude Code when working in this repo.

## What this is

`sdr-visualizer` is a static-output visual catalog generator for Adobe Customer Journey Analytics (CJA) and Adobe Analytics (AA) implementations. It consumes the same JSON snapshots as [`sdr-grader`](https://github.com/brian-a-au/sdr-grader) (from `cja_auto_sdr` / `aa_auto_sdr`) and emits a single self-contained HTML file: a catalog, a reference graph, and segment / calc-metric anatomy diagrams.

It is **not** an AI tool — no LLM calls, no agent loops. Plain Python builds the static output; plain JS (plus D3 for the graph) drives client-side interactivity. There is no server, no build step on the consumer side, and no CDN dependencies.

## Project authority

The tracked [`docs/PRODUCT_CONTRACT.md`](docs/PRODUCT_CONTRACT.md) defines the
supported inputs, stable public surfaces, resource bounds, confidentiality
guidance, compatibility policy, and release boundary. Read it before changing
public behavior. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) defines the
current data flow and module responsibilities; [`docs/RELEASING.md`](docs/RELEASING.md)
defines the evidence required for a candidate, publication, and announcement.

## Sibling project

`sdr-grader` is the sibling source for shared defensive behavior:

| sdr-grader path | sdr-visualizer path |
|---|---|
| `src/sdr_grader/core/models.py` | `src/sdr_visualizer/core/models.py` |
| `src/sdr_grader/adapters/{base,cja,aa}.py` | `src/sdr_visualizer/adapters/{base,cja,aa}.py` |
| `src/sdr_grader/input/{loader,detect,shell_out}.py` | `src/sdr_visualizer/input/{loader,detect,shell_out}.py` |
| `tests/fixtures/{cja,aa}_snapshot_*.json` | `tests/fixtures/{cja,aa}_snapshot_*.json` |

When vendoring, rewrite `sdr_grader` → `sdr_visualizer` in import paths. Fixtures may diverge over time (visualizer wants more component variety; grader wants more rule-triggering edge cases) but start identical.

The adapters have themselves diverged from the grader's copies — some legitimately (the grader carries evaluative/governance helpers the descriptive visualizer omits), some as deliberate visualizer-only behavior (numeric coercion raises for trend-skip and passes `NaN` through for the audit-H2 render guard, where the grader defaults). The shared defensive-coercion helpers (`_parse_tag_list`, `_parse_ref_list`, `_optional_list`) are kept behavior-identical and must be mirrored when touched. Before "syncing" an adapter to the sibling, read the **Vendoring parity with sdr-grader** section of [`docs/ADAPTER_GUIDE.md`](docs/ADAPTER_GUIDE.md) — it enumerates what is shared, what is grader-only, and which divergences are intentional and pinned by tests.

## Change discipline

Keep correctness, browser performance, release automation, documentation, and
community changes in reviewable units with focused tests. Do not combine
unrelated behavior changes merely because they share a release target.

## Develop

```bash
uv sync                # Set up environment
uv run pytest          # Run tests
uv run ruff check      # Lint
uv run ruff format     # Auto-format
```

## Architectural rules of the road

- **Static output, dynamic interaction.** Python emits one HTML file with embedded JSON, embedded CSS, embedded JS. No fetches, no API, no server.
- **Server-side build, client-side render.** Do work in Python (where seconds are fine); the client just reads, filters, and renders.
- **Vanilla JS, no framework.** D3 only for the reference graph. No React / Vue / Svelte.
- **Performance is enforced.** The budgets in [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) are CI-gated. An implementation that takes 5 seconds to render 500 components is broken regardless of how it looks.
- **The visualizer is descriptive, not evaluative.** No grades, no findings, no opinions. That belongs in `sdr-grader`.

## When in doubt

Prefer a tighter feature set executed beautifully over a broader feature set
executed adequately. Surface unresolved public-contract questions as GitHub
issues rather than silently expanding or weakening the contract.
