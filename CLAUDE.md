# CLAUDE.md

Guidance for Claude Code when working in this repo.

## What this is

`sdr-visualizer` is a static-output visual catalog generator for Adobe Customer Journey Analytics (CJA) and Adobe Analytics (AA) implementations. It consumes the same JSON snapshots as [`sdr-grader`](https://github.com/brian-a-au/sdr-grader) (from `cja_auto_sdr` / `aa_auto_sdr`) and emits a single self-contained HTML file: a catalog, a reference graph, and segment / calc-metric anatomy diagrams.

It is **not** an AI tool — no LLM calls, no agent loops. Plain Python builds the static output; plain JS (plus D3 for the graph) drives client-side interactivity. There is no server, no build step on the consumer side, and no CDN dependencies.

## The spec

The full project spec lives **outside the repo** at `./SPEC-VISUALIZER.md` in the local working directory (gitignored intentionally — the working folder is preserved as a reference area, the repo is the deliverable). Read it end-to-end before scaffolding or extending anything. Sections of particular load:

- §3 The four views (catalog is primary; graph + segment anatomy + calc-metric anatomy are companions)
- §4 Visual register (publication serif body, Söhne UI, restrained palette; sibling to grader)
- §5 Architecture (server-side build, client-side render; one HTML file, no fetches)
- §6 Performance budget (CI-enforced, not aspirational)
- §8 Normalized internal model (vendored verbatim from sdr-grader; same shapes)
- §10 Build phases (do not skip; do not merge)
- §11 Vendoring rationale (why we duplicate models/adapters/input from sdr-grader rather than share a package)
- §12 Decisions already made (do not relitigate)

## Sibling project

`sdr-grader` lives next door at `../sdr-grader` and is the source for vendored files per §15:

| sdr-grader path | sdr-visualizer path |
|---|---|
| `src/sdr_grader/core/models.py` | `src/sdr_visualizer/core/models.py` |
| `src/sdr_grader/adapters/{base,cja,aa}.py` | `src/sdr_visualizer/adapters/{base,cja,aa}.py` |
| `src/sdr_grader/input/{loader,detect,shell_out}.py` | `src/sdr_visualizer/input/{loader,detect,shell_out}.py` |
| `tests/fixtures/{cja,aa}_snapshot_*.json` | `tests/fixtures/{cja,aa}_snapshot_*.json` |

When vendoring, rewrite `sdr_grader` → `sdr_visualizer` in import paths. Fixtures may diverge over time (visualizer wants more component variety; grader wants more rule-triggering edge cases) but start identical.

## Phase discipline

Each phase in §10 produces a single reviewable artifact. Don't proceed to phase N+1 until phase N is reviewed. Don't bundle phases. Phase 3 (catalog view) is the largest single piece of work — spend disproportionate care there.

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
- **Performance is enforced.** §6 budgets are CI-gated. An implementation that takes 5 seconds to render 500 components is broken regardless of how it looks.
- **The visualizer is descriptive, not evaluative.** No grades, no findings, no opinions. That belongs in `sdr-grader`.

## When in doubt

Prefer a tighter feature set executed beautifully over a broader feature set executed adequately. Surface ambiguity as a GitHub issue rather than guessing — SPEC §14 has the open questions list as a starting point.
