# Release evidence template

Copy this template into the release pull request and replace every `pending`
with evidence for one frozen candidate. This tracked file is a reusable copy
source only; it is **not authoritative release evidence**. The release pull
request and its durable permalinks are the authoritative record. Follow the
complete [release checklist](RELEASING.md) rather than treating this template
as a substitute for its instructions.

Do not combine evidence from different candidate SHAs or artifact sets. Keep
customer data, credentials, local paths, and private corpus identifiers out of
the release pull request.

## Candidate identity

| Field | Value |
|---|---|
| Candidate version | pending |
| Preparation branch / PR head SHA | pending |
| Frozen merged-`main` candidate SHA | pending |
| Candidate state (`preparation` or `frozen merged-main`) | pending |
| Frozen candidate commit permalink | pending |
| Visualizer release PR URL | pending |
| Sibling sdr-grader PR URL | pending |
| Sibling sdr-grader commit permalink | pending |
| Evidence record started UTC | pending |
| Operator | pending |

## Assigned roles

All assignments remain pending until the named person and assignment time are
recorded.

| Role | Assignee | Assigned UTC | Result |
|---|---|---|---|
| Candidate approver | pending | pending | pending |
| Tag operator / authorization | pending | pending | pending |
| PyPI environment reviewer | pending | pending | pending |
| Release monitor | pending | pending | pending |
| Corpus operator | pending | pending | pending |
| Corpus privacy reviewer | pending | pending | pending |
| Announcement approver | pending | pending | pending |

## Qualification timing and triage

| Field | Value |
|---|---|
| Qualification started UTC | pending |
| Qualification completed UTC | pending |
| Triage window opened UTC | pending |
| Triage window closes UTC | pending |
| URL-propagation deadline UTC | pending |
| Deadline owner | pending |
| Triage owner | pending |
| Triage record permalink | pending |
| Open blockers or stop conditions | pending |

### Owners and prerequisites

| Pending group | Owner | Prerequisite | State |
|---|---|---|---|
| Candidate identity and freeze | pending | merged `main` SHA selected | pending |
| CLI and package | pending | clean checkout of frozen candidate | pending |
| Live CJA and AA | pending | operator authorization, privacy controls, credentials, and current generators | pending |
| Compare and Trend | pending | qualified sanitized input set | pending |
| CJA lineage | pending | qualified discovery input and authorized live access | pending |
| Workspace usage | pending | explicit collection authorization, privacy controls, and platform credentials | pending |
| Fresh and historical corpus | pending | corpus operator and privacy reviewer assigned | pending |
| Hosted settings and security | pending | exact-SHA runs and settings access | pending |
| Artifact and publication | pending | candidate GO and separate tag authorization | pending |
| Public verification and announcement | pending | completed publication from the authoritative artifact | pending |

## Candidate qualification

Record commands, results, and durable exact-SHA evidence separately for each
surface. Use `pending` until the required work has actually completed.

### CLI and package surface

| Evidence | Value |
|---|---|
| Exact candidate SHA | pending |
| Lock, lint, format, documentation-link, and workflow-policy results | pending |
| Focused input-boundary result | pending |
| Non-browser suite and coverage result | pending |
| Package metadata, dependency export, audit, and license review | pending |
| Wheel and source-distribution smoke result | pending |
| Durable evidence permalink | pending |

### Live CJA and AA

| Evidence | Value |
|---|---|
| CJA generator version and sanitized modes/arguments (placeholder IDs and config paths only) | pending |
| CJA exact-argv test permalink | pending |
| CJA complete-inventory result | pending |
| AA generator version and sanitized modes/arguments (placeholder IDs and config paths only) | pending |
| AA exact-argv test permalink | pending |
| AA normalized-catalog result | pending |
| Timeout, cleanup, authentication, and interpreter checks | pending |
| Durable evidence permalink | pending |

### Compare

| Evidence | Value |
|---|---|
| Input platforms and generator versions | pending |
| Nullable timestamps and platform-detection result | pending |
| Reference, compatibility-warning, and output-collision result | pending |
| Chromium and WebKit result | pending |
| Durable evidence permalink | pending |

### Trend

| Evidence | Value |
|---|---|
| Input platforms and generator versions | pending |
| Selection-first cap and corrupt-member result | pending |
| Compatibility-warning, UTC cutoff, and bounded-DOM result | pending |
| Chromium and WebKit result | pending |
| Durable evidence permalink | pending |

### CJA lineage

| Evidence | Value |
|---|---|
| Saved and live discovery result | pending |
| Layout, payload, renderer, CLI, and accessibility result | pending |
| Chromium and WebKit result | pending |
| Performance result | pending |
| Durable evidence permalink | pending |

### Workspace usage

| Evidence | Value |
|---|---|
| CJA fake-HTTP/actual-SDK result | pending |
| AA fake-HTTP/actual-SDK result | pending |
| Saved-evidence replay and binding result | pending |
| Collection bounds, privacy, packaging, and optional-extra review | pending |
| CJA and AA live-qualification authorization (pending blocks corresponding qualification) | pending |
| Authorized CJA and AA live-qualification result | pending |
| Durable evidence permalink | pending |

## Fresh and historical corpus aggregate

This section is the only public corpus record. Complete it only after the
assigned corpus operator and privacy reviewer approve the aggregate. Do not
include snapshot contents, paths, instance IDs, customer names, owners,
component names, formulas, or other identifiers.

| Field | Value |
|---|---|
| Candidate SHA | pending |
| Fresh CJA generator version / snapshot count / command modes / result | pending |
| Fresh AA generator version / snapshot count / command modes / result | pending |
| Historical counts by platform and generator version | pending |
| Maximum observed structure nodes and depth | pending |
| Maximum observed component count and output size | pending |
| Failures or warnings, without identifiers | pending |
| Scratch cleanup and tracked/package absence evidence | pending |
| Corpus operator approval / UTC / permalink | pending |
| Corpus privacy reviewer approval / UTC / permalink | pending |

## Sibling parity

Keep inherited evidence separate from the current candidate delta.

### Inherited v1.2.0 structured tag normalization parity

| Field | Value |
|---|---|
| v1.2.0 visualizer commit permalink | pending |
| Linked sdr-grader PR URL | pending |
| Linked sdr-grader commit permalink | pending |
| Structured tag normalization parity test result and permalink | pending |
| Sibling PR merge status and merge permalink | pending |
| Reviewer / reviewed UTC / result | pending |

This inherited record establishes only the v1.2.0 baseline; it does not qualify
the current candidate delta. Any open inherited parity gap remains blocking and
cannot be closed by recording the current delta as diff-backed N/A.

### Current candidate delta

| Field | Value |
|---|---|
| Base SHA | pending |
| Candidate SHA | pending |
| Complete changed-path output permalink | pending |
| Shared runtime paths changed | pending |
| Full parity or diff-backed N/A evidence | pending |
| Current sibling PR and commit permalinks, if applicable | pending |
| Shared-contract comparator result, if applicable | pending |
| Reviewer / reviewed UTC / result | pending |

## Hosted checks, settings, and security cutoff

| Evidence | Value |
|---|---|
| Exact-SHA test matrix run(s) | pending |
| `test (3.11)` | pending |
| `test (3.12)` | pending |
| `test (3.14)` | pending |
| `browser-perf` | pending |
| `analyze (python, none)` | pending |
| `analyze (javascript-typescript, none)` | pending |
| Release build/test and browser interpreter assertions | pending |
| Branch protection / ruleset required-context inspection | pending |
| Force-push, deletion, administrator, and bypass settings | pending |
| Dependabot, secret scanning, push protection, and code scanning | pending |
| PyPI trusted-publisher environment protection | pending |
| Pages source, homepage, and community-profile settings | pending |
| Compensating controls and owners | pending |
| Applicable open security alerts at cutoff | pending |
| Hosted-security cutoff UTC | pending |
| Settings and security evidence permalinks | pending |

## Requirement evidence matrix

Replace every result with a durable test, workflow run, document section, pull
request, digest, or settings inspection tied to the candidate SHA. Do not
renumber these requirements.

| Requirement | Required evidence | Result |
|---|---|---|
| R1 complete live CJA inventory | exact argv test + fresh live CJA run | pending |
| R2 nullable compare timestamps | schema/CLI tests | pending |
| R3 derived reference integrity | adapter/graph/payload tests | pending |
| R4 selection-first trend cap | mixed-platform and corrupt-series tests | pending |
| R5 UTC cutoff behavior | multi-time-zone tests | pending |
| R6 hostile structure budgets | boundary/CLI/corpus tests | pending |
| R7 safe identifiers/diagnostics | filename and terminal-control tests | pending |
| R8 graph threshold validation | CLI tests | pending |
| R9 bounded Changes/Trend DOM | functional + high-churn browser gate | pending |
| R10 user-visible timing | cold/warm layout-inclusive browser gate | pending |
| R11 immutable action pins | workflow-policy check | pending |
| R12 PyPI-before-GitHub ordering | workflow-policy check + authorized tag run | pending |
| R13 installed artifacts | wheel/sdist smoke + digests | pending |
| R14 minimal runtime dependencies | metadata/export/audit/license evidence | pending |
| R15 shipped, consistent docs | Markdown links + source-distribution check | pending |
| R16 safe sharing guidance | README review | pending |
| R17 current compatibility | privacy-safe fresh/corpus record | pending |
| R18 sibling parity | linked green sibling PR/commit and passing shared-contract comparator when color packs change | pending |
| R19 protected/monitored `main` | settings/API inspection | pending |
| R20 complete community surface | community profile + advertised public-link resolution | pending |
| R21 one traced candidate | this matrix + final go/no-go | pending |
| R22 decoder resource containment | focused adapter/CLI regressions | pending |
| R23 Unicode-scalar input boundary | structure/adapter/render/trend regressions | pending |
| R24 all shipped languages scanned | two successful CodeQL contexts + required-check inspection | pending |
| R25 complete browser tier matrix | required 100/500/1,000/2,000 tier gate + missing-fixture tests | pending |
| R26 output/input collision safety | lexical/symlink/hard-link/directory-candidate regressions | pending |
| R27 unambiguous platform detection | hybrid direct/override/compare/trend tests | pending |
| R28 bounded live generators | exact 600-second CJA/AA timeout and cleanup tests | pending |
| R29 documented `derived_kind` | guide/schema/payload agreement tests | pending |
| R30 all-input compatibility warnings | comparison/trend ordering, dedup, and exclusion tests | pending |
| R31 decoded list structure budgets | exact decoded tag/reference depth and node boundary tests | pending |
| R32 non-drifting test status | live workflow badge and fixed-count absence test | pending |
| R33 one frozen announcement candidate | exact-SHA matrix, four decisions, public verification, and reopen rule | pending |
| R34 portable built/public package metadata | wheel and source distribution long descriptions, Warehouse-rendered long description, and project URLs | pending |
| R35 Pages content and provenance | required landing links, examples track current `main` disclosure, Pages deployment SHA, and both embedded example versions | pending |
| R36 synchronized current release identity | project/module/lock/changelog/example version checks derived from the current candidate version | pending |
| R37 reusable patch-release policy | generic release-language regression, upstream-freshness check, and diff-backed sibling-parity applicability | pending |

## Historical findings

| Finding | Requirement | Result |
|---|---|---|
| Privileged workflows used mutable action tags | R11 | pending |
| GitHub release preceded PyPI success | R12 | pending |
| Timestamp-less compare violated payload schema | R2 | pending |
| Derived-field references missed graph edges | R3 | pending |
| Live CJA omitted optional inventories | R1 | pending |
| Changes and Trend eagerly rendered unbounded rows | R9 | pending |
| Filter timing ended before layout work | R10 | pending |
| Public docs linked to an ignored private spec | R15 | pending |
| PyYAML/Pydantic were unjustified runtime dependencies | R14 | pending |
| Hostile instance IDs reached filenames/terminal output | R7 | pending |
| Negative `--max-graph-nodes` succeeded | R8 | pending |
| Filesystem time used host-local cutoff semantics | R5 | pending |
| Trend capped before platform selection | R4 | pending |
| Deep accepted structures escaped invalid-input handling | R6 | pending |
| Embedded JSON decoder limits escaped invalid-input handling | R22 | pending |
| Surrogate code points crashed output and serialization paths | R23 | pending |
| CodeQL omitted shipped browser JavaScript | R24 | pending |

## Pretag freshness and version absence

| Evidence | Value |
|---|---|
| Candidate SHA re-confirmed | pending |
| Candidate version absent from remote tags | pending |
| Candidate version absent from GitHub releases | pending |
| Candidate version absent from PyPI | pending |
| Annotated tag dereferences to candidate SHA | pending |
| CJA upstream-freshness result | pending |
| AA upstream-freshness result | pending |
| Installation, authentication, interpreter, and live-path drift review | pending |
| Evidence permalinks / checked UTC / reviewer | pending |

## Authoritative artifact and retention

Use one artifact set throughout. Record every retry separately; never combine
evidence from different attempts or manifests.

| Field | Value |
|---|---|
| Release workflow URL | pending |
| Workflow run ID | pending |
| Attempt | pending |
| Event / tag / `headSha` | pending |
| Job conclusions | pending |
| Retained artifact ID | pending |
| Artifact URL | pending |
| Artifact expiry UTC | pending |
| Repository retention setting and inspection URL | pending |
| 90-day recovery-window end UTC | pending |
| Wheel filename / SHA-256 | pending |
| Source-distribution filename / SHA-256 | pending |
| Authoritative `SHA256SUMS` manifest URL | pending |
| Manifest-to-artifact comparison | pending |
| PyPI environment approval / UTC / permalink | pending |

## Public verification

| Evidence | Value |
|---|---|
| PyPI project/version URL and file inventory | pending |
| GitHub release URL and asset inventory | pending |
| PyPI provenance repository/workflow/tag/SHA result | pending |
| Fresh Python 3.11 `--no-cache-dir` install and render | pending |
| Fresh Python 3.12 `--no-cache-dir` install and render | pending |
| PyPI download hashes versus retained manifest | pending |
| GitHub download hashes versus retained manifest | pending |
| GitHub `SHA256SUMS` byte comparison | pending |
| Warehouse-rendered long description | pending |
| Published Homepage, Documentation, Repository, Changelog, and Issues URLs | pending |
| Pages deployment SHA and URL | pending |
| Pages current-`main` disclosure and destination checks | pending |
| Deployed CJA and AA example versions | pending |
| URL propagation checked UTC | pending |
| Public-verification evidence permalink | pending |

## Decision records

These are four distinct decisions. Each remains pending until its own reviewer,
UTC timestamp, decision, and durable release-PR permalink are recorded.

| Decision | Reviewer | UTC | Decision | Durable release-PR permalink |
|---|---|---|---|---|
| 1. Candidate GO after the complete pre-publication matrix and security cutoff | pending | pending | pending | pending |
| 2. Tag authorization after exact-candidate and absent-version confirmation | pending | pending | pending | pending |
| 3. PyPI publication approval after artifact, manifest, and 90-day retention inspection | pending | pending | pending | pending |
| 4. Public verification and announcement GO after publication, provenance, install, digest, Pages, and URL checks | pending | pending | pending | pending |

## Final status

| Field | Value |
|---|---|
| Applicable matrix rows complete | pending |
| Reopen-class review | pending |
| Announcement status | pending |
| Final reviewer / UTC / durable permalink | pending |
