# sdr-visualizer

[![PyPI](https://img.shields.io/pypi/v/sdr-visualizer)](https://pypi.org/project/sdr-visualizer/)
[![Tests](https://github.com/brian-a-au/sdr-visualizer/actions/workflows/test.yml/badge.svg)](https://github.com/brian-a-au/sdr-visualizer/actions/workflows/test.yml)
[![Lint](https://github.com/brian-a-au/sdr-visualizer/actions/workflows/lint.yml/badge.svg)](https://github.com/brian-a-au/sdr-visualizer/actions/workflows/lint.yml)
[![Version Sync](https://github.com/brian-a-au/sdr-visualizer/actions/workflows/version-sync.yml/badge.svg)](https://github.com/brian-a-au/sdr-visualizer/actions/workflows/version-sync.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://img.shields.io/badge/coverage-92%25-brightgreen.svg)](tests/)
[![Tests](https://img.shields.io/badge/tests-308-brightgreen.svg)](tests/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Static-output visual catalog generator for Adobe Customer Journey Analytics (CJA) and Adobe Analytics (AA) implementations. Consumes JSON snapshots from [`cja_auto_sdr`](https://github.com/brian-a-au/cja_auto_sdr) and [`aa_auto_sdr`](https://github.com/brian-a-au/aa_auto_sdr) and produces a single self-contained HTML file with:

- A searchable, filterable component catalog (the primary view)
- An interactive force-directed reference graph
- Per-segment anatomy diagrams that make deeply-nested segments legible
- Per-calculated-metric formula trees with click-through to referenced metrics

![The catalog view: header stats strip, search and filters, and the component table](https://raw.githubusercontent.com/brian-a-au/sdr-visualizer/main/docs/screenshot-catalog.png)

**Live examples:** [CJA report](https://brian-a-au.github.io/sdr-visualizer/cja-typical.html) · [AA report](https://brian-a-au.github.io/sdr-visualizer/aa-typical.html)

The output is one HTML file: no server, no build step on the consumer side, no CDN dependencies. Everything is built into that one file. The component data is stored as JSON, the styling as CSS, and the interactive code as JavaScript, all inside it. You open it by double-clicking it in any modern web browser, and it works without an internet connection. There are no network requests, so no data is sent anywhere, and you can open it safely inside a locked-down corporate environment. You can move it, rename it, or copy it anywhere, and it still opens the same way. Drop it on a wiki, email it to a stakeholder, screenshot it into a deck.

## Install

```bash
uv tool install sdr-visualizer
```

Or with pip:

```bash
pip install sdr-visualizer
```

(Requires 0.6.0 or later on PyPI.) For development, run from a clone:

```bash
git clone https://github.com/brian-a-au/sdr-visualizer
cd sdr-visualizer
uv sync
uv run sdr-visualizer --help
```

## Quickstart

```bash
# Mode 1: from a snapshot file
sdr-visualizer path/to/snapshot.json

# Mode 2: from a directory of snapshots (uses the most recent)
sdr-visualizer path/to/snapshots/

# Mode 3: shell out to the upstream tool
sdr-visualizer --dataview dv_prod_web        # CJA
sdr-visualizer --rsid prod_us                # AA

# Mode 4: stdin
cja_auto_sdr dv_prod_web --format json --output - | sdr-visualizer -

# Compare against an earlier snapshot: adds a Changes view to the report
sdr-visualizer snapshot_new.json --compare-to snapshot_old.json

# Chart evolution across a directory of snapshots: adds a Trend view
sdr-visualizer ./snapshots/ --trend
```

The output lands at `./visualize-{instance_id}-{timestamp}.html` by default. Open it in a browser — that's the whole experience.

## Useful flags

| Flag | What it does |
|---|---|
| `--output PATH`           | Write HTML somewhere specific. |
| `--json PATH`             | Also emit the embedded payload as a separate JSON file (useful for downstream tooling). |
| `--title TEXT`            | Override the document title. |
| `--exclude-orphans`       | Default the catalog's references filter to "Referenced" — hides components nothing depends on. |
| `--max-graph-nodes N`     | Override the 1,000-node graph-rendering threshold. |
| `--platform cja\|aa`      | Override platform auto-detection. |
| `--at TIMESTAMP`          | When path is a directory, pick the snapshot closest to (and not after) this timestamp. |
| `--quiet`                 | Suppress informational stderr output. |

## What's in the output

Open the generated HTML and you'll see four views, accessible from the top-level navigation:

1. **Catalog** — a searchable, filterable, sortable table of every component. Click a row to slide out a detail panel with description, properties, references, and anatomy.
2. **Reference graph** — a force-directed view of every component and the edges between them; small implementations (under 20 components) use a static radial layout instead. Hover dims unrelated nodes; click opens the same detail panel; drag pins; pan/zoom.
3. **Segment anatomy** (contextual) — opens from a segment's detail panel. Renders the segment's definition tree as nested containers with subtle alpha-stacked shading per nesting level, color-coded AND/OR/NOT chips, and clickable inline references to other segments.
4. **Calculated metric anatomy** (contextual) — opens from a calc metric's detail panel. Renders the formula as a tree of operations and operands; metric refs are clickable.

With `--compare-to`, a fifth **Changes** view appears, listing components
added, removed, and modified relative to a baseline snapshot, with
field-level before/after detail.

With `--trend` on a snapshot directory, a **Trend** view appears: sparkline
charts of descriptive aggregates (component counts, orphans, undocumented
components, reference edges) across the directory's snapshots, plus a
per-interval change log. The window is capped at the 60 most recent
snapshots.

A trend directory must hold snapshots of a single implementation. If it mixes
CJA and AA snapshots, pass `--platform cja|aa` to select one (or point at a
single-platform directory); without it the run stops rather than guess. If it
mixes data views or report suites, the run stops as well. This mirrors
`--compare-to`, which refuses both a platform and an instance mismatch, so
neither view ever diffs unrelated inventories. To compare or chart across
different data views or report suites on purpose (for example staging versus
prod drift), pass `--allow-instance-mismatch`; the run then proceeds with a
warning. Platform mismatches are always rejected. The report shown alongside
the trend is the newest usable snapshot in the directory.

- **Shareable links** — the catalog's filters, sort, view, and open detail panel are encoded in the URL hash; copy the address bar to share a filtered view.

## Performance budget

The output is CI-gated against the budgets in [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md).
Build time and HTML size are enforced at every §6 tier (100 / 500 / 1,000 / 2,000
components). Browser-measured budgets are enforced at the 1,000-component tier
(initial render < 1s, filter/search < 150ms) and the 2,000-component tier
(< 2s, < 300ms), plus a 700ms cap on the graph view's main-thread block.

## Stability

From 1.0.0, [semantic versioning](https://semver.org) covers the surface below. Anything not listed is internal and may change in any release.

**CLI.** The argument set: the positional `path` (snapshot file, snapshot directory, or `-` for stdin), `--dataview`, `--rsid`, `--platform`, `--at`, `--compare-to`, `--trend`, `--allow-instance-mismatch`, `--output`, `--title`, `--exclude-orphans`, `--max-graph-nodes`, `--json`, `--quiet`, `--version`. Removing or repurposing any of these is a major bump; adding flags is a minor one.

**Exit codes.** `0` success, `1` runtime error, `3` invalid input. `2` is never used.

**The data payload.** The JSON embedded in every report and the `--json` sidecar share one schema, published at [docs/payload-schema.json](https://github.com/brian-a-au/sdr-visualizer/blob/main/docs/payload-schema.json) (JSON Schema 2020-12), validated in CI against every payload shape the bundled fixtures produce, and against a real corpus of 108 production snapshots before each release. Removing or retyping a field is major; adding optional fields is minor. The `segment_trees` / `formula_trees` node internals are documented in the schema as loosely specified.

**Performance budgets.** The tier table above is a guarantee, not a goal: loosening a budget is a breaking change; tightening one is minor.

Warnings (snapshot generator newer than the tested version; 5,000+ component reports) are informational and never make a valid snapshot fail.

## Develop

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv).

```bash
uv sync                # Set up environment
uv run pytest          # Run tests (auto-generates the large fixture on first run)
uv run ruff check      # Lint
uv run ruff format     # Auto-format

uv run python scripts/generate_examples.py   # Regenerate examples/
uv run python scripts/perf_check.py          # Run the perf gate
```

## See also

- [`sdr-grader`](https://github.com/brian-a-au/sdr-grader) — deterministic, rule-based linter for the same input format.
- [`cja_auto_sdr`](https://github.com/brian-a-au/cja_auto_sdr) — generates CJA snapshots.
- [`aa_auto_sdr`](https://github.com/brian-a-au/aa_auto_sdr) — generates AA snapshots.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — module layout, one-way data flow, design principles.
- [`docs/ADAPTER_GUIDE.md`](docs/ADAPTER_GUIDE.md) — how the CJA and AA adapters work, and how to add a new platform.
- [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) — performance budgets and how they're enforced.
- [`docs/EMBEDDED_DATA_FORMAT.md`](docs/EMBEDDED_DATA_FORMAT.md) — the JSON payload format embedded in the HTML output.

## License

MIT — see [`LICENSE`](LICENSE). The output bundles [D3](https://d3js.org) v7,
vendored under the ISC license; see
[`THIRD_PARTY_LICENSES`](THIRD_PARTY_LICENSES) for the full notice.
