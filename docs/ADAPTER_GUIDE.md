# Adapter guide

Adapters take a parsed JSON snapshot from one of the upstream SDR generators and produce a normalized `Implementation` (see `core/models.py`). Most analysis and rendering code operates against that normalized model. Adding a platform still requires updating every dispatch, public-contract, payload, UI, and test seam listed below.

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
  "metrics": [{"id": "metrics/orders", "name": "Orders"}],
  "dimensions": [{"id": "variables/page", "name": "Page"}],
  "calculated_metrics": {"metrics": []},
  "segments": {"segments": []},
  "derived_fields": {"fields": []}
}
```

`calculated_metrics` and `segments` also accept bare lists.

**What it does:**

- Maps `Data View ID` to `Implementation.instance_id`.
- `cja_auto_sdr` writes a literal `"-"` for missing descriptions; the adapter normalizes those to `None` so the catalog's "Missing description" filter works.
- Calc metric `definition_json` is a JSON-encoded string in the upstream output; the adapter parses it into a dict so `analysis/formula_tree.py` can walk it.
- Segment `container_types` is computed by walking the definition tree and collecting distinct `func: "container"` `context` values (in CJA: `event` / `session` / `person`).
- Calc metrics ship `metric_references` and `segment_references` arrays; the adapter merges these and de-dupes.
- Derived fields appear only in CJA — there's no AA equivalent.

### CJA component mappings

| CJA input | Normalized collection | Embedded type |
|---|---|---|
| `metrics` | `Implementation.metrics` | `metric` |
| `dimensions` | `Implementation.dimensions` | `dimension` |
| `derived_fields.fields` | `Implementation.derived_fields` | `derived_field` |
| `segments.segments` | `Implementation.segments` | `segment` |
| `calculated_metrics.metrics` | `Implementation.calculated_metrics` | `calculated_metric` |

Derived-field `component_references` are normalized into reference edges when
the target exists. A declared CJA derived-field kind may become the optional
embedded `derived_kind`; other adapter-only details stay internal.

## AA (`adapters/aa.py`)

Reads the JSON output of [`aa_auto_sdr`](https://github.com/brian-a-au/aa_auto_sdr).

**Top-level shape it expects:**

```json
{
  "report_suite": {"rsid": "...", "name": "..."},
  "tool_version": "...",
  "captured_at":  "...",
  "dimensions": [{"id": "variables/evar1", "name": "Site Section"}],
  "metrics": [{"id": "metrics/event1", "name": "Orders"}],
  "calculated_metrics": [],
  "segments": [],
  "classifications": [],
  "virtual_report_suites": []
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

The visualizer currently accepts one platform per snapshot. Supporting another
analytics tool is a cross-cutting feature, not just a new adapter:

1. Extend the platform type and normalized fields in `core/models.py`, then add
   `adapters/<name>.py` with `adapt(snapshot, *, source) -> Implementation`.
2. Add unambiguous shape recognition in `input/detect.py` and adapter dispatch
   in `core/visualizer.py`.
3. Add the public `--platform` choice and relevant live-mode or compatibility
   warning routing in `cli/main.py`.
4. Review `docs/payload-schema.json` and `render/data_payload.py`. Normalized
   fields intended for consumers need an explicit schema and payload mapping.
   `Component.platform_specific` is adapter-working data:
   **platform_specific is not embedded** in reports or `--json` output. Keep
   unsupported platform extras in the original snapshot rather than promising
   them to payload consumers.
5. Review labels, filters, and platform-specific assumptions in
   `render/static/visualizer.js` and the surrounding report UI. Generic code
   may need no edit, but that conclusion must come from an exercised review.
6. Add clean, messy, invalid, ambiguous-detection, CLI, schema/payload, and
   browser fixtures under `tests/fixtures/`. Mirror the adapter coverage in
   `tests/test_adapters_<name>.py` and extend detection, CLI, payload-schema,
   and browser tests.

Use the existing model where it describes the new platform accurately. Do not
put a consumer-facing concept only in `platform_specific`, because that field
is deliberately omitted at the payload boundary.

The fixtures may diverge from sdr-grader's over time — the visualizer wants more component variety to exercise rendering; the grader wants more rule-triggering edge cases — but shared defensive behavior follows the parity policy in [`PRODUCT_CONTRACT.md`](PRODUCT_CONTRACT.md#compatibility-policy).

## Vendoring parity with sdr-grader

`adapters/{cja,aa}.py` originated in [`sdr-grader`](https://github.com/brian-a-au/sdr-grader). They are **not** byte-identical copies, and shouldn't be assumed to be — but the *defensive coercion* of untrusted snapshot fields is a shared class that must stay in sync. When you touch it, mirror the change to the sibling in the same cycle and record the evidence required by [`RELEASING.md`](RELEASING.md#sibling-parity).

**Shared, behavior-identical (keep in sync):**

- `input.loader.list_snapshot_candidates` — owns sorted `*.json` directory
  discovery for both ordinary directory selection and trend enumeration. It
  returns every candidate before later timestamp, parseability, platform, or
  window-cap filtering (including an empty list for an empty directory) and
  maps discovery failures to `InvalidSnapshotError`.
  The grader mirrors this loader primitive even though it has no trend mode.
- `_parse_tag_list` / `_parse_ref_list` — parse `tags` and reference fields
  that `cja_auto_sdr` ships as JSON-encoded list strings (`'["a"]'`) while
  tolerating native lists. Ordinary JSON syntax failures drop to `[]`;
  decoder resource failures raise `InvalidSnapshotError`. Every successful
  decode is limited to depth 100 and 10,000 nodes before shape fallback or
  coercion; this decoded-structure guard is part of the required sibling
  parity behavior.
- Snapshot structure validation rejects surrogate code points in string values
  and mapping keys before normalization. Embedded definition, tag, and
  reference helpers repeat that Unicode-scalar check after decoding, when
  escaped surrogates first materialize.
- `_optional_list` (AA) — an absent/null optional section is `[]`, but a present non-list value raises `InvalidSnapshotError` (a malformed export, not an empty one). CJA gets the same guarantee through `_section_records`.
- `generator_version_warning` / `_version_tuple` / `TESTED_THROUGH_GENERATOR_VERSION` — the Q5 version-compat warning mechanism (1.0.0). The helper bodies are behavior-identical; the constant's *value* is per-platform and per-release by design (the newest generator version that release was validated against).
- `_optional_timestamp` — guards `created_at`/`modified_at`: keeps the value only if it's already a non-empty string, else `None`, so `_compact` drops a non-string timestamp (an epoch int, say) instead of leaking it into the payload. Present in both `cja.py` and `aa.py` here, and mirrored into the grader's copies of both adapters — a non-string timestamp is *missing*, not a value worth coercing to a numeric string.
- `_optional_str` (CJA only) — guards `owner` and the derived-field `data_type` at the CJA record builders that previously passed them straight through unguarded (`str(x) if x else None`, the same pattern the metric/dimension `data_type` path already used). No grader-side mirror needed for `owner`: the grader's `_normalize_owner` (governance helper, see below) already reduces a non-string owner to `None` — a different mechanism, the same outcome — so grader `owner` needs no additional guard. AA needs no `_optional_str` mirror either: its three `owner_id` builder sites and its one `data_type` site were already cast (`str(x) if x else None`) before this cycle.

**Grader-only (do not port — evaluative, not descriptive):** the grader carries logic that exists only to serve its grading rules — governance signals (`_governance_approved`, `_governance_shared_to_count`, `_normalize_owner`, `_aa_governance_signals`) and inline-echo de-duplication (`_echoes_derived_field`, which drops a metric/dimension that merely re-declares a derived field so rule SCH-001 doesn't false-fire on the duplicate name). The visualizer describes rather than grades: it keeps such echoes and instead warns on duplicate component ids (last-writer-wins for anatomy), so it never adopts these helpers.

**Visualizer-only numeric coercion — intentional divergence, do NOT reconcile to the grader:** `_as_float` / `_as_int` are the visualizer's variant of the grader's tolerant `_safe_float` / `_safe_int`. Two deltas, both driven by visualizer-only features:

1. A present-but-unconvertible numeric **raises** `InvalidSnapshotError` (the grader defaults). Trend mode relies on the raise to *skip* a malformed snapshot rather than chart a fabricated value; a single snapshot exits 3.
2. `NaN` / `Infinity` **pass through** to the renderer's `allow_nan=False` guard, which rejects the whole report (audit H2). The grader coerces them to a default. A visualizer report that embeds `NaN` cannot boot in a browser, so rejecting loudly beats substituting `0.0`.

These deltas are pinned by `test_nan_snapshot_exits_3`, `test_nan_in_snapshot_raises_invalid_snapshot_error`, and the trend bad-scalar skip test — a sync that "fixes" the divergence will fail them.

**Visualizer-only output protection — do not port to the grader:** before its
first write, the visualizer compares both HTML and optional JSON destinations
with every explicit snapshot and every directory candidate. Resolved paths and
existing-file identity catch lexical aliases, symlinks, symlinked parents, and
hard links. The grader does not produce these report artifacts, so only the
shared candidate-listing primitive belongs in its parity surface.
