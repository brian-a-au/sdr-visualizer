# Changelog

All notable changes to `sdr-visualizer` will be documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- The embedded JSON payload now escapes `<` as the JSON unicode escape `\u003c` (transparent to `JSON.parse`). Previously a snapshot
  field containing `</script>` (e.g. a hostile component description) could
  terminate the data block and inject live markup into the generated HTML.

### Added

- **Shareable URL state.** Catalog search, type/description/references/modified
  filters, sort, the active view, and the open detail panel are reflected in
  `location.hash` — copy the URL to share a filtered view ("every undocumented
  metric"). Restored on load. (SPEC §14 Q1)
- **Radial layout for small graphs.** Implementations with fewer than 20
  components skip the force simulation and place nodes evenly on a circle —
  force-directed layouts look chaotic at that size. Drag and reset still work.
  (SPEC §14 Q2)
- Browser-level functional tests (Playwright) covering script-injection,
  URL-state restore, and the radial layout; run in CI's browser-perf job.

## [0.2.0] - 2026-06-10

Performance and scaling release. The embedded payload contract changed (see
Removed) — per the stability policy this bumps the leftmost non-zero version.

### Added

- `modified_ts` (epoch ms) on every catalog entry — the client sorts and
  date-windows without constructing `Date` objects in hot paths.
- Browser-side performance gate (`scripts/perf_browser_check.py`, Playwright):
  initial render + filter latency budgets now enforced in CI alongside the
  existing build-time/size gate.
- 2,000-component budget tier gated in CI via a generated XL fixture
  (`scripts/generate_large_fixture.py --scale 1.67`).
- Catalog row cap: above 1,000 matching rows the table truncates with a
  "Showing 1,000 of N · Show all" escape hatch.
- Graph label culling (graphs over 200 nodes label only the top-60 in-degree nodes by default; all labels
  past 1.4× zoom or on hover) and warm-started force simulation (near-settled
  first paint).

### Changed

- Client builds the search index and sort keys in one pass at load; row HTML
  is cached per entry; the master list stays pre-sorted; search input is
  debounced (120 ms). Net: filter latency stays flat into the thousands of
  components.
- Graph hover/filter passes use precomputed neighbor counts.

### Removed (breaking, embedded payload + `--json` shape)

- `catalog_index` — the client builds its own search blob at load.
- `graph.nodes`, `graph.in_degree`, `graph.out_degree` — derivable from
  catalog entries; only `graph.edges` ships.
- `platform_specific` on component entries — never consumed by the client;
  consult the original snapshot for platform extras.
- Null/empty fields on entries (sparse encoding) — consumers must treat a
  missing key as null/empty.

Net payload reduction: ~40% at the 1,200-component tier.

## [0.1.0] - 2026-05-09

First releasable cut. Feature-complete per [`SPEC-VISUALIZER.md`](SPEC-VISUALIZER.md) §10 phases 0–10. Surface (CLI flags, `--json` payload shape, exit codes, embedded payload schema) is documented but not yet hardened against real-world implementations — expect changes between 0.x releases as feedback comes in.

### Added

- **Catalog view (primary).** Searchable, filterable, sortable table of every component (metric / dimension / derived field / segment / calculated metric). Click a row to slide out a detail panel with description, properties, references, and anatomy.
- **Reference graph view.** D3 force-directed layout with per-type color coding, in-degree-proportional node sizing, hover-to-highlight neighbors, drag-to-pin, pan + zoom, and graceful degradation above the 1,000-node threshold (configurable via `--max-graph-nodes`).
- **Segment anatomy.** Reached from a segment's detail panel. Renders the segment definition tree as nested containers with subtle alpha-stacked shading per nesting depth, color-coded AND/OR/NOT operators, and clickable inline references to other segments.
- **Calculated-metric anatomy.** Reached from a calc metric's detail panel. Renders the formula as a tree of operations and operands; metric refs are clickable.
- **CJA + AA adapters.** Vendored from `sdr-grader` v1.0 per SPEC §15. Handle missing-description normalization, segment depth + container-context extraction, calc-metric formula parsing across both shapes (CJA `col1`/`col2`, AA `args`), classifications-as-tags for AA.
- **Four input modes.** File path, snapshot directory (with `--at TIMESTAMP`), shell-out to `cja_auto_sdr` / `aa_auto_sdr`, stdin.
- **CLI flags.** `--platform`, `--output`, `--json`, `--title`, `--exclude-orphans`, `--max-graph-nodes`, `--at`, `--quiet`, `--version`. Exit codes 0 / 1 / 3 per SPEC §7.
- **Single-file output.** All CSS, JS (vanilla + D3 v7), and JSON payload inlined. No fetches, no CDNs, no external resources.
- **Performance gate.** `scripts/perf_check.py` enforces SPEC §6 budgets (build time + HTML size) for both CJA and AA at the 1,000-component class. Wired into CI.
- **Documentation.** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md), [`docs/ADAPTER_GUIDE.md`](docs/ADAPTER_GUIDE.md), [`docs/EMBEDDED_DATA_FORMAT.md`](docs/EMBEDDED_DATA_FORMAT.md).

### Stability

The following surfaces are intended to be SemVer-stable from 0.1 onwards (breaking changes will bump the leftmost non-zero version):

- CLI flag names and behavior
- Exit codes
- The embedded JSON payload's documented top-level keys (per `docs/EMBEDDED_DATA_FORMAT.md`)
- The `--json` output shape

The following are explicitly internal and may change without notice:

- Template HTML structure / class names / IDs
- CSS selectors
- Module layout under `sdr_visualizer.*` (use the CLI or import from `sdr_visualizer.core.visualizer` only)

### Known limitations

- Not yet validated against real customer `cja_auto_sdr` / `aa_auto_sdr` output beyond the vendored grader fixtures.
- No browser-side performance gate yet (Python build time + HTML size are gated; client-side render and filter latency aren't).
- The PyPI publish step in `release.yml` is `continue-on-error: true` until trusted-publisher is configured at pypi.org.

### Deferred to later releases (per SPEC §13)

- Comparative view, two snapshots side-by-side (v0.2)
- Trend mode against a directory of snapshots (v0.3)
- Workspace project visualization (v0.4)
- Schema map view (v0.5)

[0.2.0]: https://github.com/brian-a-au/sdr-visualizer/releases/tag/v0.2.0
[0.1.0]: https://github.com/brian-a-au/sdr-visualizer/releases/tag/v0.1.0
