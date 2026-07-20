# Contributing to sdr-visualizer

Thanks for your interest. This project has a deliberately tight scope and a
few non-negotiable architectural rules; reading this first will save you a
review round-trip.

## The rules of the road

These are settled decisions (see the spec history), not open questions:

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
uv run python scripts/perf_check.py           # build/size budgets
uv run python scripts/perf_browser_check.py   # browser budgets
```

Every PR needs: tests for behavior changes, a green suite, clean
`ruff check` and `ruff format --check`, at least 99% combined line-and-branch
coverage from the non-browser Python suite, and green browser/perf gates when
the change could plausibly affect them.

## Releases (maintainer notes)

The release commit bumps `pyproject.toml`, `src/sdr_visualizer/__init__.py`,
and `uv.lock` together, dates the CHANGELOG's Unreleased section, and adds
the version's link definition at the bottom of the file. Tag the release
commit itself — never a commit whose message contains `[skip ci]` (the
examples auto-commits), because GitHub skips all workflows for such a tag.
Do not commit locally generated `examples/*.html`; CI regenerates them.
