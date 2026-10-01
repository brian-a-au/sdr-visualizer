# Repository guidance

This is the canonical working guide for contributors and AI coding agents across
this repository. Keep shared setup, validation, architecture, and contribution
instructions here; `CLAUDE.md` and `CONTRIBUTING.md` point here instead of maintaining
parallel copies. Detailed feature contracts remain in the linked documents.

## Project and authority

`sdr-visualizer` is a Python static-output visual catalog generator for Adobe
Customer Journey Analytics (CJA) and Adobe Analytics (AA). It consumes JSON
snapshots from `cja_auto_sdr` / `aa_auto_sdr` and emits one self-contained HTML
report with catalog, reference graph, anatomy, comparison, and trend views.
The package also installs the independent CJA-only `cja-lineage` command.
There are no LLM calls or agent loops in the product.

Read these documents for the area you are changing:

- [Product contract](docs/PRODUCT_CONTRACT.md): supported inputs, stable public
  surfaces, integrity/resource bounds, confidentiality, and compatibility. Read
  before changing public behavior; do not silently expand or weaken the contract.
- [Architecture](docs/ARCHITECTURE.md): data flow, module responsibilities, and
  adding views or platforms.
- [Adapter guide](docs/ADAPTER_GUIDE.md): snapshot shapes and sibling parity.
- [Embedded data format](docs/EMBEDDED_DATA_FORMAT.md) and
  [payload schema](docs/payload-schema.json): catalog payload contract.
- [Workspace usage](docs/WORKSPACE_USAGE.md): optional collection/replay boundaries
  and [usage schema](docs/workspace-usage-schema.json).
- [Lineage](docs/LINEAGE.md): separate discovery input, CLI, and report contract.
- [Performance](docs/PERFORMANCE.md): CI-gated Python and browser budgets.
- [Releasing](docs/RELEASING.md): candidate, publication, and announcement evidence.

## Setup and everyday development

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv). Run from the repo root:

```bash
uv sync --locked --all-extras --dev --group browser
uv run playwright install chromium webkit
uv run pytest
uv run ruff check
uv run ruff format --check
```

The extras install the pinned AA/CJA SDKs for collection tests; base/offline use
only requires Jinja2. The `dev` group supplies Python test/lint tooling and
`browser` supplies Playwright. On Linux, use
`uv run playwright install --with-deps chromium webkit` if browser system libraries
are missing. `tests/conftest.py` generates missing large CJA/AA fixtures on demand.
Do not commit generated performance fixtures or caches.

Use `uv run ruff format` to format changes. Use a focused `uv run pytest tests/test_*.py`
selection while iterating, then complete the PR checks below. Offline CLI smoke:

```bash
uv run sdr-visualizer tests/fixtures/cja_snapshot_clean.json --output /tmp/sdr-visualizer-check.html
uv run sdr-visualizer --help
uv run cja-lineage --help
```

## Validation before a PR

Every PR needs a green suite, clean lint/format, and at least 99% combined line
and branch coverage from the non-browser Python suite. Behavior changes need
focused tests. Run both browser suites with Chromium and WebKit installed;
skipped browser tests do not establish browser validation.

```bash
uv run pytest --ignore=tests/test_browser_functional.py --ignore=tests/test_lineage_browser.py \
  --cov=sdr_visualizer --cov-branch --cov-report=term-missing \
  --cov-report=json --cov-fail-under=99
uv run pytest tests/test_browser_functional.py tests/test_lineage_browser.py -v
uv run ruff check
uv run ruff format --check
uv run python scripts/check_markdown_links.py
uv run python scripts/check_workflow_policy.py
```

The Markdown checker uses Git's tracked-file list. Stage newly added documents
before running it so new links are validated against content that will ship.

When a change could affect build size, rendering, or browser performance, run the
performance gates. Generate their fixture sizes as CI does:

```bash
uv run python scripts/generate_large_fixture.py --scale 0.083 --output tests/fixtures/cja_snapshot_small.json
uv run python scripts/generate_large_fixture.py --scale 0.417 --output tests/fixtures/cja_snapshot_medium.json
uv run python scripts/generate_large_fixture.py
uv run python scripts/generate_aa_large_fixture.py
uv run python scripts/generate_large_fixture.py --scale 1.67 --output tests/fixtures/cja_snapshot_xl.json
uv run python scripts/perf_check.py
uv run python scripts/perf_lineage_poc.py
uv run python scripts/perf_browser_check.py
```

If rendered output changes, run `uv run python scripts/generate_examples.py` and
commit the refreshed `examples/*.html` in the same PR. CI verifies deterministic
example drift and never pushes directly to `main`.

For packaging changes, build and check the independently installed wheel and
source distribution outside the checkout:

```bash
uv build --out-dir dist/packages
uv run python scripts/package_smoke_check.py dist/packages/ --browser
```

Use an output directory containing exactly one wheel and one source distribution.
Keep runtime dependencies limited to imports used by shipped code; tooling-only
dependencies belong in `dev`. The sdist has an explicit allowlist in
`pyproject.toml`; include new public documents there when needed. Release
qualification requires the full [release checklist](docs/RELEASING.md), including
fresh private-corpus/live-generator and explicit-commit sibling evidence; local
fixtures and CI do not substitute for that evidence.

## Architecture and invariants

- Catalog pipeline: `cli/main.py` orchestrates `input/` loading/detection and
  `adapters/` normalization into `core/models.py::Implementation`; `analysis/`
  computes references, anatomy, diff, and trend; `render/data_payload.py`, render
  helpers, Jinja templates, and embedded assets produce the report.
- Lineage uses `cli/lineage.py`, `input/lineage_discovery.py`, `adapters/cja_lineage.py`,
  `core/lineage.py`, `analysis/lineage_layout.py`, and the lineage render modules.
  Its discovery input and internal payload are separate from catalog snapshots.
- Workspace collection uses `cli/workspace_usage.py` and `usage/`; offline replay
  uses `input/workspace_usage.py`. Binding lives in `core/workspace_usage.py` and
  presentation in `render/workspace_usage.py`. Project evidence stays separate
  from component references, graph, diff, and trend.
- Python precomputes analysis and chart geometry. The browser reads embedded JSON,
  filters data, and renders bounded DOM; it does not analyze raw snapshots.
- Reports embed JSON, CSS, JavaScript, and vendored D3: no browser fetches, CDNs,
  application server, or consumer build step. Live exporter invocation and explicit
  optional Python-side Workspace collection follow their documented boundaries;
  saved-input generation and replay stay offline.
- Use vanilla JavaScript, with D3 confined to graph rendering. Do not add a frontend
  framework or new JS dependencies. Preserve lazy initialization and display bounds.
- The visualizer is descriptive: no grades, findings, or recommendations. Those
  belong in [sdr-grader](https://github.com/brian-a-au/sdr-grader).
- Preserve public exit codes: `0` success, `1` runtime failure, `3` invalid input;
  never introduce code `2`. Treat snapshots as untrusted and retain output-alias,
  structure-limit, Unicode, escaping, and non-finite JSON guards.
- Color packs affect HTML presentation only, not the embedded/sidecar payload.

## Sibling parity

The normalized model, `adapters/{base,cja,aa}.py`, and
`input/{loader,detect,shell_out}.py` originated in `sdr-grader`. Shared defensive
behavior must be evaluated and mirrored in the same release cycle; a PR touching
it must explain how parity is met. `input/series.py` is visualizer-only.
When vendoring, rewrite `sdr_grader` imports to `sdr_visualizer`. Fixtures may
intentionally diverge to exercise each project's features.

Read [Vendoring parity with sdr-grader](docs/ADAPTER_GUIDE.md#vendoring-parity-with-sdr-grader)
before syncing: shared coercion helpers stay behavior-identical, while grader-only
evaluative helpers, visualizer numeric coercion, typed-reference metadata, and
output protection have documented intentional differences. Do not copy over
those differences indiscriminately. Color-pack source/accessibility contracts
also require the explicit-SHA comparator described in
[Sibling parity](docs/RELEASING.md#sibling-parity); derived role values are local.

## Contribution and release discipline

Keep changes focused and reviewable; preserve unrelated working-tree changes.
Do not combine correctness, browser performance, automation, documentation, or
community changes merely because they share a release target. Discuss non-trivial
features in an issue first and surface unresolved contract questions there.
Prefer a tighter feature set executed well over unnecessary scope expansion.

Follow [CONTRIBUTING.md](CONTRIBUTING.md), the
[code of conduct](CODE_OF_CONDUCT.md), and the [PR template](.github/PULL_REQUEST_TEMPLATE.md).
PRs should describe resulting behavior, relevant validation, and any parity
obligation. Maintainer self-review is permitted and independent approvals are
currently not required; required checks still apply. Release maintainers
re-inspect repository settings and record evidence before each release.

Never add customer snapshots, identifiers, names, owners, formulas, source paths,
credentials, or private corpus evidence to public commits/issues/PRs. Generated
reports inherit their source's confidentiality. Report vulnerabilities privately
as directed by [SECURITY.md](SECURITY.md). Do not run live collection or read
maintainer credential sources as an unannounced test.

Keep changes under `Unreleased` during development. The release commit bumps
`pyproject.toml`, `src/sdr_visualizer/__init__.py`, and `uv.lock` together. In the
same commit, rename `Unreleased` to the version and release date, add that version's
link definition, update the comparison target, and add a fresh empty `Unreleased`
section. Tag the release commit itself; never tag a commit containing `[skip ci]`.

Follow [RELEASING.md](docs/RELEASING.md) for separately authorized tags, publication,
and announcement gates. PyPI publication precedes the GitHub release; both verify
the same `SHA256SUMS` manifest. If publication succeeds but the GitHub-release job
fails, rerun only the failed `github-release` job against the retained artifact;
never rerun successful publication or republish the same version. A green PR is
not release or announcement authorization.
