# Adapter guide

Adapters take a parsed JSON snapshot from one of the upstream SDR generators and produce a normalized `Implementation` (see `core/models.py`). The visualizer's downstream layers (analysis, render) operate against the normalized model, so they don't need to know which platform produced the snapshot.

This document covers the two adapters shipped in v0.1 and what to do if you want to add a third.

## CJA (`adapters/cja.py`)

Reads the JSON output of [`cja_auto_sdr`](https://github.com/brian-a-au/cja_auto_sdr).

**Top-level shape it expects:**

```json
{
  "metadata": {
    "Data View ID": "...",
    "Data View Name": "...",
    "Generation Timestamp": "...",
    "Tool Version": "..."
  },
  "metrics":     [{...}, ...],
  "dimensions":  [{...}, ...],
  "calculated_metrics": { "metrics": [...] }   // also accepts a bare list
  "segments":           { "segments": [...] }, // also accepts a bare list
  "derived_fields":     { "fields": [...] }
}
```

**What it does:**

- Maps `Data View ID` to `Implementation.instance_id`.
- `cja_auto_sdr` writes a literal `"-"` for missing descriptions; the adapter normalizes those to `None` so the catalog's "Missing description" filter works.
- Calc metric `definition_json` is a JSON-encoded string in the upstream output; the adapter parses it into a dict so `analysis/formula_tree.py` can walk it.
- Segment `container_types` is computed by walking the definition tree and collecting distinct `func: "container"` `context` values (in CJA: `event` / `session` / `person`).
- Calc metrics ship `metric_references` and `segment_references` arrays; the adapter merges these and de-dupes.
- Derived fields appear only in CJA — there's no AA equivalent.

## AA (`adapters/aa.py`)

Reads the JSON output of [`aa_auto_sdr`](https://github.com/brian-a-au/aa_auto_sdr).

**Top-level shape it expects:**

```json
{
  "report_suite": {"rsid": "...", "name": "..."},
  "tool_version": "...",
  "captured_at":  "...",
  "dimensions":         [{...}, ...],   // eVars and props live here
  "metrics":            [{...}, ...],   // success events
  "calculated_metrics": [{...}, ...],
  "segments":           [{...}, ...],
  "classifications":    [{...}, ...],
  "virtual_report_suites": [...]
}
```

**Vocabulary mapping:**

| AA term | Normalized model |
|---|---|
| Report suite ID (`rsid`) | `Implementation.instance_id` |
| eVars | `dimensions` (with `platform_specific.allocation` / `expiration`) |
| Props | `dimensions` (with prop-specific flags in `platform_specific`) |
| Events | `metrics` |
| Classifications | tags on the parent dimension |
| Container contexts | `hits` / `visits` / `visitors` (rather than CJA's `event` / `session` / `person`) |

**Notes:**

- AA has no derived-field equivalent; `Implementation.derived_fields` is always `[]` for AA snapshots.
- AA segment definitions can mix containers under different contexts. The adapter walks the full definition tree to compute `nesting_depth` and the distinct set of `container_types`.
- AA calc-metric formulas use `args: [...]` (a flat list) rather than the CJA `col1` / `col2` pair. `analysis/formula_tree.py` handles both shapes.

## Adding a new platform

The visualizer is single-platform-per-snapshot, but the architecture doesn't preclude adding new ones. If you want to point it at a different analytics tool (GA4, Amplitude, ...):

1. Write `adapters/<name>.py` exposing `adapt(snapshot, *, source) -> Implementation`. Stick with the `core/models.py` field set; if your platform has concepts that don't fit, stash them under `Component.platform_specific` rather than extending the model.
2. Add a detection branch to `input/detect.py` that recognizes the new shape from a top-level key.
3. Wire the new branch into `core/visualizer.py:build_implementation` so `--platform <name>` reaches the adapter.
4. Drop sample fixtures into `tests/fixtures/`. At minimum: a clean snapshot that the catalog can render without complaint, and a messy one with several edge cases.
5. Mirror the existing tests (`tests/test_adapters_<name>.py`) round-tripping every field.

The downstream layers need no changes — `analysis/`, `render/`, the catalog UI, and the graph view all work against the normalized model.

The fixtures may diverge from sdr-grader's over time — the visualizer wants more component variety to exercise rendering; the grader wants more rule-triggering edge cases — but the model contract is shared between projects per [`SPEC-VISUALIZER.md`](../SPEC-VISUALIZER.md) §11.

## Vendoring parity with sdr-grader

`adapters/{cja,aa}.py` are vendored from [`sdr-grader`](https://github.com/brian-a-au/sdr-grader) per SPEC §11/§15. They are **not** byte-identical copies, and shouldn't be assumed to be — but the *defensive coercion* of untrusted snapshot fields is a shared class that must stay in sync. When you touch it, mirror the change to the sibling in the same cycle.

**Shared, behavior-identical (keep in sync):**

- `_parse_tag_list` / `_parse_ref_list` — parse `tags` and reference fields that `cja_auto_sdr` ships as JSON-encoded list strings (`'["a"]'`), tolerating native lists and dropping anything unparseable to `[]`.
- `_optional_list` (AA) — an absent/null optional section is `[]`, but a present non-list value raises `InvalidSnapshotError` (a malformed export, not an empty one). CJA gets the same guarantee through `_section_records`.
- `generator_version_warning` / `_version_tuple` / `TESTED_THROUGH_GENERATOR_VERSION` — the Q5 version-compat warning mechanism (1.0.0). The helper bodies are behavior-identical; the constant's *value* is per-platform and per-release by design (the newest generator version that release was validated against).

**Grader-only (do not port — evaluative, not descriptive):** the grader carries logic that exists only to serve its grading rules — governance signals (`_governance_approved`, `_governance_shared_to_count`, `_normalize_owner`, `_aa_governance_signals`) and inline-echo de-duplication (`_echoes_derived_field`, which drops a metric/dimension that merely re-declares a derived field so rule SCH-001 doesn't false-fire on the duplicate name). The visualizer describes rather than grades: it keeps such echoes and instead warns on duplicate component ids (last-writer-wins for anatomy), so it never adopts these helpers.

**Visualizer-only numeric coercion — intentional divergence, do NOT reconcile to the grader:** `_as_float` / `_as_int` are the visualizer's variant of the grader's tolerant `_safe_float` / `_safe_int`. Two deltas, both driven by visualizer-only features:

1. A present-but-unconvertible numeric **raises** `InvalidSnapshotError` (the grader defaults). Trend mode relies on the raise to *skip* a malformed snapshot rather than chart a fabricated value; a single snapshot exits 3.
2. `NaN` / `Infinity` **pass through** to the renderer's `allow_nan=False` guard, which rejects the whole report (audit H2). The grader coerces them to a default. A visualizer report that embeds `NaN` cannot boot in a browser, so rejecting loudly beats substituting `0.0`.

These deltas are pinned by `test_nan_snapshot_exits_3`, `test_nan_in_snapshot_raises_invalid_snapshot_error`, and the trend bad-scalar skip test — a sync that "fixes" the divergence will fail them.
