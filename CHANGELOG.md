# Changelog

All notable changes to `sdr-visualizer` will be documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-07-11

### Changed

- **Graph view warm-up no longer freezes on huge graphs.** The synchronous
  warm-up that pre-settles the force simulation now runs until near-settled
  or a 150 ms budget elapses, whichever comes first (it ran a fixed 60–120
  ticks before — ~0.8 s blocked at 2,000 nodes, ~2.2 s at 5,000). Graphs
  that can't settle in budget finish asynchronously, one tick per frame.
  The simulation also uses a coarser Barnes-Hut theta and faster alpha
  decay (~30% cheaper ticks) above 1,000 nodes — §6's interactive ceiling —
  or above a lower `--max-graph-nodes` opt-in threshold, whichever is
  smaller.
- **Graph hover/filter repaints coalesced to one pass per frame.** Filter
  state is recomputed only when a filter input changes; hover and filter
  paints apply all node/link classes in a single pass per selection and are
  batched through `requestAnimationFrame`. Sweeping the pointer across a
  5,000-node graph previously cost up to ~3.6 ms per mouseover/mouseout
  event in full selection walks. The graph search box is now debounced
  (120 ms), matching the catalog search. The hover/filter contract is now
  explicit: hover fading wins while active, search-match highlights persist
  through hover (now honored visually too — the fade previously dimmed the
  highlight ring), and any filter or search change cancels an active hover
  and repaints on the next frame. (Also fixes a pre-existing bug where a
  hovered node's edge highlights could linger after mouseout.)

### Added

- `THIRD_PARTY_LICENSES` with the D3 v7.9.0 ISC license notice — D3 is
  redistributed in the repo, in built packages (wheel `dist-info/licenses/`,
  sdist), and inlined into every generated report. `pyproject.toml` now uses
  the SPDX `license` string + `license-files` so both files ship in
  distributions.
- **Shareable URL state.** Catalog search, type/description/references/modified
  filters, sort, the active view, and the open detail panel are reflected in
  `location.hash` — copy the URL to share a filtered view ("every undocumented
  metric"). Restored on load. (SPEC §14 Q1)
- **Radial layout for small graphs.** Implementations with fewer than 20
  components skip the force simulation and place nodes evenly on a circle —
  force-directed layouts look chaotic at that size. Drag and reset still work.
  (SPEC §14 Q2)
- CI browser gate now also asserts entering the graph view blocks the main
  thread < 700 ms (`scripts/perf_browser_check.py`) — script time plus a
  forced style/layout flush of the inserted SVG — timing the worst-case
  "Render anyway" path on both large fixtures (and failing if that path
  stops being exercised); plus browser-level functional tests for hover
  neighbor-highlighting, graph search fade/highlight, and filter-cancels-
  hover behavior.
- Perf gate now enforces the SPEC §6 100- and 500-component tiers (build
  time + HTML size) via generated small fixtures, and the browser gate
  covers the AA path and asserts per-tier budgets (1,000-component budgets
  on the large fixtures, 2,000-component on XL).

### Fixed

- Canonical Adobe segment roots (`{"func": "segment", "container": {...}}`)
  parse into a full anatomy tree instead of collapsing to one empty
  segment reference.
- Snapshots containing `NaN`/`Infinity` exit 3 with a clear message instead
  of emitting a report whose payload the browser cannot parse (exit 0).
- Usage errors exit 3, not argparse's default 2 (SPEC §7 forbids 2), and
  unwritable `--output`/`--json` paths exit 1 with a clean message instead
  of a traceback.
- AA segment `nesting_depth` counts container nesting; it previously
  reported raw JSON depth (a single-container segment claimed depth 4).
- Explicit JSON `null` reference keys in CJA snapshots parse as empty
  instead of crashing.
- `--at` accepts full ISO-8601 (offsets, fractional seconds) and warns when
  passed with non-directory input modes, where it never applied.
- Date cells display the timestamp's date prefix — Safari showed raw
  strings and Chrome could drift a day against the modified filter.
- A shared URL with every type filter unchecked restores as unchecked.
- AA calc-metric formula summaries render nested formulas readably instead
  of leaking Python dict syntax; classifications without a name or id no
  longer add blank tag chips.
- Duplicate component ids in a snapshot print a build warning (anatomy
  trees for duplicated ids are last-writer-wins).
- Shell-out output decodes as UTF-8 regardless of host locale.

### Security

- The embedded JSON payload now escapes `<` as the JSON unicode escape `\u003c` (transparent to `JSON.parse`). Previously a snapshot
  field containing `</script>` (e.g. a hostile component description) could
  terminate the data block and inject live markup into the generated HTML.
- Jinja autoescaping now applies to all templates (`autoescape=True`).
  `select_autoescape(["html"])` never matched `index.html.j2` (final
  extension `.j2`, not `.html`), so template-interpolated values — the
  document title and instance name — rendered unescaped: a hostile Data
  View name could inject live markup into the page. Same class of stored
  XSS as the payload escape above; both shipped in the same fix pass.

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

- Not yet validated against real customer `cja_auto_sdr` / `aa_auto_sdr` output beyond the vendored grader fixtures. *(Since resolved: validated against real cja_auto_sdr / aa_auto_sdr output.)*
- No browser-side performance gate yet (Python build time + HTML size are gated; client-side render and filter latency aren't). *(Resolved in 0.2.0 by scripts/perf_browser_check.py.)*
- The PyPI publish step in `release.yml` is `continue-on-error: true` until trusted-publisher is configured at pypi.org.

### Deferred to later releases (per SPEC §13)

- Comparative view, two snapshots side-by-side (v0.2)
- Trend mode against a directory of snapshots (v0.3)
- Workspace project visualization (v0.4)
- Schema map view (v0.5)

[0.3.0]: https://github.com/brian-a-au/sdr-visualizer/releases/tag/v0.3.0
[0.2.0]: https://github.com/brian-a-au/sdr-visualizer/releases/tag/v0.2.0
[0.1.0]: https://github.com/brian-a-au/sdr-visualizer/releases/tag/v0.1.0
