# Contributing to sdr-visualizer

Thanks for your interest. This project has a deliberately tight scope and a
few non-negotiable architectural rules; reading this first will save you a
review round-trip. By participating, you agree to follow the
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

## The rules of the road

These are settled decisions in the
[`product contract`](docs/PRODUCT_CONTRACT.md), not open questions:

- **Static output, dynamic interaction.** The tool emits one self-contained
  HTML file: embedded JSON, embedded CSS, embedded JS. No fetches, no CDNs,
  no server, no build step for the consumer.
- **Server-side build, client-side render.** Analysis work happens in
  Python, where seconds are fine. The client reads, filters, and renders
  against a millisecond budget.
- **Vanilla JS.** D3 for the reference graph only. No frameworks, no new
  JS dependencies.
- **Descriptive, not evaluative.** The visualizer reports what an
  implementation contains and how it changed — never whether that is good
  or bad. Grading belongs in the sibling project,
  [sdr-grader](https://github.com/brian-a-au/sdr-grader).
- **Performance budgets are CI-gated.** `docs/PERFORMANCE.md` documents
  them. A change that blows a budget fails CI regardless of its merits.
- **Exit codes are 0 / 1 / 3.** 0 success, 1 runtime error, 3 invalid
  input. Code 2 is never used.

## The vendoring relationship

`src/sdr_visualizer/adapters/*` and `src/sdr_visualizer/input/{loader,detect,shell_out}.py`
are vendored from sdr-grader, and the `core/models.py` shapes are shared.
Any behavioral change to those files must be mirrored to the sibling repo in
the same cycle — a PR that changes them should say how the parity obligation
is being met. `input/series.py` is visualizer-only and exempt.

## Developing

```bash
uv sync --dev --group browser    # environment
uv run playwright install chromium webkit
uv run pytest                    # tests (includes browser tests)
uv run pytest --ignore=tests/test_browser_functional.py --cov=sdr_visualizer --cov-branch --cov-report=term-missing --cov-report=json --cov-fail-under=99  # Python coverage gate
uv run ruff check                # lint
uv run ruff format               # format (the repo is format-clean)
uv run python scripts/check_markdown_links.py
uv run python scripts/perf_check.py           # build/size budgets
uv run python scripts/perf_browser_check.py   # browser budgets
uv run python scripts/check_workflow_policy.py
uv build
uv run python scripts/package_smoke_check.py dist/  # isolated wheel + sdist installs
```

Every PR needs: tests for behavior changes, a green suite, clean
`ruff check` and `ruff format --check`, at least 99% combined line-and-branch
coverage from the non-browser Python suite, and green browser/perf gates when
the change could plausibly affect them.

Release artifacts are not considered usable merely because `uv build`
succeeds. The package smoke check installs the wheel and source distribution
independently into temporary environments outside the checkout, then verifies
import/version metadata, the console entry point, `--help`, and an offline
render. Keep runtime dependencies limited to imports used by shipped package
code; tooling-only dependencies belong in the `dev` group.

If your change affects rendered output, run
`uv run python scripts/generate_examples.py` and commit the refreshed
`examples/*.html` files in the same PR. CI checks deterministic drift and
never pushes directly to `main`, so branch protection has no automation
bypass.

## Releases (maintainer notes)

Use the full candidate and publication checklist in
[`docs/RELEASING.md`](docs/RELEASING.md).

Keep changes under `Unreleased` while they are in development. The release
commit bumps `pyproject.toml`, `src/sdr_visualizer/__init__.py`, and `uv.lock`
together. In the same commit, rename `Unreleased` to the version and release date,
add that version's link definition, update the comparison target, and add a
fresh empty `Unreleased` section. Tag the release
commit itself — never a commit whose message contains `[skip ci]` (the
examples auto-commits), because GitHub skips all workflows for such a tag.
The release workflow publishes to PyPI before creating the GitHub release and
both stages verify the same `SHA256SUMS` manifest. If PyPI succeeds but the
final GitHub-release job fails, rerun only the failed `github-release` job
against the retained artifact. Never rerun the successful publish job or try
to republish the same version to PyPI.
