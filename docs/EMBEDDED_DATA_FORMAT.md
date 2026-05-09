# Embedded data format

Every HTML output contains a JSON payload in `<script id="sdr-data" type="application/json">…</script>`. Client-side JS reads it on load to drive every view; downstream tooling can also consume it directly via `--json PATH`.

The payload is a stable contract: external tooling can rely on the keys documented below. Internal, undocumented keys may change without notice.

## Top-level shape

```jsonc
{
  "meta":              { ... },
  "components":        [ ... ],     // metrics + dimensions + derived fields
  "segments":          [ ... ],
  "calculated_metrics": [ ... ],
  "graph":             { "nodes": [...], "edges": [...], "in_degree": {...}, "out_degree": {...} },
  "catalog_index":     { "by_id": { "<id>": { search, type, tags } } },
  "segment_trees":     { "<id>": SegmentTreeNode },
  "formula_trees":     { "<id>": FormulaTreeNode }
}
```

## `meta`

```jsonc
{
  "instance_id":           "dv_prod_web",
  "instance_name":         "Production Web Analytics",
  "platform":              "cja" | "aa",
  "snapshot_taken_at":     "2026-04-25 09:14:00" | null,
  "snapshot_source":       "/path/to/snapshot.json" | "stdin" | "shell-out:cja_auto_sdr dv_x",
  "adapter_version":       "3.5.17",
  "visualizer_version":    "0.1.0",
  "generated_at":          "2026-04-25T09:14:00Z",
  "component_count":       487,
  "exclude_orphans_default": false,
  "max_graph_nodes":       1000        // only present when --max-graph-nodes was passed
}
```

## `components` (one entry per metric / dimension / derived field)

```jsonc
{
  "id":              "metrics/cm_metric_001",
  "type":            "metric" | "dimension" | "derived_field",
  "name":            "Sessions",
  "description":     "Distinct sessions in the period." | null,
  "data_type":       "integer" | "decimal" | "string" | null,
  "polarity":        "positive" | "negative" | "neutral" | null,
  "tags":            ["custom", "approved"],
  "owner":           "a.user@example.com" | null,
  "created_at":      "2025-09-01T00:00:00Z" | null,
  "modified_at":     "2026-04-25T09:14:00Z" | null,
  "in_degree":       8,                                          // how many things reference this
  "out_degree":      0,
  "platform_specific": { /* CJA: precision, AA: allocation/expiration, etc. */ }
}
```

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
  "tags":             [],
  "owner":            "a.user@example.com" | null,
  "created_at":       "...",
  "modified_at":      "...",
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
  "attribution_model":  "last-touch" | null,
  "allocation":         "linear" | null,
  "complexity_score":   42.0,
  "references":         ["metrics/revenue", "metrics/visits"],
  "tags":               [],
  "owner":              "...",
  "created_at":         "...",
  "modified_at":        "...",
  "in_degree":          0,
  "out_degree":         2
}
```

## `graph`

```jsonc
{
  "nodes":  [ { "id": "...", "type": "metric", "label": "Sessions" }, ... ],
  "edges":  [ { "source": "<id>", "target": "<id>", "kind": "references" }, ... ],
  "in_degree":  { "<id>": <int>, ... },
  "out_degree": { "<id>": <int>, ... }
}
```

Edges are directed (source → target) and only emitted when the target exists in the inventory. Dangling references (e.g. a calc metric referencing `metrics/revenue` when `metrics/revenue` isn't in the snapshot) are visible on the source entry's `references` array but not in `graph.edges`.

## `catalog_index.by_id`

Per-component fast-search index. The `search` field is a lowercased blob containing `id + name + description + formula_text + tags` so the client can do plain `indexOf()` substring matching.

```jsonc
{
  "<id>": {
    "search":  "metrics/cm_metric_001 sessions distinct sessions in the period.",
    "type":    "metric",
    "tags":    ["custom"]
  }
}
```

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

- The keys documented above are stable. Renaming or removing them is a breaking change that bumps the major version.
- Adding new keys is non-breaking — consumers should ignore unknown keys.
- The exact shape of `platform_specific` and `unknown` nodes is intentionally loose; consumers should use them defensively.
