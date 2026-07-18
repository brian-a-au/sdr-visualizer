# Changelog

All notable changes to `sdr-visualizer` will be documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Boundary tests pin the contract warnings: Q4's exact 5,000-component
  edge and its once-per-run firing under `--compare-to` / `--trend`, plus
  Q5's tuple-length version comparisons.
- Browser tests pin the derived-metric filter path and the client-rendered
  no-description chip, catalog marker, and detail-panel state.

### Changed

- The changes view's filter input is debounced by 120 ms, matching the
  catalog search; it previously rerendered on every keystroke.
- `version-sync` CI failures now name the extraction or version-drift
  problem instead of ending with a raw regex traceback.

### Fixed

- `_version_tuple`'s unreachable `TypeError` handler was removed in both
  adapters and mirrored to sdr-grader with the deferred parity documentation
  follow-ups ([sdr-grader PR #21](https://github.com/brian-a-au/sdr-grader/pull/21)).
- Speculative rationales were removed from scalar-coercion docstrings while
  preserving their defensive behavior.

## [1.0.1] - 2026-07-18

### Fixed

- The CJA adapter now reads the timestamp key real `cja_auto_sdr`
  exports actually carry (`Generated Date & timestamp and timezone`) —
  previously ~93% of real CJA reports rendered with no snapshot
  timestamp. Verified against the private corpus: 100/100 real CJA
  snapshots now carry one.
- A calculated metric whose formula `args` is a scalar no longer
  crashes report rendering with a bare `TypeError` (fuzz-found; the
  formula tree degrades to an operation with no arguments, matching its
  never-raise design).
- Wrong-typed optional scalars (`owner`, `created_at` / `modified_at`,
  a derived field's output type) are coerced at the adapter layer —
  stringified, or dropped when a timestamp is not a string — instead of
  flowing into the payload as non-strings the published schema rejects
  and the client renders wrongly. All adapter fixes in this release are
  mirrored to sdr-grader in the same cycle
  (https://github.com/brian-a-au/sdr-grader/pull/20).
- The payload schema wrongly required `trend.snapshots[].taken_at` to
  be a string; shipped 1.0.0 behavior emits null for a timestamp-less
  snapshot. Widened to nullable — a correction to match reality, not a
  contract change.

### Added

- The fuzz suite's render-path property now validates every accepted
  payload against `docs/payload-schema.json`, catching schema-vs-reality
  drift as a class instead of one review finding at a time. It earned
  its keep immediately: the formula-tree crash and the wrong-typed
  scalar passthroughs above were all surfaced by this gate.

## [1.0.0] - 2026-07-17

1.0.0 is a promise more than a feature release: the CLI surface, exit
codes, data payload, and performance budgets are now covered by semantic
versioning, and the release was validated against a real corpus of 108
production `cja_auto_sdr` / `aa_auto_sdr` snapshots (0 failures, size
budgets and payload-schema validation included).

### Added

- `docs/payload-schema.json` (JSON Schema 2020-12): the schema shared by
  the embedded payload and the `--json` sidecar. Validated in CI against
  every payload shape the fixtures can produce, and by
  `scripts/corpus_check.py` against real snapshots, so it cannot drift
  from reality.
- Derived fields now carry their declared functional kind: real
  `cja_auto_sdr` records mark each derived field as a Dimension or
  Metric, and the payload's optional `derived_kind` surfaces it. The
  catalog's Dimension / Metric filters also match derived fields of that
  kind, and the type column reads "Derived dimension" / "Derived
  metric". Declared only — never inferred.
- Build warning at 5,000+ components (SPEC §14 Q4): the report still
  builds; the warning states the size and that the graph view stays
  behind its `--max-graph-nodes` opt-in.
- Generator-version compatibility warning (SPEC §14 Q5): warns — never
  refuses — when a snapshot's generator is newer than the newest version
  this release was tested against (CJA 3.5.17, AA 1.18.0; per-adapter
  constants in the vendored layer, mirrored to sdr-grader).
- Standalone `lint` and `version-sync` workflows (backing the new README
  badge row, which now mirrors the cja_auto_sdr / aa_auto_sdr set).

### Changed

- The repository went public on 2026-07-17: the examples site is live on
  GitHub Pages, `pages.yml` deploys on pushes to main again, and the
  README regained its catalog screenshot (as an absolute URL, so it
  renders on the PyPI page too) and live-example links.
- The README states the stability contract: covered CLI argument set,
  exit codes 0/1/3, the payload schema, and the performance-budget
  guarantee. Template structure, CSS selectors, and module internals stay
  explicitly uncovered.

### Fixed

- Reports without derived fields (every AA report, and CJA views that
  have none) no longer offer a "Derived field" type filter chip in the
  catalog and graph views.

### Notes

- SPEC §14 fully resolved: Q1/Q2 shipped in 0.3.0; Q3 (Adobe UI links)
  and Q6 (Open Graph metadata) rejected; Q4 and Q5 shipped here as
  warnings.
- The accessibility pass is deliberately the first 1.x item, not a 1.0.0
  blocker.

## [0.6.0] - 2026-07-17

### Added

- Property-based fuzz suite (`tests/test_adapter_fuzz.py`, ported from
  sdr-grader and extended): random and mutated-fixture inputs must produce
  a valid report or `InvalidSnapshotError` — never a bare crash — through
  the adapters AND the render path, including the NaN/Infinity payload
  class.
- Browser functional tests now run on webkit as well as Chromium in CI;
  performance budgets remain Chromium-only by design.
- `scripts/corpus_check.py`: sweep a private directory tree of real
  snapshots through the full build, asserting adapter acceptance, payload
  serializability, embedded-payload parseability, and (optionally) the
  §6 size budget per tier. A clean corpus sweep becomes the 1.0.0 gate;
  swept clean ahead of this release over the local real corpus
  (108 snapshots, budget checks included).
- Contributor hygiene: `CONTRIBUTING.md`, PR and issue templates, and
  `SECURITY.md` with private reporting via GitHub security advisories.
- The example reports can be published via GitHub Pages (`pages.yml`;
  deploys are manual until Pages is enabled for the repo). The README's
  catalog screenshot and live-example links are held back until the site
  is live — the README is also the PyPI page, where they cannot resolve
  yet; `docs/screenshot-catalog.png` ships in the repo meanwhile.
- Dependabot keeps the SHA-pinned GitHub Actions and the Python
  dependencies current (weekly, grouped into one PR per ecosystem).

### Changed

- Releases now publish to PyPI via trusted publishing (OIDC, `pypi`
  environment) as a hard step — a publish failure fails the release.
  Release assets no longer include the stray `default.gitignore` file.
- README install instructions point at PyPI again (0.6.0 is the first
  published release); installing from the repo remains the development
  path.
- CI pins `astral-sh/setup-uv` by commit SHA at v8.3.2 (previously the
  mutable `v3` tag) and sets `prune-cache: false`, so cached pre-built
  wheels are no longer stripped and re-downloaded from PyPI on every
  run. The release build job now uses the cache too.

### Fixed

- The AA and CJA adapters no longer crash with a bare `TypeError`/`ValueError`
  on a malformed optional field (found by the new fuzz suite). A truthy
  non-list `tags` or `*_references` value degrades to an empty list; a
  present-but-unconvertible `nesting_depth` or `complexity_score` now raises
  `InvalidSnapshotError` (so a single snapshot exits 3 and the trend loader
  skips such a snapshot) instead of a bare exception. These files are
  vendored from sdr-grader, which already carried equivalent type guards —
  the visualizer had drifted behind, and nothing is owed to the sibling repo.
- The sdist is now built from an explicit file allowlist
  (`[tool.hatch.build.targets.sdist]`). Hatchling's default includes every
  non-gitignored file in the project directory — tracked or not — which
  swept local tool state (a Claude Code lock file, the Hypothesis example
  cache) and repo-meta content (the example HTML pages, the README
  screenshot, `uv.lock`, `CLAUDE.md`) into the tarball. The wheel was
  always restricted to `src/sdr_visualizer` and is unaffected, and no sdist
  was ever published (PyPI publishing starts with 0.6.0). `.claude/` and
  `.hypothesis/` are gitignored as a second layer of defense.

## [0.5.0] - 2026-07-12

### Added

- **Trend mode.** `--trend` on a snapshot directory adds a Trend view:
  server-rendered sparkline charts of descriptive aggregates (total and
  per-type component counts, orphans, components without a description,
  reference edge count) across the directory's snapshots, plus a change log
  with one expandable row per adjacent snapshot pair (added / removed /
  modified component ids, computed with the 0.4.0 diff engine). The window
  honors `--at` as its end and is capped at the 60 most recent parseable
  snapshots with a build warning. Unparseable snapshots and snapshots with an
  unconvertible scalar field are skipped with warnings. A directory that mixes
  platforms exits 3 unless `--platform cja|aa` selects one, and a directory
  that mixes data views / report suites exits 3, so unrelated inventories are
  never diffed (mirroring `--compare-to`, which refuses both). Fewer than 2
  usable snapshots exits 3, as does combining `--trend` with `--compare-to`,
  `--dataview`, `--rsid`, a file path, or stdin. (SPEC §13, trend mode)
- **`--allow-instance-mismatch`.** Opt-in flag that lets `--compare-to` and
  `--trend` span different data views / report suites on purpose (for example
  staging versus prod drift); the run proceeds with a warning instead of
  exiting 3. Platform mismatches are always rejected.

### Changed

- **`--compare-to` now refuses an instance mismatch.** Comparing snapshots
  from different data views / report suites exits 3 instead of warning and
  proceeding (0.4.0 behavior), matching `--trend`; both views require a single
  implementation so the diff never spans unrelated inventories. Pass
  `--allow-instance-mismatch` to restore the cross-instance comparison on
  demand.

### Fixed

- **Cross-command flag consistency.** `--at` now resolves a `--compare-to`
  baseline directory the same way it resolves the primary directory (it was
  silently ignored for the baseline, which always used the latest snapshot).
  A directory mixing timestamped and un-timestamped snapshots now warns about
  the dropped un-timestamped files in single-snapshot and `--compare-to`
  selection, matching `--trend`. `--platform` combined with `--dataview` /
  `--rsid` is ignored with a warning instead of forcing a mismatched adapter.

## [0.4.0] - 2026-07-11

### Added

- **Comparative view.** `--compare-to BASELINE` (a snapshot file, or a
  directory that resolves to its latest snapshot) adds a Changes view to the
  report: components added, removed, and modified against the baseline, with
  field-level before/after detail. The diff is computed at build time and
  embedded as the payload's `changes` section — the baseline snapshot itself
  is never embedded, so the report grows only with the size of the diff.
  A platform mismatch between the two snapshots exits 3; differing instance
  ids warn but proceed. (SPEC §13, comparative view)

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
- The PyPI publish step in `release.yml` is `continue-on-error: true` until trusted-publisher is configured at pypi.org. *(Resolved in 0.6.0: publishing moved to a hard, gated publish job — a failure fails the release.)*

### Deferred to later releases (per SPEC §13)

- Comparative view, two snapshots side-by-side (v0.2) *(Shipped in 0.4.0.)*
- Trend mode against a directory of snapshots (v0.3) *(Shipping in 0.5.0.)*
- Workspace project visualization (v0.4)
- Schema map view (v0.5)

[1.0.1]: https://github.com/brian-a-au/sdr-visualizer/releases/tag/v1.0.1
[1.0.0]: https://github.com/brian-a-au/sdr-visualizer/releases/tag/v1.0.0
[0.6.0]: https://github.com/brian-a-au/sdr-visualizer/releases/tag/v0.6.0
[0.5.0]: https://github.com/brian-a-au/sdr-visualizer/releases/tag/v0.5.0
[0.4.0]: https://github.com/brian-a-au/sdr-visualizer/releases/tag/v0.4.0
[0.3.0]: https://github.com/brian-a-au/sdr-visualizer/releases/tag/v0.3.0
[0.2.0]: https://github.com/brian-a-au/sdr-visualizer/releases/tag/v0.2.0
[0.1.0]: https://github.com/brian-a-au/sdr-visualizer/releases/tag/v0.1.0
