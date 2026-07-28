# Embedded data format

Every HTML output contains a JSON payload in `<script id="sdr-data" type="application/json">…</script>`. Client-side JS reads it on load to drive every view; downstream tooling can also consume it directly via `--json PATH`.

The payload is a stable contract: external tooling can rely on the keys
documented below. Internal, undocumented keys may change without notice. See
[`PRODUCT_CONTRACT.md`](PRODUCT_CONTRACT.md#stable-public-surfaces) for the
versioning boundary and confidentiality warning.

## Top-level shape

```jsonc
{
  "meta":              { ... },
  "components":        [ ... ],     // metrics + dimensions + derived fields
  "segments":          [ ... ],
  "calculated_metrics": [ ... ],
  "graph":             { "edges": [...] },
  "segment_trees":     { "<id>": SegmentTreeNode },
  "formula_trees":     { "<id>": FormulaTreeNode },
  "changes":           { ... },     // only with --compare-to
  "trend":             { ... }      // only with --trend
}
```

> **Sparse encoding (0.2.0+):** fields whose value is `null`, `""`, `[]`, or `{}` are omitted from entries. Consumers must treat a missing key as that empty value. Numeric zeros (`in_degree`, `complexity_score`) are always present.

## `meta`

```jsonc
{
  "instance_id":           "dv_prod_web",
  "instance_name":         "Production Web Analytics",
  "platform":              "cja" | "aa",
  "snapshot_taken_at":     "2026-04-25 09:14:00" | null,
  "snapshot_source":       "/path/to/snapshot.json" | "stdin" | "shell-out:cja_auto_sdr dv_x",
  "adapter_version":       "3.5.17",
  "visualizer_version":    "0.2.0",
  "generated_at":          "2026-04-25T09:14:00Z",
  "component_count":       487,
  "exclude_orphans_default": false,
  "max_graph_nodes":       1000,       // only present when --max-graph-nodes was passed
  "compared_to": {                     // only present with --compare-to
    "source": "/path/to/baseline.json",
    "taken_at": "2026-04-20 09:14:00" | null,
    "instance_id": "dv_prod_web"
  }
}
```

## `components` (one entry per metric / dimension / derived field)

```jsonc
{
  "id":              "metrics/cm_metric_001",
  "type":            "metric" | "dimension" | "derived_field",
  "name":            "Sessions",
  "description":     "Distinct sessions in the period.",          // omitted when absent
  "data_type":       "integer" | "decimal" | "string",           // omitted when absent
  "polarity":        "positive" | "negative" | "neutral",        // omitted when absent
  "tags":            ["custom", "approved"],
  "owner":           "a.user@example.com",                       // omitted when absent
  "created_at":      "2025-09-01T00:00:00Z",                    // omitted when absent
  "modified_at":     "2026-04-25T09:14:00Z",                    // omitted when absent
  "modified_ts":     1777108440000,                              // epoch ms; omitted when absent
  "in_degree":       8,                                          // how many things reference this
  "out_degree":      0
}
```

*`platform_specific` was removed in 0.2.0 — consult the original snapshot for platform extras.*

## `segments`

```jsonc
{
  "id":               "segments/seg_qualified_lead_v3",
  "type":             "segment",
  "name":             "Qualified Lead v3",
  "description":      "Leads who completed evaluation step.",
  "nesting_depth":    8,
  "container_types":  ["event", "session", "person"],   // CJA; ["hits","visits","visitors"] for AA
  "references":       ["variables/evar1", "metrics/cm_metric_001"],
  "owner":            "a.user@example.com",                      // omitted when absent
  "created_at":       "...",
  "modified_at":      "...",
  "modified_ts":      1777108440000,                              // epoch ms; omitted when absent
  "in_degree":        2,
  "out_degree":       2
}
```

## `calculated_metrics`

```jsonc
{
  "id":                 "calculatedMetrics/cm_revenue_per_visit",
  "type":               "calculated_metric",
  "name":               "Revenue per Visit",
  "description":        "...",
  "formula_text":       "Revenue / Visits",
  "attribution_model":  "last-touch",                            // omitted when absent
  "allocation":         "linear",                                // omitted when absent
  "complexity_score":   42.0,
  "references":         ["metrics/revenue", "metrics/visits"],
  "owner":              "...",
  "created_at":         "...",
  "modified_at":        "...",
  "modified_ts":        1777108440000,                            // epoch ms; omitted when absent
  "in_degree":          0,
  "out_degree":         2
}
```

## `graph`

```jsonc
{
  "edges":  [ { "source": "<id>", "target": "<id>", "kind": "references" }, ... ]
}
```

> Edges are directed (source → target) and only emitted when the target exists in the inventory. CJA derived-field `component_references` contribute edges after adapter normalization, alongside segment and calculated-metric references. Dangling segment and calculated-metric references remain visible on the source entry's `references` array but are not included in `graph.edges`; derived-field dangles remain available only in the original snapshot because `platform_specific` is not embedded. Graph *nodes* are derivable from the catalog entries (`id`, `type`, `name`, `in_degree`) — the client builds them in one pass at load; `in_degree`/`out_degree` live on each entry. The separate `nodes`/`in_degree`/`out_degree` sections were removed in 0.2.0.

## `changes`

Present only with `--compare-to`. The baseline reference accepts a missing
snapshot timestamp, represented as `null` in both `changes.baseline.taken_at`
and `meta.compared_to.taken_at`:

```jsonc
{
  "baseline": {
    "source": "/path/to/baseline.json",
    "taken_at": null,
    "instance_id": "dv_prod_web"
  },
  "added": [],
  "removed": [],
  "modified": []
}
```

`added` and `removed` entries contain `id`, `type`, and `name`. A `modified`
entry also contains `fields`, an array of `{field, before, after}` records.
Only the baseline reference and change summaries are embedded; the full
baseline snapshot is not.

## `trend`

Present only with `--trend`. Snapshots are ordered oldest to newest and capped
at the 60 newest usable selected snapshots. `capped` is true only when a 61st
usable selected snapshot exists.

```jsonc
{
  "capped": false,
  "snapshots": [
    {
      "source": "/path/to/snapshot.json",
      "taken_at": "2026-04-25 09:14:00" | null,
      "aggregates": {
        "total": 487,
        "metrics": 120,
        "dimensions": 210,
        "derived_fields": 12,
        "segments": 80,
        "calculated_metrics": 65,
        "orphans": 44,
        "no_description": 31,
        "edges": 506
      }
    }
  ],
  "intervals": [
    {
      "from": "2026-04-24 09:14:00",
      "to": "2026-04-25 09:14:00",
      "from_source": "snapshot-2026-04-24.json",
      "to_source": "snapshot-2026-04-25.json",
      "added": ["metrics/new_metric"],
      "removed": [],
      "modified": ["segments/changed_segment"]
    }
  ]
}
```

Each interval is a diff of adjacent snapshots. Its three change arrays contain
component IDs only; the browser materializes those IDs lazily when the interval
is expanded.

## Search index

Removed in 0.2.0. The client builds a lowercased per-entry search blob
(`id + name + description + formula_text + tags`) in one pass at load —
shipping it doubled the textual payload.

## `segment_trees`

Each segment's parsed definition. Node `kind`s:

```jsonc
// container — a nesting box scoped to a context
{ "kind": "container", "context": "event", "child": Node }

// logical — and / or / not / without
{ "kind": "logical", "op": "and", "children": [Node, ...] }

// criterion — a leaf comparison
{
  "kind": "criterion",
  "op": "streq" | "eq" | "gt" | "...",
  "target_id": "variables/evar1" | null,
  "target_label": "variables/evar1",
  "value": "match" | 42 | null,
  "refs": ["variables/evar1"],
  "summary": "variables/evar1 equals 'match'"
}

// segment_ref — inline reference to another segment
{ "kind": "segment_ref", "segment_id": "segments/seg_x" }

// unknown — fallback for shapes the parser doesn't recognize yet
{ "kind": "unknown", "func": "exotic-op", "raw_keys": ["foo", "bar"] }
```

## `formula_trees`

Each calculated metric's parsed formula. Node `kind`s:

```jsonc
// operation — divide / multiply / subtract / add / sum / ...
{ "kind": "operation", "op": "divide", "args": [Node, Node] }

// metric_ref — leaf metric reference
{ "kind": "metric_ref", "metric_id": "metrics/revenue", "label": "metrics/revenue" }

// constant — numeric or string literal
{ "kind": "constant", "value": 100 }

// segment_scope — formula scoped to a segment
{ "kind": "segment_scope", "segment_id": "segments/seg_x", "child": Node }

// unknown — fallback
{ "kind": "unknown", "func": "exotic-op", "raw_keys": ["..."] }
```

## Stability

- The keys documented above are stable. Renaming or removing them is a breaking change that bumps the leftmost non-zero version (the major version once 1.0+).
- Adding new keys is non-breaking — consumers should ignore unknown keys.
- The exact shape of `unknown` tree nodes is intentionally loose; consumers should use them defensively.
- 0.2.0 removed `catalog_index`, `graph.nodes`, `graph.in_degree`, `graph.out_degree`, and `platform_specific`, and introduced sparse encoding — a breaking change per the policy above (leftmost non-zero version bumped).
- The embedded `sdr-data` block escapes `<` as the JSON unicode escape `\u003c` (transparent to `JSON.parse`); the `--json PATH` output is plain unescaped JSON — byte-level comparisons between the two will differ.
