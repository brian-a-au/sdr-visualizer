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
