# Workspace project usage

Starting in 1.2.0, `sdr-visualizer` can optionally collect Workspace project
usage while generating a catalog. It writes the HTML and a separate usage JSON
file automatically. Existing AA and CJA snapshots work without re-export.
Opening the report and replaying saved evidence are entirely offline.

## Generate an augmented report

Install the extra for the platform you use. The two SDK integrations are
independent and pinned to their characterized versions:

```bash
pip install 'sdr-visualizer[workspace-cja]'
sdr-visualizer snapshots/cja.json --collect-workspace-usage \
  --workspace-usage-org 'EXAMPLE@AdobeOrg' \
  --workspace-usage-config ../credentials/adobe.json \
  --output reports/cja.html
```

```bash
pip install 'sdr-visualizer[workspace-aa]'
sdr-visualizer snapshots/aa.json --collect-workspace-usage \
  --workspace-usage-org 'EXAMPLE@AdobeOrg' \
  --workspace-usage-company example-company \
  --workspace-usage-config ../credentials/adobe.json \
  --output reports/aa.html
```

Create the output directory first. Each command writes its HTML and
`reports/cja.workspace-usage.json` or `reports/aa.workspace-usage.json`.
`--workspace-usage-output PATH` overrides only the usage-file location.
`--json PATH` still writes the **complete report payload**, including usage.
The usage file contains exactly the logical evidence embedded in the report.
It is an output of collection; no notebook, raw findings file, or manual
normalization is required.

Collection also works with directory input, `--at`, stdin, comparison, and trend.
Only the primary catalog is augmented; a trend augments its newest selected
snapshot. The existing live inventory commands work as well:

```bash
sdr-visualizer --dataview example-dataview --collect-workspace-usage \
  --workspace-usage-org 'EXAMPLE@AdobeOrg' \
  --workspace-usage-config ../credentials/adobe.json --output reports/cja.html
sdr-visualizer --rsid example-suite --collect-workspace-usage \
  --workspace-usage-org 'EXAMPLE@AdobeOrg' --workspace-usage-company example-company \
  --workspace-usage-config ../credentials/adobe.json --output reports/aa.html
```

Live inventory still invokes `cja_auto_sdr` or `aa_auto_sdr` with its existing
configuration and 600-second timeout. The visualizer then collects usage itself;
it does not forward usage configuration to the exporter. No exporter changes
or new snapshot form are required. A live-generated usage file binds to the
original in-memory exporter snapshot. That raw snapshot is not saved as a new
output, so replay requires obtaining that exact original snapshot separately.
A later export is not interchangeable.

## Credentials, identity, and scope

Use an existing authorized account through an explicit config file, or omit
the config option to use the complete environment quartet `ORG_ID`, `CLIENT_ID`,
`SECRET`, `SCOPES`. Config wins as one complete source; partial sources are never
merged, and the visualizer does not search for a default config file.

Supported config keys are `org_id`, `client_id`, `secret`, and `scopes`. Scopes
accept a nonempty comma-separated string or list of strings. The legacy
`tech_id` key is ignored; other unknown keys are rejected. Endpoint overrides,
key-file loading, logging destinations, and executable configuration are not
accepted. Credential values and raw SDK diagnostics are never embedded or logged.
Keep config outside snapshot directories. Do not commit credentials.

The expected organization is required for both platforms. AA additionally
requires the explicit global company ID; CJA forbids that option. Credentials
must match the expected organization. Collection checks the exact CJA data view,
or the exact AA organization/company membership and report suite. Virtual AA
suite identity is retained. These checks do not authenticate the history of a
legacy snapshot: its organization/company context remains an author assertion.

By default, collection requests `includeType=all` and checks all catalog
components, up to 2,000. Narrow the question when necessary:

```bash
# Add these options to a collection command:
--workspace-usage-scope owned
--workspace-usage-component 'metric=metrics/pageviews'
--workspace-usage-component 'segment=example-segment'
```

`--workspace-usage-scope` accepts `all`, `owned`, or `shared`; owned omits
`includeType`, and shared requests it explicitly. Alternatively, repeat
`--workspace-usage-project ID` to fetch specific projects without an index scan.
Explicit project IDs and an explicit scope option are mutually exclusive.
There is no fallback from all to owned after an access failure.

Component selectors use exact `TYPE=ID`, splitting only the first `=`.
Types are `metric`, `dimension`, `derived_field`, `segment`, and
`calculated_metric`. Unknown, duplicate, or ambiguous raw IDs reject before
collection. Aliases are not inferred. Catalogs above 2,000 entries require a
bounded selection; an empty catalog cannot request collection.

Collection uses `cjapy==0.3.1` for CJA and `aanalytics2==0.5.3.post1` for AA.
Each SDK's `findComponentsUsage` runs locally against sanitized fetched project
definitions in a separate, credential-free process. Characterized helpers can
miss structures or return false positives. **All SDK results remain unverified
candidates**, even when API traversal completes. Neither integration promises
visibility into every Workspace project or parity of matching behavior.

## Read the catalog section

“Workspace project usage” is separate from Uses / Used by. It shows project
names and IDs, check time, requested scope, component attempts, collection and
result completion, permission visibility, source, and known limits. Project
names and IDs are plain text; this version does not create project links.
Lists retain all accepted projects and show 50 rows per page.

| Evidence condition | Display state |
|---|---|
| No evidence, component outside the requested scope, or missing result in a partial collection | Not checked; no fabricated zero-reference conclusion. |
| Missing result in a failed collection, or failed record without projects | Lookup failed; no conclusion available. |
| Nonempty unverified SDK results | Possible project references; exact component and environment match unverified. |
| Exact positive evidence with complete collection and record, without limitations | Project references found. Timing warnings remain independent. |
| Exact positives with partial/failed collection or record, or limitations | Project references found; results are partial. Positives remain visible. |
| Exact empty result, complete collection and record, no limitations, valid check time | No project references found within the checked scope. |
| Other attempted empty results | Partial or unverified lookup; no conclusion available. |

When retrieval metadata is supplied, completed positive and empty states also
require complete retrieval without retrieval limitations. Partial or failed
retrieval keeps exact positives visible as partial and empty results inconclusive.
Retrieval limitations appear on component display rows, including missing results.
Saved evidence without retrieval metadata remains supported.

Permission visibility is `limited` or `unknown`, never “all projects.” A
successful traversal describes only the declared scope accessible to the
collecting principal. Requested components, actual result records, retrieval
completion, and known collection/permission limits are separate facts. A
completed empty project inventory produces attempted partial/unverified empty
records, not a claim of non-use. Partial collection with no records must carry
the limitation `No results were collected`.

An empty result never establishes “unused” or “safe to delete.” An exact project
reference establishes an observed dependency, not recent project activity.
Unverified candidates do not establish that exact dependency.

“Usage checked at” is separate from snapshot time and report-generation time.
The collector uses the earliest response receipt among the inspected project
definitions; a completed empty inventory uses its last successful index receipt.
It never substitutes project modification time. Saved timestamps are not refreshed
when generating or opening a report.

Missing or empty timestamps display “Not supplied”; invalid bounded strings
display a timing warning. Timestamps require an explicit UTC offset and seconds.
Any time after report generation is marked future/unverified. Evidence older
than 24 hours at generation receives an age notice: this supports the daily
investigation workflow, not an Adobe freshness guarantee. Exactly 24 hours does
not trigger the notice. There is no “fresh” badge or automatic expiry. Bad timing
does not erase positives; missing, invalid, or future timing prevents an exact
empty result from becoming the scoped no-reference state.

## Replay saved evidence

```bash
sdr-visualizer snapshots/cja.json \
  --workspace-usage reports/cja.workspace-usage.json \
  --workspace-usage-org 'EXAMPLE@AdobeOrg' --output reports/cja-replay.html
sdr-visualizer snapshots/aa.json \
  --workspace-usage reports/aa.workspace-usage.json \
  --workspace-usage-org 'EXAMPLE@AdobeOrg' --workspace-usage-company example-company \
  --output reports/aa-replay.html
```

Replay requires neither SDK extras nor credentials nor network access. It
creates no usage sidecar and cannot be combined with collection or live inventory.
Use the original snapshot, including all its otherwise unused fields. Identity
or digest mismatches reject the whole usage input rather than automatically
rebinding it. Keep usage JSON outside snapshot directories so future snapshot
selection cannot mistake it for inventory.

Python callers can explicitly collect with
`sdr_visualizer.usage.collect_workspace_usage(parsed_snapshot, organization_context=...,
company_context=..., config_path=...)`, which returns a JSON-ready evidence mapping.
Pass that mapping to `visualize(..., workspace_usage=evidence,
organization_context=..., company_context=...)` for pure offline rendering.
Importing or calling ordinary `visualize` does not enable collection.

## Normalized input contract

The [version 1 JSON Schema](workspace-usage-schema.json) documents the accepted
envelope. It is **not** the raw component-ID-keyed `findComponentsUsage` response.
Raw filters/calculated-metric branches are not report evidence, and raw findings
alone do not supply measured timestamps, identity binding, or coverage metadata.

Required top-level fields are `schema_version: 1`, `target`, `collection`,
`requested_components`, and `results`. A result has a typed `component`, `status`,
`checked_at` (string or null), `match_basis`, `projects`, and `limitations`.
Each project has an exact `id` and `name` (string or null). `match_basis` is
`exact_component_id` for independently established assertions, or
`unverified_lookup` for candidates. Optional `failure` values are
`permission_denied`, `collection_error`, `unsupported`, and `unknown`.

CJA targets contain `platform`, `ims_org_id`, `data_view_id`, and `snapshot_digest`.
AA targets replace `data_view_id` with `global_company_id` and `rsid`. Cross-platform
fields are rejected. The digest uses `algorithm: "sdr-python-json-sha256-v1"` and
a lowercase SHA-256 `value` over the original parsed snapshot:

```python
hashlib.sha256(
    json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
).hexdigest()
```

Collection requires `status`, `project_scope`, `permission_visibility`, and
`limitations`. Scope is `{"kind":"accessible_projects"}` or
`{"kind":"explicit_projects","project_ids":["synthetic-project"]}`.
Complete collection requires one complete record per requested component.
Partial collection may omit records. Failure is distinct from completion.
Optional `source` identifies SDK candidates and version; optional `retrieval`
records the interval, requested visibility, request/page/detail counters, status,
and limits. These are measured by collection, not inferred from raw findings.

These synthetic result fragments illustrate the distinction:

```json
{"component":{"type":"metric","id":"synthetic-metric"},"status":"partial",
 "checked_at":"2026-09-12T12:00:00Z","match_basis":"unverified_lookup",
 "projects":[{"id":"synthetic-project","name":"Example analysis"}],
 "limitations":["Exact component and environment matching is unverified"]}
```

```json
{"component":{"type":"metric","id":"synthetic-metric"},"status":"complete",
 "checked_at":"2026-09-12T12:00:00Z","match_basis":"exact_component_id",
 "projects":[],"limitations":[]}
```

The second fragment requires independently justified exact matching and complete
declared scope; it is not produced by the current SDK collector. Complete
synthetic envelopes for [CJA](../tests/fixtures/workspace_usage_cja_all_types.json)
and [AA](../tests/fixtures/workspace_usage_aa_all_types.json) accompany the tests.
Runtime validation additionally checks binding and cross-record consistency.
Duplicate result records reject; identical duplicate project entries normalize
deterministically, while conflicting names for one project ID reject globally.
Explicit-scope results must refer only to that scope. Unknown schema keys reject.

## Bounds, persistence, and privacy

| Boundary | Limit |
|---|---|
| Usage file | Regular UTF-8 JSON, 2,097,152 bytes, depth 20, 100,000 nodes |
| Requested components / result records | 2,000 each |
| Distinct projects / occurrences before deduplication | 10,000 each |
| IDs / project names / timestamp strings | 512 / 256 / 64 characters |
| Limitations | 20 per list, 256 characters each |
| Embedded normalized usage branch | 1,048,576 UTF-8 serialized bytes |
| Config | Regular UTF-8 JSON, 64 KiB, depth 10, 1,000 nodes |
| Credential values | 16 KiB each, 64 KiB total |
| API response / total transfer | 2 MiB / 32 MiB; depth 100, 250,000 nodes per response |
| API work | 180 seconds, 256 attempts, 20 index pages of 50, 200 project details |
| Local SDK matching | Separate 30-second process deadline |

JSON duplicate keys, nonfinite values, invalid UTF-8/Unicode, BOMs, special files,
and over-limit inputs reject. IDs cannot contain control characters. Project
names/IDs and limitation text are escaped; supplied navigation URLs are not accepted.
Collection uses fixed Adobe HTTPS routes, encoded IDs, TLS verification, no
redirects, 5/15-second connect/read timeouts, and bounded explicit GET retries.
Authentication attempts count toward the limits. Pagination is not an atomic
point-in-time project snapshot. Partial traversal retains usable earlier projects.

These are engineering limits for optional report generation, not Adobe service
limits or completeness guarantees. Collection may take up to 210 seconds plus
process cleanup, separately from exporter time and the local
[build/render budgets](PERFORMANCE.md). With usage enabled, HTML must fit the
smallest applicable published tier, plus the existing comparison/trend allowance;
outside that envelope HTML is capped at 16,000,000 bytes. Full report JSON has
the same 16,000,000-byte cap. Oversized evidence rejects without truncation and
asks for a narrower scope. No-usage acceptance behavior is unchanged.

All intended feature artifacts are serialized and checked before writing.
Sibling temporary files are staged before final replacement. New HTML and full
report JSON use normal umask-derived file creation permissions; replacements
preserve their existing destination permissions. Standalone usage JSON uses
owner-only permissions where supported, including when replacing an existing
file. Staging failure preserves existing outputs. A replacement failure can
leave earlier complete files replaced; it returns exit 1, names the affected
artifact, and cleans remaining temporary files.
Collection interruption terminates workers and writes no new final artifacts.
Input/schema/identity errors return 3. Recorded API failures return 0 with a
warning if the truthful failure evidence and report were successfully written.

Reports and usage files contain project names/IDs, organization/company context,
and free-text limitations. Share them only with recipients authorized to see
that metadata. Offline operation is not access control. Raw project definitions,
owner fields, credentials, API responses, usage-file paths, and raw exception
messages are omitted. Runtime calls send environment/project identities to Adobe;
they do not upload snapshot or component definitions.

Existing component-reference lists, Used by counts, graph edges, navigation,
comparison, and trends keep their meaning. Workspace evidence stays with each
report; usage-specific history/diffs, project graph nodes, grading, deletion,
and activity measurement are outside this feature. `sdr-grader` supplementary
input compatibility is a future consumer consideration: no grader changes,
penalties, orphan-rule activation, or unresolved-reference policy changes occur.

Local tests use fake HTTP with each actual pinned SDK separately. Fresh live
Adobe qualification, universal permission coverage, exact-match promotion,
reliable project links, broader SDK versions, and exporter/grader enrichment
remain separate work.
