# CJA lineage reports

`cja-lineage` shows which Adobe Experience Platform (AEP) datasets feed your
CJA Connections and which Data Views use those Connections. It is included in
the `sdr-visualizer` package starting with version 1.1.0.

The command uses CJA dataset discovery JSON to build the report. AA report suites
and AA or CJA component snapshots cannot be used as lineage input. To generate
component catalogs for CJA or Adobe Analytics (AA), use `sdr-visualizer`.

## Generate a report

After installing the package, inspect the available options:

```bash
cja-lineage --help
cja-lineage --version
```

With a saved discovery file, no upstream generator or credentials are needed:

```bash
cja-lineage --saved discovery.json --output lineage.html \
  --scope-label "Accessible CJA scope" --color-pack default
```

The saved file is the JSON object returned by
`cja_auto_sdr --list-datasets --format json --output -`, not a component
snapshot. It contains a `dataViews` array and a `count`, with each Data View's
parent Connection and backing datasets. Use the upstream tool's own credential
configuration when saving discovery output. Do not paste credentials into
command arguments.

For live discovery:

```bash
cja-lineage --live --binary /absolute/path/to/cja_auto_sdr \
  --config-file /absolute/path/to/config.json \
  --scope-label "Accessible CJA scope" --output lineage.html
```

Alternatively use `--profile profile-name`, or omit both credential selectors
to use the upstream default credential route. `--profile` and `--config-file`
are mutually exclusive and apply only to `--live`. The executable and explicit
configuration paths must be absolute. Live discovery currently accepts exactly
`cja_auto_sdr` 3.11.8 and 3.12.0. Other versions fail closed pending compatibility
qualification; saved discovery is validated by shape rather than generator
version. No generator is installed automatically.

The command currently targets macOS and Linux, using POSIX process and
owner-only output protections. Windows execution is not qualified. The generated
HTML is portable and opens offline in a modern browser on any platform.

The default output is `lineage.html`; `--output` selects another file. The parent
directory must exist. Successful writes atomically replace the destination with
an owner-only file (`0600`). Explicitly supplied input, credential configuration, and executable paths
(and their aliases) cannot be overwritten. Configuration files discovered
implicitly by upstream profiles or environment settings are not known to the
output validator; choose a dedicated HTML destination. Symlink and multiply linked destinations are rejected.
`--quiet` suppresses the success message. Opening the report is a separate step.

## Explore the report

1. Start with the Connection overview and relationship-role counts.
2. Choose **Data Views**, **Connections**, or **Datasets** in **Search for**, then
   enter a name or stable identifier. Duplicate names retain their identifiers.
3. Select a Connection to see its datasets, role mix, and explicit Data View
   choices. A dataset search reveals the accessible Connections using it and
   the number of Data Views under each.
4. Choose a Data View to draw its bounded neighborhood. Select a backing
   dataset to inspect that dataset–Connection relationship and trace its route.
5. Use **Back to Connection** to return to the inspector. Escape clears a route
   or selection and restores focus. Search and selection do not write browser
   storage or change the URL.

Role filters remain active when navigating back. Selecting a searched Connection
excluded by the current role filter resets that filter to All so the selection
can be shown. Dataset search spans the accessible scope, independent of the
overview role filter.

**Dark mode** is available before drawing a diagram. The report follows the
system theme until you override it. The color packs are `default`, `ADBE`,
`OMTR`, and `BLUE`. Text labels accompany role colors. Reduced-motion preferences
remove moving markers; static route emphasis retains the same meaning.

Choose **Draw full topology** to draw the complete diagram. Reports with more
than 1,000 nodes or 8,000 relationships show a warning because drawing a large
diagram can be slow; you can still choose to draw it. Use zoom, reset, and
selected-route centering for navigation. Large local neighborhoods compact their
geometry and show lists in batches. Search and relationship details are available
without drawing the full diagram.

## Interpret coverage correctly

The report describes the scope accessible during discovery, not every object
in an organization. Unavailable, not reported, reported empty, and explicit
null values remain distinguishable. Identical dataset IDs can have different
metadata in different Connections.

Event, Profile, Lookup, Summary, and custom roles are **Connection
configuration**. They are not XDM behavior or AEP Profile enablement. Role counts
count dataset–Connection relationships, so a shared dataset may contribute more
than once. Ingestion observations do not prove end-to-end CJA reporting readiness.
Animation is a navigation aid, not measured throughput, latency, or health.

The HTML contains names, stable identifiers, and available relationship metadata.
Keep live reports private to their authorized audience. The repository
[synthetic example](https://github.com/brian-a-au/sdr-visualizer/blob/main/examples/cja-lineage.html) contains no live discovery data.

## Troubleshooting and exit codes

| Result | Next step |
|---|---|
| `invalid-structure` | Supply CJA `--list-datasets` discovery JSON; AA and CJA component snapshots are unsupported. |
| `invalid-json` / `invalid-utf8` | Save complete UTF-8 JSON output, without terminal messages mixed into it. |
| `saved-read-failed` | Check that the saved file exists and is readable. |
| `executable-invalid` | Use an absolute, current-user-owned executable that is not group/world writable. |
| `executable-version-mismatch` | Use a qualified upstream version listed above. |
| `selector-invalid` | Check the profile or absolute configuration path and use one credential selector. |
| `process-failed` / `timeout` | Check upstream authentication and discovery independently; acquisition has a 600-second limit. |
| `saved-too-large` / `stdout-limit-exceeded` / `stderr-limit-exceeded` | Reduce the discovery scope; capture is bounded at 64 MiB for saved/stdout and 1 MiB for stderr. |
| `unsafe-destination` / `write-failed` | Choose a separate regular output file in a writable existing directory. |

`cja-lineage` returns **0** on success, **1** for rendering/output failures,
**2** for argument errors, and **3** for rejected input or destination preflight.
Errors omit raw arguments, discovery content, and upstream stderr. These are
the lineage command's codes; the existing catalog command's codes are unchanged.

## Compatibility and development

The documented command arguments are the public lineage interface. The embedded
`sdr-lineage-data` payload, Python implementation modules, and browser test hooks
remain internal; they do not extend the catalog's stable JSON schema or `--json`
sidecar contract. There is no lineage JSON sidecar option.

From a checkout, run `uv run cja-lineage` with the same arguments. The earlier
`scripts/generate_cja_lineage_poc.py` remains a private fixed-filename development
driver; use the installed command for supported use. `visualize-*.html` remains
ignored, including the private live-review artifact.

Run the focused tests and synthetic performance gate before live acquisition:

```bash
uv run pytest tests/test_lineage_cli.py tests/test_cja_lineage.py \
  tests/test_lineage_discovery.py tests/test_lineage_renderer.py
uv run pytest tests/test_lineage_browser.py
uv run python scripts/perf_lineage_poc.py
```

Release review also needs full Python coverage, browser/performance gates,
isolated wheel and sdist smoke checks, and a visual/assistive-technology pass.
Automated assertions do not certify visual appearance or actual screen-reader use.
