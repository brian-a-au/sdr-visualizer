# Adapter correctness review for 1.1.2

## Release closeout (2026-09-08)

Version 1.1.2 was released after this review. The final visualizer candidate was
`994d6bfc064782138492d5dbfc004e52ec57bf01`; the defensive-fallback companion
[sdr-grader #62](https://github.com/brian-a-au/sdr-grader/pull/62) merged on
2026-09-07 at `b20dde45c72d28368e58307f86805324b330dc54`.

The later [candidate qualification record](https://github.com/brian-a-au/sdr-visualizer/pull/41#issuecomment-5576131593)
includes the fresh CJA/AA exports and historical corpus qualification.
The [public verification record](https://github.com/brian-a-au/sdr-visualizer/pull/41#issuecomment-5576213797)
closes publication, artifact identity, provenance, and installed-package checks.
See [PR #41](https://github.com/brian-a-au/sdr-visualizer/pull/41) for the full
merged-candidate evidence and release links.

The sections below preserve the original review and preparation scope.
Their statements about pending merges, corpus runs, and publication describe
that earlier stage, not the release's current readiness. The documented
comparison and reference-inference limits still apply.

## Scope and reproductions

Reviewed against visualizer main `26c19be` (1.1.1). The original investigation
used `c1646f8`; the intervening patch added typed CJA shortened-ID graph matching.
The following synthetic cases still failed on current main, through adapter →
analysis → schema-valid payload → HTML → Chromium and WebKit:

- AA divide with typed `col1` revenue and `col2` visitors displayed `divide()`,
  omitted both outgoing edges, and missed a numerator change to orders.
- AA `streq` with `val={func: attr, name: variables/page}` and the literal
  `str=metrics/documentation` omitted its page reference and detail link.
- CJA segment `dimension_references=[dimensions/channel]` did not resolve the
  exported `variables/channel`, leaving its outgoing link/count unresolved.

`tests/adapter_cases.py` contains only synthetic inputs. Before implementation,
all three payload cases, the comparison case, and all six browser cases failed.
The tests now require edges, readable summaries, typed anatomy destinations,
and navigation. Additional cases cover absent targets, literals, aliases in
both directions, exact precedence, namespace/path collisions, derived-field
outgoing references, saved filters, outer and inner filter context, and trend
counts/intervals. Existing short-ID ambiguity and resource-limit tests remain.

## Evidence and changes

Adobe's [calculated metrics API examples](https://developer.adobe.com/analytics-apis/docs/2.0/guides/endpoints/calculatedmetrics/)
use `col1`, `col2`, typed metric nodes, and a `visualization-group/col` wrapper.
Its [segment definition contract](https://developer.adobe.com/analytics-apis/docs/2.0/guides/endpoints/segments/definition)
distinguishes `attr/name` and `event/name` references from `str`, `list`, and
`glob` literals. These support the confirmed AA extraction and anatomy fixes.

Saved `segment-ref/id` filters and CJA `dimensions/` ↔ `variables/` aliases
follow the established sibling evidence in
[sdr-grader's 1.2.7 audit](https://github.com/brian-a-au/sdr-grader/blob/366b0834301c69b5a69a493a8bd77328710188bf/docs/CORRECTNESS_AUDIT_1.2.7.md).
The saved-filter shape is documented there from an API client; this review
does not claim that the current official Adobe pages exhaustively specify it.

AA now preserves named operands and relevant outer definition context. Formula
summaries retain field names, values, and filters in deterministic order. Known
formula wrappers and saved/inline filters render in anatomy. Typed references
are extracted separately from literal text, keeping supplied IDs intact.

Graph and anatomy use one snapshot-local resolver: exact IDs first, then
established dimension/variable aliases or the existing unique CJA short-ID
fallback. Full alias suffixes are preserved. No metric namespace aliases,
missing-ID guesses, or omitted-inventory nodes are introduced. Graph degree
counts, detail links, and trend aggregates use resolved edges.

## Sibling parity

[sdr-grader #60](https://github.com/brian-a-au/sdr-grader/pull/60) is merged at
`366b0834301c69b5a69a493a8bd77328710188bf` (1.2.7). Its adapter, fuzz,
AA-definition, CJA-resolution, and correctness-evidence suites passed: 238 tests.
This patch adopts its extraction and alias semantics while keeping visualizer
graph typing, readable summaries, inventory retention, coercion failures, and
output protection. A subsequent fuzz run reproduced a shared 1.2.7 regression:
non-object calculated-metric definitions could crash outer-context preservation
or contribute references despite an empty retained formula. Both adapters now
normalize these malformed definitions to the prior empty fallback.

The minimal companion [sdr-grader #62](https://github.com/brian-a-au/sdr-grader/pull/62)
at `adb3beea12afdc683823c3158baa78573abb1d9c` contains only that guard and six
synthetic regressions. Its full suite passed 1,149 tests (244 focused). It remains
unmerged in this session; release parity requires its green checks and maintainer
merge. The visualizer also keeps malformed segment definitions from acquiring
new references; grader segment-list extraction predates 1.2.7 and is unchanged.

Listed defensive helper bodies remain unchanged. Grader built-in availability
and grading logic are excluded. No sibling release metadata or publication
surfaces were modified. Exact committed-SHA color-contract parity and final
visualizer checks are recorded in the PR.

## Coverage limits and intentional boundaries

- Only bundled and synthetic fixtures were used. No private fixture directory
  was supplied or accessed, no fresh production/live generator run occurred,
  and no customer incidence or full historical corpus qualification is claimed.
  Compatibility version markers are unchanged. The release corpus and privacy
  review remain pre-publication requirements, not completed evidence.
- Snapshot comparison deliberately excludes raw segment definitions. CJA
  comparison still relies on exported formula summaries and reference arrays;
  distinct raw formulas with the same summary and references remain outside
  that contract. No arbitrary formula-equivalence engine was introduced.
- CJA declared reference arrays remain authoritative for graph dependencies.
  Anatomy describes supplied definitions; inconsistent or omitted upstream
  reference arrays can still disagree with definition contents. This patch
  unifies target resolution, not reference inference for undocumented shapes.
- Unknown AST operators retain descriptive fallbacks. No aliases beyond the
  established namespace pair and existing short-ID contract are inferred.
- All component inventories were already counted correctly. The independent
  `cja-lineage` pipeline was unchanged; its README introduction moved below
  the main catalog/development sections, before related-project links.
- This is PR/candidate preparation only. No merge, tag, publication, or release
  readiness approval is included.
