# Releasing

This checklist separates reversible release-candidate work from irreversible
publication. A candidate is not ready for a public announcement merely because
its pull request and CI are green.

## Readiness states

- **Not ready:** any required check or external control is missing, failed, or
  unverified.
- **Release-candidate ready:** one exact commit satisfies all pre-publication
  gates below, with privacy-safe evidence recorded in its release pull request.
- **Announcement ready:** a separately authorized tag has published that exact
  candidate to PyPI, the GitHub release was created afterward from the same
  verified artifacts, and the record includes both results.

Do not create or move a release tag, publish a package, create a GitHub release,
or announce the project as part of candidate preparation. Those actions need
explicit maintainer authorization after candidate review.

## Candidate identity

Record these first and repeat them in the release pull request:

```text
Candidate version (current candidate version):
Candidate commit SHA:
Visualizer PR:
Sibling sdr-grader PR:
Sibling sdr-grader commit:
Date:
Operator:
```

If the candidate commit changes, rerun affected checks and update the record.
Do not combine results from different candidate SHAs.
The candidate must be one merged `main` SHA. Freeze `main` at that commit
through tag authorization; any intervening merge is a stop condition and the
resulting SHA must be qualified from the beginning.

Before qualification begins, assign and record these roles with UTC
timestamps:

```text
Candidate approver:
Tag operator / authorization:
PyPI environment reviewer:
Release monitor:
Corpus operator:
Corpus privacy reviewer:
Announcement approver:
```

One person may fill multiple roles, but the release pull request must preserve
four separately timestamped decisions with durable release-PR permalinks:

1. candidate GO after the complete pre-publication matrix and security cutoff;
2. tag authorization after the exact candidate and absent public version are
   confirmed;
3. PyPI publication approval after the authoritative artifact, manifest, and
   90-day retention are inspected; and
4. public-verification evidence plus announcement GO after publication,
   provenance, install, digest, Pages, and URL checks pass.

Candidate GO does not authorize the tag, tag authorization does not authorize
PyPI approval, and publication does not authorize an announcement. Ignored
local plans and release-evidence files are supplemental, not authoritative;
the durable record is the release PR and its linked workflow/settings/public
evidence. The GitHub release must link that evidence index.

## Local verification

Run from a clean checkout of the candidate:

```bash
uv lock --check
uv sync --locked --dev --group browser
uv run playwright install chromium webkit
uv run ruff check
uv run ruff format --check
uv run python scripts/check_markdown_links.py
uv run python scripts/check_workflow_policy.py
uv run pytest tests/test_structure_limits.py tests/test_adapters_cja.py \
  tests/test_adapters_aa.py tests/test_cli.py tests/test_analysis_trend.py \
  tests/test_renderer.py -q
uv run pytest --ignore=tests/test_browser_functional.py \
  --cov=sdr_visualizer --cov-branch --cov-report=term-missing \
  --cov-report=json --cov-fail-under=99

uv run python scripts/generate_large_fixture.py \
  --scale 0.083 --output tests/fixtures/cja_snapshot_small.json
uv run python scripts/generate_large_fixture.py \
  --scale 0.417 --output tests/fixtures/cja_snapshot_medium.json
uv run python scripts/generate_large_fixture.py
uv run python scripts/generate_aa_large_fixture.py
uv run python scripts/generate_large_fixture.py \
  --scale 1.67 --output tests/fixtures/cja_snapshot_xl.json
uv run pytest tests/test_browser_functional.py -v
uv run python scripts/perf_browser_check.py
uv run python scripts/perf_check.py
```

Regenerate examples twice and confirm both passes produce no diff:

```bash
uv run python scripts/generate_examples.py
git diff --exit-code -- examples
uv run python scripts/generate_examples.py
git diff --exit-code -- examples
```

Build from a tree without generated performance fixtures, then smoke each
artifact in its own clean environment outside the checkout:

```bash
uv build --out-dir dist/packages
uv run python scripts/package_smoke_check.py dist/packages/
(cd dist/packages && sha256sum *.whl *.tar.gz)
```

Record the wheel and source-distribution filenames and SHA-256 digests. Inspect
their metadata and confirm Jinja2 is the only direct runtime dependency,
required public documents are in the source distribution, and ignored specs,
plans, generated fixtures, caches, and repository metadata are absent.
Extract the wheel and source distribution long descriptions and confirm their
repository-owned links are absolute, map to tracked content, and match the
source README. Inspect built metadata for the expected Homepage, Documentation,
Repository, Changelog, and Issues project URLs. This built-artifact check is
required even when source-level documentation tests pass.
The focused input-boundary run above must cover decoder-limit failures,
surrogate-containing string values and mapping keys, surrogates materialized by
embedded JSON decoding, direct rendering, default output naming, diagnostics,
and corrupt trend-member skipping.

Export and audit the runtime-only dependency set:

```bash
uv export --locked --no-dev --no-emit-project --no-header \
  --format requirements-txt \
  --output-file /tmp/sdr-visualizer-runtime-requirements.txt
uvx --python 3.12 pip-audit --disable-pip --no-deps \
  -r /tmp/sdr-visualizer-runtime-requirements.txt
```

The audit must report no known vulnerabilities. Record the `pip-audit`
version, vulnerability database date if reported, exact exported dependency
set, and result. Review `LICENSE` and
[`THIRD_PARTY_LICENSES`](../THIRD_PARTY_LICENSES) against shipped code and the
resolved dependency licenses.

## Upstream compatibility and private corpus

Bundled fixtures prove deterministic behavior; they do not prove current
production compatibility. Before marking a candidate ready:

1. Generate one new production-representative snapshot with the current
   released `cja_auto_sdr`, using the same complete-inventory mode requested by
   `sdr-visualizer --dataview`.
2. Generate one new production-representative snapshot with the current
   released `aa_auto_sdr`.
3. The assigned corpus operator puts those samples together with the full
   historical private snapshot corpus in a developer-controlled private
   directory with restricted permissions and no external telemetry.
4. Run:

   ```bash
   uv run python scripts/corpus_check.py /private/corpus --check-budgets
   ```

5. Exercise file, directory, stdin, and live mode where applicable, plus a
   representative comparison and trend.

Do not commit snapshots, paths, instance IDs, customer names, owners, component
names, formulas, or other customer data. The corpus operator inspects logs and
temporary outputs, removes scratch material, and proves before and after the
run that no snapshot, manifest, local path, identifier, or corpus-derived file
is tracked or packaged. The privacy reviewer approves only this aggregate
public record:

```text
Candidate SHA:
CJA generator version / snapshot count / command modes / result:
AA generator version / snapshot count / command modes / result:
Historical counts by platform and generator version:
Maximum observed structure nodes and depth:
Maximum observed component count and output size:
Failures or warnings, described without identifiers:
```

Advance `TESTED_THROUGH_GENERATOR_VERSION` only to generator versions actually
exercised by this run. If the corpus contradicts a structure or performance
limit, the candidate is not ready; fix or recalibrate the limit with tests and
rerun the complete gate.

## Sibling parity

Review changes to `core/models.py`, `adapters/`, and
`input/{loader,detect,shell_out}.py` against `sdr-grader`.

- Mirror shared defensive behavior in a linked sibling pull request.
- Document and test intentional project-specific differences.
- Record the sibling commit, pull-request URL, test result, and merge status.
- Require the sibling change to be green and merged in the same release cycle.
- Confirm the sibling patch changes no grader version metadata, CodeQL
  language set, package publication, GitHub release, or announcement surface.

Missing access or an unreviewed sibling change blocks release; it does not turn
parity into an optional follow-up.

When the candidate changes none of the listed shared runtime paths, sibling
parity may be recorded as a **diff-backed N/A**. The record must include the
base and candidate SHAs, the complete changed-path output, and a reviewer
confirmation that no shared runtime surface changed. A documentation-only
label or commit message is not sufficient evidence. Any shared-path change
requires the full sibling review above.

## GitHub and community controls

Inspect repository settings immediately before the go/no-go decision and record
the result:

- `main` requires pull requests and the expected test/lint checks;
- the candidate has successful `analyze (python, none)` and
  `analyze (javascript-typescript, none)` CodeQL checks, and `main` requires
  both emitted contexts before tag authorization;
- force pushes and branch deletion are blocked;
- administrator and bypass behavior is explicitly chosen;
- Dependabot alerts and security updates are enabled;
- secret scanning and push protection are enabled where supported;
- code scanning is enabled where supported, or its compensating control and
  owner are recorded, and no applicable open Python or JavaScript/TypeScript
  alert remains;
- the PyPI environment has the intended trusted-publisher protection;
- Pages uses the intended workflow/source and the repository homepage points to
  the live project site;
- the community profile recognizes the license, Code of Conduct, contribution
  guide, security policy, issue templates, and pull-request template; and
- the tracked security and community documents resolve from their advertised
  public links and do not direct vulnerabilities into public issues.

Unsupported account or plan features must be named with a compensating control
and owner. An unexplained disabled control is a blocker.

Record a UTC hosted-security cutoff with candidate GO. At that cutoff all
required controls and the zero-applicable-alert condition must pass. After
candidate GO, only the four reopen classes below can reverse GO unless evidence
for the exact candidate SHA is shown to be invalid; a newly surfaced
non-critical item is backlog.

## Requirement evidence matrix

Copy this table into the release pull request and replace every `pending` with
a durable test, workflow run, document section, pull request, digest, or
settings inspection tied to the candidate SHA.

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
| R18 sibling parity | linked green sibling PR and commit | pending |
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

### Documentation-patch evidence map

The current documentation patch uses P1-P15 to map its implementation contract
onto the durable release rows above. This table records scope; it does not
renumber or replace R1-R37.

| Patch requirement | Durable release evidence |
|---|---|
| P1 README link portability | R15 and R34 |
| P2 saved versus live generator onboarding | R1, R17, and R28 |
| P3 navigation model accuracy | R15 plus functional browser evidence |
| P4 performance-tier and browser scope | R10 and R25 |
| P5 end-user troubleshooting and safe sharing | R16 and R28 |
| P6 Catalog versus Changes display bounds | R9 and R15 |
| P7 platform-extension seams and payload boundary | R15 and payload-schema evidence |
| P8 illustrative embedded examples and stable kinds | R15 and R29 |
| P9 changelog and contributor convention | R15 and R36 |
| P10 package and Pages discovery | R34 and R35 |
| P11 conduct-reporting route | Excluded from this patch by maintainer scope; no route is changed or claimed as new evidence. |
| P12 drift-prevention checks | R15 and R34-R37 |
| P13 one synchronized candidate | R13 and R36 |
| P14 generic reusable release rubric | R21 and R34-R37 |
| P15 pending announcement until public verification | R33 and R37 |

Also account explicitly for the original 14 validated findings:

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

## Publication and recovery

Before tagging, prove the candidate version is absent from remote tags, GitHub
releases, and PyPI. Record the exact candidate SHA and confirm the annotated
tag will dereference to that SHA. Any conflicting public state is a stop
condition.

Immediately before tag authorization, run an **upstream-freshness** check for
the current released CJA and AA generators. Reconfirm installation guidance,
authentication/configuration prerequisites, interpreter constraints, reported
versions, and one live generation path against the frozen candidate. Any drift
from candidate evidence stops publication and requires complete
requalification; it is not patched into the release after tagging.

After the candidate is approved, a separate explicit tag authorization starts
the release workflow. Record the workflow run ID and attempt, event, tag,
`headSha`, job conclusions, retained artifact ID, artifact expiry, distribution
filenames, and authoritative `SHA256SUMS`. Grant the protected PyPI environment
approval only after those artifacts and their manifest exist. Verify that:

1. browser/performance gates pass;
2. one build job creates and smoke-tests the wheel and source distribution;
3. the digest manifest covers exactly those distributions;
4. PyPI trusted publishing succeeds;
5. only then does the GitHub release job verify the same digests and attach the
   same artifacts plus the manifest.

Add the tag, workflow-run URL, PyPI project/version URL, GitHub release URL,
artifact digests, and installation smoke result to the evidence record.
Verify PyPI provenance identifies this repository, `release.yml`, the
authorized tag ref, and the exact candidate SHA. Fresh `--no-cache-dir`
installs on Python 3.11 and 3.12 must render outside the checkout. Download the
PyPI and GitHub distributions again, compare them with the retained manifest,
and confirm the GitHub `SHA256SUMS` asset matches that manifest byte-for-byte.
Inspect the Warehouse-rendered long description and every published project
URL, not only the source README and local metadata. Record the Pages deployment
SHA, verify the landing's current-`main` disclosure and destinations, and
confirm both deployed examples embed the expected visualizer version. If Pages
deploys again before announcement GO, repeat those checks against the newer
deployment SHA.

The authoritative workflow artifact must remain available throughout a
90-day recovery window. Confirm repository retention and the artifact's actual
expiry before approval; if either is shorter, stop and repair the recovery
path before tagging.

Every retry records its run ID, attempt, artifact ID, and manifest. Evidence
from different artifact sets may never be combined.

| Public state | Permitted recovery | Stop condition |
|---|---|---|
| Tag exists; no authoritative workflow artifact | A transient retry may create the first authoritative set only when tag/SHA are unchanged and no code or artifact defect exists. | Moved/reused tag, changed SHA, or a defect requiring rebuilt content. |
| Authoritative artifact exists; PyPI has zero files | Retry only downstream publication from that retained artifact and manifest. | Rebuild, changed artifact identity, or mixed evidence. |
| PyPI has a partial file set | Stop routine release and inventory public filenames and digests. Only separately authorized incident recovery may upload a missing byte-identical retained file. | Any existing or missing-file mismatch requires forward recovery. |
| PyPI is complete; GitHub release or assets are absent/partial | Inventory existing assets, then retry only from the retained artifact and manifest. | Existing assets are neither absent nor byte-identical, or retained artifacts are missing/expired. |
| Public digest, provenance, install, or content defect | Block announcement, preserve evidence, and obtain separate incident authorization before any yank or deletion. Correct only in a forward patch. | Any attempt to overwrite assets, move the tag, or silently replace the published version. |
| Only URL propagation is incomplete | The release monitor retries until the recorded deadline without changing artifacts. | The deadline passes: announcement is NO-GO/rescheduled, not rebuilt or republished. |

The public announcement is a final, separate go/no-go. It remains blocked until
every applicable matrix row is passing, both publication links and the live
Pages/homepage URLs resolve, public provenance and digests pass, and the
announcement approver records a UTC-timestamped go decision.

## Post-matrix stop and reopen rule

After every applicable matrix row passes for the frozen candidate, do not start
another unconstrained repository-readiness audit for this announcement. New
information reopens GO only when it identifies:

1. a critical security vulnerability;
2. data loss on a normal supported path;
3. broken installation or publication; or
4. a regression introduced by the current patch release.

This rule does not waive a matrix row or invalid exact-SHA evidence. All other
new findings and improvements enter the post-announcement backlog without
moving the launch bar.
