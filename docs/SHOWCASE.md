# README slideshow

The [README](../README.md) uses `screenshot-catalog.gif`, a 28.5-second loop with a
clickable `screenshot-catalog.png` still alternative. The editorial frame matches
the sdr-grader slideshow: 1120 × 720 pixels, warm ink background, cream serif
headlines, teal accents, browser-window excerpts, numbered steps, and a progress
line. It uses the same Charter / Iowan Old Style / Source Serif Pro / Georgia,
Söhne / Inter / system UI, and JetBrains Mono / SF Mono / Menlo font stacks.

AA and CJA are supported platforms throughout the story, rather than separate
features. All excerpt content comes from the real renderer and bundled synthetic
fixtures. The frame is documentation artwork, not a product interface.

| Scene | Source | What it shows |
| --- | --- | --- |
| Catalog | `cja_snapshot_messy.json` | Revenue search, filters, counts, matching components |
| References | `cja_snapshot_clean.json` | Direct dependency graph focused on a calculated metric and its neighbors |
| Anatomy | `aa_snapshot_messy.json` | Returning Visitors segment containers and Revenue per Visit formula |
| Changes | Copies of `cja_snapshot_messy.json` | Same-instance additions, removal, expanded description edit |
| Trend | The same four synthetic history copies | Inventory charts and changes between snapshots |
| Offline | `aa_snapshot_messy.json` | AA catalog in the same self-contained report format |

The history uses four copies of one CJA fixture, dated April 22–25, 2026. The
copies vary metric counts, edit Revenue's description, and remove one metric.
They demonstrate comparison and trend behavior, not a real implementation's
history. No customer data, credentials, live collection, or Adobe API is used.
Browser network requests are blocked during capture.

The report excerpts retain their text and stylesheet inside isolated shadow
roots. Artwork-only overrides compact spacing, chart layout, and graph height.
The graph excerpt zooms to the hovered node's neighborhood. Catalog excerpts
show up to three matches and omit Tags, Modified, and Owner columns; the offline
scene omits the filter row. Trend shows all nine charts and the final interval.
Complete reports retain every column, row, and interval.

## Regenerate

Install FFmpeg separately, then use the repository's existing browser tooling:

```sh
uv sync --locked --group browser
uv run playwright install chromium
uv run python scripts/capture_screenshot.py --output-dir /tmp/visualizer-showcase
```

Inspect all six `showcase-scene-*.png` previews and the encoded GIF. Verify text
and diagrams fit, all features are represented, and the animation loops. Then
copy only `screenshot-catalog.gif` and `screenshot-catalog.png` into `docs/`.
Individual scene PNGs are inspection outputs and should not be committed.
Temporary animation frames are removed automatically. FFmpeg, Chromium, and
available local fonts can affect the raster bytes. No new runtime dependency is
required. Product HTML examples are unchanged by this documentation-only capture.
