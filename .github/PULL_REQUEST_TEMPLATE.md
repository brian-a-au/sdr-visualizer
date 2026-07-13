## Summary

<!-- What does this PR do, in 1-3 sentences? -->

## Type of change

- [ ] Bug fix
- [ ] Feature (agreed in an issue first for anything non-trivial)
- [ ] Docs / examples / CI
- [ ] Other (describe)

## Invariant check

Non-negotiable per CONTRIBUTING.md. Confirm:

- [ ] No network fetches, CDNs, or new JS dependencies introduced
- [ ] No JS framework; D3 stays confined to the graph view
- [ ] Output stays descriptive — no grades, scores, or judgments
- [ ] Perf budgets respected (`scripts/perf_check.py` / `perf_browser_check.py` green if plausibly affected)
- [ ] Vendored files (`adapters/*`, `input/{loader,detect,shell_out}.py`) untouched — or the sdr-grader parity plan is stated below

## Tests

- [ ] `uv run pytest` passes locally (browser tests running, not skipped)
- [ ] `uv run ruff check` and `uv run ruff format --check` pass

## Notes for the reviewer

<!-- Anything non-obvious: a subtle invariant relied on, a fixture that
needed updating, a follow-up you intend to file. -->
