"""Capture the README slideshow. See docs/SHOWCASE.md for reproduction.

Reads only bundled synthetic fixtures. Requires Playwright Chromium and FFmpeg.
Run: uv run python scripts/capture_screenshot.py --output-dir /tmp/showcase
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from sdr_visualizer.analysis.diff import diff_implementations
from sdr_visualizer.analysis.trend import build_trend
from sdr_visualizer.core.visualizer import build_implementation
from sdr_visualizer.render.renderer import build_payload_with_options, render_payload

REPO = Path(__file__).resolve().parent.parent
FPS = 8
SCENES = [
    (
        "Find the component",
        "Your catalog.<br>In focus.",
        "Search names, descriptions, and formulas. Filter the inventory to find the component you need.",
        "CJA example · Search + filters<br>Metrics, dimensions, segments & more",
        "cja-catalog",
        4.5,
    ),
    (
        "Follow the references",
        "See what<br>connects.",
        "Explore direct component dependencies. Highlight a node to see its connections in the snapshot.",
        "CJA example · Reference graph<br>Direct dependencies, made visible",
        "cja-references",
        4.5,
    ),
    (
        "Read the logic",
        "Complex logic.<br>Made legible.",
        "Unpack segment containers and calculated-metric formulas. Follow references into component details.",
        "AA example · Segment + formula<br>Structured anatomy, linked references",
        "aa-anatomy",
        5,
    ),
    (
        "Compare snapshots",
        "Know what<br>changed.",
        "See additions, removals, and edits between snapshots. Expand a component to compare its fields.",
        "CJA example · Same data view<br>Before → after, field by field",
        "cja-changes",
        5,
    ),
    (
        "Follow the history",
        "A snapshot.<br>A longer view.",
        "Track component counts and reference patterns over time. Inspect the changes between each snapshot.",
        "CJA example · Four synthetic snapshots<br>Inventory trends + interval changes",
        "cja-trend",
        5,
    ),
    (
        "Open it anywhere",
        "One report.<br>Ready offline.",
        "Open the self-contained HTML in a browser. Review your AA or CJA catalog without a server or internet connection.",
        "AA example · Embedded HTML + JSON<br>No server · No CDN · No browser fetches",
        "aa-catalog",
        4.5,
    ),
]


def fixture(name):
    return json.loads((REPO / "tests/fixtures" / name).read_text(encoding="utf-8"))


def reports():
    cja = fixture("cja_snapshot_messy.json")
    history = []
    # Same-instance synthetic history; never compare unrelated implementations.
    for index, count in enumerate((166, 170, 174, len(cja["metrics"]))):
        snapshot = copy.deepcopy(cja)
        snapshot["metadata"]["Generation Timestamp"] = f"2026-04-{index + 22:02d} 09:14:00"
        snapshot["metrics"] = snapshot["metrics"][:count]
        revenue = next(m for m in snapshot["metrics"] if m["id"] == "metrics/revenue")
        revenue["description"] = (
            "Revenue from completed orders."
            if index < 3
            else "Revenue from completed orders, excluding refunds."
        )
        if index == 3:
            snapshot["metrics"] = [
                m for m in snapshot["metrics"] if m["id"] != "metrics/cm_metric_001"
            ]
        history.append(build_implementation(snapshot, source=f"synthetic-history-{index + 1}.json"))
    payload = build_payload_with_options(history[-1])
    payload["changes"] = diff_implementations(history[-2], history[-1])
    payload["meta"]["compared_to"] = payload["changes"]["baseline"]
    payload["trend"] = build_trend(history, capped=False)
    result = {"history": render_payload(payload)}
    for key, name in (
        ("cja", "cja_snapshot_messy.json"),
        ("aa", "aa_snapshot_messy.json"),
        ("graph", "cja_snapshot_clean.json"),
    ):
        result[key] = render_payload(
            build_payload_with_options(build_implementation(fixture(name)))
        )
    return result


def excerpt(page, selectors):
    return page.evaluate(
        """selectors => ({
      css: document.querySelector('style').textContent,
      html: selectors.map(selector => {
        const el = document.querySelector(selector);
        if (!el) throw new Error(`Missing excerpt: ${selector}`);
        const clone = el.cloneNode(true);
        el.querySelectorAll('input').forEach((input,i) => {
          const target = clone.querySelectorAll('input')[i];
          target.setAttribute('value',input.value);
          if (input.type === 'checkbox') target.toggleAttribute('checked',input.checked);
        });
        clone.removeAttribute('hidden');
        if (selector === '#graph-stage') {
          const svg = clone.querySelector('svg');
          const nodes = Array.from(el.querySelectorAll('.graph-node:not(.is-faded)'));
          const boxes = nodes.map(n => { const p = n.__data__; const b = n.getBBox(); return {x:p.x,y:p.y,w:b.width,h:b.height}; });
          const x = Math.min(...boxes.map(b=>b.x))-40;
          const y = Math.min(...boxes.map(b=>b.y))-40;
          const right = Math.max(...boxes.map(b=>b.x+b.w))+40;
          const bottom = Math.max(...boxes.map(b=>b.y+b.h))+40;
          svg.setAttribute('viewBox',`${x} ${y} ${right-x} ${bottom-y}`);
        }
        if (selector === '#trend-log') {
          Array.from(clone.children).slice(0,-1).forEach(child=>child.remove());
        }
        return clone.outerHTML;
      }).join('\\n')
    })""",
        selectors,
    )


def capture(output):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required; see docs/SHOWCASE.md")
    output.mkdir(parents=True, exist_ok=True)
    html = reports()
    with tempfile.TemporaryDirectory(prefix="visualizer-showcase-") as temporary:
        frames = Path(temporary)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1000, "height": 720})
                page.route("**/*", lambda route: route.abort())
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                scenes = []

                def load(content):
                    page.goto("about:blank")
                    page.set_content(content)

                load(html["cja"])
                page.fill("#search-input", "revenue")
                page.wait_for_function(
                    "document.querySelector('#result-count').textContent.includes(' of ')"
                )
                for control in page.locator('#type-filter input:not([value="metric"])').all():
                    value = control.get_attribute("value")
                    page.locator(f'#type-filter label.chip:has(input[value="{value}"])').click()
                page.wait_for_function(
                    "document.querySelector('#result-count').textContent === '2 of 575'"
                )
                scenes.append(excerpt(page, [".meta-strip", ".catalog-controls", ".catalog-table"]))
                load(html["graph"])
                page.click('[data-view="graph"]')
                page.wait_for_selector(".graph-node")
                page.evaluate("""() => {
                  const nodes = Array.from(document.querySelectorAll('.graph-node'));
                  nodes.find(n => n.textContent.includes('Cm Clean Ratio A'))
                    .dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
                }""")
                page.wait_for_selector(".graph-node.is-hover")
                scenes.append(excerpt(page, [".graph-controls", ".reference-help", "#graph-stage"]))
                load(html["aa"])
                details = []
                for component_id in ("s_returning", "cm_revenue_per_visit"):
                    page.locator(f'#catalog-body tr[data-id="{component_id}"]').click()
                    page.wait_for_selector("#detail-panel.is-open")
                    details.append(
                        excerpt(
                            page,
                            [
                                ".detail-eyebrow",
                                ".detail-name",
                                ".detail-section:has(.anatomy), .detail-section:has(.formula-tree)",
                            ],
                        )
                    )
                    page.click("#detail-close")
                scenes.append(
                    dict(
                        css=details[0]["css"],
                        html="".join(
                            f'<div class="logic-excerpt">{d["html"]}</div>' for d in details
                        ),
                    )
                )
                load(html["history"])
                page.click('[data-view="changes"]')
                page.locator("details.change-modified").filter(has_text="Revenue").locator(
                    "summary"
                ).click()
                scenes.append(excerpt(page, [".changes-header", "#changes-body"]))
                page.click('[data-view="trend"]')
                scenes.append(
                    excerpt(
                        page, [".trend-charts", "#trend-view .change-group-title", "#trend-log"]
                    )
                )
                load(html["aa"])
                page.fill("#search-input", "revenue")
                page.wait_for_function(
                    "document.querySelector('#result-count').textContent.includes(' of ')"
                )
                scenes.append(
                    excerpt(page, [".brand", ".meta-strip", ".catalog-controls", ".catalog-table"])
                )
                page.set_viewport_size({"width": 1120, "height": 720})
                page.set_content((REPO / "docs/assets/showcase.html").read_text(encoding="utf-8"))
                page.evaluate(
                    """scenes => {
                  for (const scene of scenes) {
                    const el = document.createElement('div'); el.className = 'scene'; el.dataset.scene = scene.filename;
                    el.innerHTML = `<div class="story"><div class="kicker">${scene.kicker}</div><h1>${scene.title}</h1><p class="description">${scene.description}</p><div class="proof">${scene.proof}</div></div><div class="window"><div class="window-bar"><i class="dot"></i><i class="dot"></i><i class="dot"></i><span class="filename">${scene.filename}</span></div><div class="excerpt"></div></div>`;
                    const shadow = el.querySelector('.excerpt').attachShadow({mode:'open'});
                    shadow.innerHTML = `<style>${scene.css.replaceAll(':root[data-color-pack="default"]', ':host').replaceAll(':root', ':host')}
                      :host { display:block; color:var(--sdr-text-primary); background:var(--sdr-surface-page); font:16px/1.55 "Charter","Iowan Old Style","Source Serif Pro",Georgia,serif; }
                      .meta-strip { margin-bottom:22px; flex-wrap:wrap; }
                      .catalog-table .col-owner, .catalog-table .col-modified, .catalog-table .col-tags { display:none; }
                      .catalog-table { table-layout:fixed; width:100%; }
                      .catalog-table .col-name { width:38%; }
                      .catalog-table .col-type { width:19%; }
                      .catalog-table .col-description { width:35%; }
                      .catalog-table .col-refs { width:8%; }
                      .catalog-table td { overflow-wrap:anywhere; padding:10px 8px; }
                      .catalog-table th { padding:10px 8px; }
                      .catalog-table tbody tr:nth-child(n+4) { display:none; }
                      .catalog-controls { gap:10px; margin-bottom:10px; padding-bottom:10px; }
                      .filter-row { gap:12px; }
                      .filter-group { gap:4px; }
                      .reference-help { margin:8px 0; }
                      .logic-excerpt { display:inline-block; width:48%; vertical-align:top; }
                      .logic-excerpt + .logic-excerpt { margin:0 0 0 4%; padding:0; border:0; }
                      .trend-chart svg { width:100%; height:32px; }
                      .trend-chart { padding:10px; }
                      .trend-chart-values { margin-top:0; }
                      .trend-charts { padding-bottom:14px; }
                      .catalog-table .row-id { font-size:10px; }
                      .graph-stage { height:255px; min-height:0; }
                      #graph-canvas { height:255px; }
                      .detail-name { font-size:24px; margin:6px 0 12px; }
                      .detail-section { margin:12px 0; }
                      .brand h1 { font-size:30px; margin:4px 0 10px; }
                      .brand { margin-bottom:20px; }
                      .trend-charts { grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
                    </style>${scene.html}`;
                    if (scene.filename.startsWith('aa-catalog')) shadow.querySelector('.filter-row').remove();
                    document.querySelector('#scenes').append(el);
                  }
                }""",
                    [
                        dict(
                            kicker=f"{i + 1:02d} / {s[0]}",
                            title=s[1],
                            description=s[2],
                            proof=s[3],
                            filename=s[4] + ".html · excerpt",
                            **content,
                        )
                        for i, (s, content) in enumerate(zip(SCENES, scenes, strict=True))
                    ],
                )
                total = round(sum(s[5] for s in SCENES) * FPS)
                frame = 0
                for index, spec in enumerate(SCENES):
                    for tick in range(round(spec[5] * FPS)):
                        page.evaluate(
                            """({index,tick,frame,total}) => {
                          document.querySelectorAll('.scene').forEach((el,i) => {
                            el.style.visibility = i === index ? 'visible' : 'hidden';
                            el.style.transform = `translateY(${tick < 3 ? (3-tick)*2 : 0}px)`;
                          });
                          document.querySelectorAll('.steps span').forEach((el,i) => el.classList.toggle('active',i===index));
                          document.querySelector('.progress').style.transform = `scaleX(${(frame+1)/total})`;
                        }""",
                            dict(index=index, tick=tick, frame=frame, total=total),
                        )
                        page.screenshot(path=str(frames / f"{frame:04d}.png"))
                        if tick == 3:
                            page.screenshot(path=str(output / f"showcase-scene-{index + 1}.png"))
                        frame += 1
                if errors:
                    raise RuntimeError(f"Browser errors during capture: {errors}")
            finally:
                browser.close()
        shutil.copyfile(output / "showcase-scene-1.png", output / "screenshot-catalog.png")
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(FPS),
                "-i",
                str(frames / "%04d.png"),
                "-filter_complex",
                "[0:v]split[a][b];[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=none:diff_mode=rectangle",
                "-loop",
                "0",
                str(output / "screenshot-catalog.gif"),
            ],
            check=True,
        )
    print(f"Wrote {output / 'screenshot-catalog.gif'} ({total / FPS:g}s, {total} frames)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=REPO / "docs")
    capture(parser.parse_args().output_dir)


if __name__ == "__main__":
    main()
