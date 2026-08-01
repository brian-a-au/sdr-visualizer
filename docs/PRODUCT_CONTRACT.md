# Product contract

This document is the tracked public contract for `sdr-visualizer`. It defines
what the project promises, what it deliberately does not promise, and which
surfaces require semantic-versioning discipline.

## Purpose and scope

`sdr-visualizer` turns Adobe Customer Journey Analytics (CJA) and Adobe
Analytics (AA) SDR snapshots into a self-contained HTML catalog. The report
describes an implementation through a searchable catalog, reference graph,
segment and calculated-metric anatomy, snapshot comparison, and time-series
trend views.

The visualizer is descriptive, not evaluative. It does not grade an
implementation, prescribe changes, host reports, authenticate viewers, or send
snapshot data to an external service. Evaluation belongs in
[`sdr-grader`](https://github.com/brian-a-au/sdr-grader).

## Input contract

Exactly one input source is required:

- a JSON snapshot file;
- a directory of JSON snapshots;
- standard input (`-`);
- live CJA inventory through `--dataview`; or
- live AA inventory through `--rsid`.

CJA and AA auto-detection is based on the top-level snapshot shape.
`--platform cja|aa` can resolve an ambiguous file or select one platform from a
mixed trend directory. Live mode fixes the platform itself.

A directory normally selects its newest timestamped snapshot. `--at` selects
the newest snapshot at or before an ISO-8601 cutoff using UTC-consistent
comparison. In a directory that mixes timestamped and untimestamped filenames,
the untimestamped files are skipped with a warning; when no filenames carry a
timestamp, filesystem modification time is used. Ordinary directory mode
loads the one selected file and reports it as invalid if it is corrupt.
`--trend` instead scans past corrupt or unusable candidates with warnings until
it fills the selected-platform window.

`--compare-to` requires the same platform and, by default, the same data view
or report suite. `--trend` likewise requires one platform and one
implementation. `--allow-instance-mismatch` opts into a cross-instance compare
or trend with a warning; a platform mismatch is always rejected.

Trend selection keeps at most the 60 newest usable snapshots after platform
selection. The report records that it was capped only when a 61st usable
selected snapshot exists.

## Output and confidentiality

The primary output is one HTML file with JSON, CSS, JavaScript, and vendored D3
embedded in it. It makes no network requests and needs no report server, CDN,
or client-side build step. `--json PATH` can also write the same logical
payload as a JSON sidecar.

Offline is a transport property, not a confidentiality classification.
Generated reports can contain implementation names, component names and
descriptions, segment and calculated-metric logic, owners, identifiers,
timestamps, and source paths. Treat each report as derived from its source
snapshot. Share, email, post, or attach it only in locations and with people
allowed by the applicable organizational data-handling policy.

## Stable public surfaces

For releases at or above 1.0.0, semantic versioning covers:

- the documented CLI arguments and their meanings;
- exit codes `0` (success), `1` (runtime failure), and `3` (invalid input);
- the documented embedded/sidecar payload in
  [`EMBEDDED_DATA_FORMAT.md`](EMBEDDED_DATA_FORMAT.md) and
  [`payload-schema.json`](payload-schema.json); and
- the budgets in [`PERFORMANCE.md`](PERFORMANCE.md).

Removing or repurposing a documented argument, removing or retyping a payload
field, or loosening a published performance budget is a breaking change.
Adding an optional argument or payload field is normally additive. Consumers
must ignore unknown payload keys and treat documented sparse fields as absent
empty values.

Templates, CSS class names, internal Python modules, JavaScript helper names,
warning wording, and undocumented payload details are internal unless another
public document explicitly says otherwise.

## Integrity and resource bounds

Snapshots are untrusted input. Before recursive processing, the visualizer
enforces these implementation limits:

| Limit | Current bound |
|---|---:|
| Native snapshot or decoded embedded value nesting depth | 100 |
| Native snapshot scalar/container nodes | 250,000 |
| Each segment/formula definition or decoded tag/reference value | 10,000 nodes |

Limit violations are invalid input and produce exit `3` without an output
artifact. Default filenames sanitize instance identifiers to prevent path and
terminal-control injection. `--max-graph-nodes` accepts zero or a positive
integer; negative values are invalid.

All snapshot-controlled string values and mapping keys must contain Unicode
scalar values; isolated UTF-16 surrogate code points are invalid input.
Optional definitions, tags, and references may arrive as JSON-encoded strings.
Ordinary malformed JSON in those optional fields keeps the documented empty
fallback. Successfully decoded tag and reference fields receive the same
depth-100 and 10,000-node embedded-structure validation before shape fallback
or coercion; decoder resource-limit failures and structure-limit violations
are invalid input. Values decoded from embedded JSON are checked again because
escaped surrogates first materialize at that boundary.

The graph includes directed edges only when both source and target exist.
CJA-derived-field component references are normalized and contribute to those
edges and degree counts. Dangling references do not create graph edges.

Browser rendering is also bounded:

- the catalog and Changes view render at most 1,000 matching rows at once;
- the graph requires explicit opt-in above 1,000 nodes (or the configured
  `--max-graph-nodes` value) and above 8,000 reference edges;
- Changes materializes rows in batches of 250 after filtering the full data;
- Trend emits at most 59 interval summaries for its 60 snapshots; and
- Trend creates changed-ID chips only when an interval is expanded, in batches
  of 100 per change kind.

These are display bounds, not data-loss rules: filtering and progressive
disclosure continue to operate on the complete embedded data.

## Compatibility policy

The adapters warn, but do not reject, when a snapshot declares a generator
version newer than the adapter's tested-through marker. The current markers
are:

| Platform | Warning threshold |
|---|---:|
| CJA (`cja_auto_sdr`) | 3.11.7 |
| AA (`aa_auto_sdr`) | 1.21.10 |

A marker is evidence of exercised compatibility, not a promise about every
possible snapshot produced by that version. It may advance only after a
fresh, production-representative snapshot from that exact upstream version and
the full historical private corpus pass the release checks in
[`RELEASING.md`](RELEASING.md). Bundled fixtures and CI do not replace that
evidence.

Shared defensive model, adapter, and input behavior is maintained in the same
release cycle as `sdr-grader`. Intentional differences are documented in
[`ADAPTER_GUIDE.md`](ADAPTER_GUIDE.md).

## Release boundary

A green pull request is a release candidate, not an announcement. Publication
requires a separately authorized tag; the release workflow must publish the
verified wheel and source distribution to PyPI before creating the GitHub
release. Candidate qualification includes CodeQL analysis of both shipped
languages: Python and JavaScript/TypeScript. Public announcement remains
blocked until the post-publication evidence in
[`RELEASING.md`](RELEASING.md) is complete.
