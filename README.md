# sdr-visualizer

[![Tests](https://github.com/brian-a-au/sdr-visualizer/actions/workflows/test.yml/badge.svg)](https://github.com/brian-a-au/sdr-visualizer/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Static-output visual catalog generator for Adobe Customer Journey Analytics (CJA) and Adobe Analytics (AA) implementations. Consumes JSON snapshots from [`cja_auto_sdr`](https://github.com/brian-a-au/cja_auto_sdr) and [`aa_auto_sdr`](https://github.com/brian-a-au/aa_auto_sdr) and produces a single self-contained HTML file with:

- A searchable, filterable component catalog (the primary view)
- An interactive force-directed reference graph
- Per-segment anatomy diagrams that make deeply-nested segments legible
- Per-calculated-metric formula trees with click-through to referenced metrics

It is the visual companion to [`sdr-grader`](https://github.com/brian-a-au/sdr-grader). Where the grader answers *"is this implementation good?"*, the visualizer answers *"what does this implementation look like?"*.

The output is one HTML file: no server, no build step on the consumer side, no CDN dependencies. Drop it on a wiki, email it to a stakeholder, screenshot it into a deck.

## Install

```bash
uv tool install sdr-visualizer
```

Or with pip:

```bash
pip install sdr-visualizer
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

- **Shareable links** — the catalog's filters, sort, view, and open detail panel are encoded in the URL hash; copy the address bar to share a filtered view.

## Performance budget

The output is CI-gated against the budgets in [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md). At 1,000 components:

- Build time: < 6s
- HTML size:  < 4MB
- Initial render: < 1s
- Filter/search latency: < 150ms

## Develop

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
