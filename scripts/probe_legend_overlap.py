"""Headless probe: gender-legend ↔ stats-section geometry.

Drives chromium against the running localhost stack: dismisses the
first-launch disclosure, uploads ``zh_30s.wav``, clicks #analyze-btn,
waits for #phone-timeline-root to populate, and measures the bounding
rects of the legend, the timeline, and stats. Now sweeps a 4 × 3 grid
of (viewport × DPR) so we can see whether 女声方向 "swallowing" is a
real overlap, a clipped/collapsed grid (squeezed three-panel layout),
a media-query gap shrink, or DPR-dependent sub-pixel rendering.

Outputs (under ``tests/reports/legend_probe/``):
  - ``<viewport>_dpr<n>_t{0,1}.png`` — viewport screenshot per state
  - ``<viewport>_dpr<n>_full.png``   — full-page screenshot
  - ``report.json``                  — per-state metrics + console log

Run: uv run python scripts/probe_legend_overlap.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
# Local dev runs vite on 5173 with /api/* proxied to the uvicorn backend on
# 8080. The 8080 instance only ships the JSON `root()` (its web_dir has no
# `assets/` subdir in repo layout), so we go through vite for the SPA.
BASE = "http://localhost:5173"
FIXTURE = REPO / "tests/fixtures/audio/zh_30s.wav"
OUT = REPO / "tests/reports/legend_probe"
OUT.mkdir(parents=True, exist_ok=True)

# Widths picked to match the user's three reproduction screenshots:
#   140424.png ≈ 497 (mobile single column)
#   140436.png ≈ 660 (squeezed three-panel — labels go missing here)
#   140429.png ≈ 837 (narrow desktop — labels look glued to stats)
# Plus 1280 baseline.
VIEWPORTS = [
    ("mobile", 497, 880),
    # The 200px-1fr-270px three-panel rule fires at 780–1000.  Sweep this band
    # densely — center panel = viewport − 470, so it shrinks fast as we
    # approach the 780 floor.
    ("tri_790", 790, 740),
    ("tri_820", 820, 740),
    ("tri_870", 870, 740),
    ("tri_920", 920, 740),
    ("tri_980", 980, 740),
    ("desktop", 1280, 900),
]
DPRS = [1.0]
# Chinese locale: user reproduces 140436 with the 中 button active.  zh
# labels (男声方向 / 中性 / 女声方向) have very different metrics from EN.
LOCALES = ["zh-CN", "en-US"]

PROBE_JS = """() => {
    const r = (el) => el ? el.getBoundingClientRect().toJSON() : null;
    // Glyph (inline-text-box) bottom — the real bottom of rendered characters,
    // not the row's content box. Catches the case where line-height is tight
    // but the layout-box bottom still reads as "above" the next sibling while
    // glyphs visually clip into it.
    const inlineBottom = (el) => {
        if (!el) return null;
        const rects = el.getClientRects ? Array.from(el.getClientRects()) : [];
        if (!rects.length) return el.getBoundingClientRect().bottom;
        return Math.max(...rects.map(r => r.bottom));
    };
    const isVisible = (el) => {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        if (rect.width < 4 || rect.height < 4) return false;
        if (el.offsetParent === null && getComputedStyle(el).position !== 'fixed') return false;
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
        return true;
    };
    const isClipped = (el) => {
        if (!el) return false;
        return el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
    };
    const t = document.getElementById('phone-timeline-root');
    const s = document.getElementById('stats-section');
    const legend = document.querySelector('.vga-gender-legend');
    const barWrap = document.querySelector('.vga-gender-legend__bar-wrap');
    const labelsRow = document.querySelector('.vga-gender-legend__labels');
    const right = document.querySelector('.vga-gender-legend__label--right');
    const mid = document.querySelector('.vga-gender-legend__label--mid');
    const left = document.querySelector('.vga-gender-legend__label--left');
    const footer = document.querySelector('.vga-timeline__footer');
    const panelCenter = document.querySelector('.panel-center');
    const panelLeft = document.querySelector('.panel-left, .past-sessions');
    const panelRight = document.querySelector('.panel-right');
    const cs = (el, keys) => el ? Object.fromEntries(
        keys.map(k => [k, getComputedStyle(el)[k]])
    ) : null;
    const statsRect = s ? s.getBoundingClientRect() : null;
    const statsTop = statsRect ? statsRect.top : null;
    const labelsRowBottom = labelsRow ? labelsRow.getBoundingClientRect().bottom : null;
    const rightTextBottom = inlineBottom(right);
    const midTextBottom = inlineBottom(mid);
    const leftTextBottom = inlineBottom(left);
    const labelsTextBottom = Math.max(
        rightTextBottom ?? -Infinity,
        midTextBottom ?? -Infinity,
        leftTextBottom ?? -Infinity
    );
    return {
        // Layout state
        bodyWidth: document.documentElement.clientWidth,
        dpr: window.devicePixelRatio,
        panelLeftVisible: isVisible(panelLeft),
        panelRightVisible: isVisible(panelRight),
        panelCenter: r(panelCenter),
        // Geometry rects
        timeline: r(t), stats: r(s),
        legend: r(legend), barWrap: r(barWrap), labelsRow: r(labelsRow),
        rightLabel: r(right), midLabel: r(mid), leftLabel: r(left),
        footer: r(footer),
        rightTextBottom, midTextBottom, leftTextBottom,
        // Visibility / clip booleans (the smoking gun for F1/F2)
        labels_visible: {
            left: isVisible(left), mid: isVisible(mid), right: isVisible(right),
        },
        labels_clipped: {
            left: isClipped(left), mid: isClipped(mid), right: isClipped(right),
        },
        gradient_bar_height: barWrap ? barWrap.getBoundingClientRect().height : null,
        // Critical gaps. Negative = visual overlap.
        statsTop_minus_legendBottom: legend && s
            ? statsTop - legend.getBoundingClientRect().bottom : null,
        statsTop_minus_labelsRowBottom: labelsRow && s
            ? statsTop - labelsRowBottom : null,
        statsTop_minus_labelsTextBottom: (labelsTextBottom !== -Infinity && s)
            ? statsTop - labelsTextBottom : null,
        statsTop_minus_footerBottom: footer && s
            ? statsTop - footer.getBoundingClientRect().bottom : null,
        // Computed styles for context
        labelsCS: cs(labelsRow, ['display','grid-template-columns','line-height',
                                 'padding-top','padding-bottom','font-size','height','overflow']),
        legendCS: cs(legend, ['display','min-height','overflow']),
        panelCenterCS: cs(panelCenter, ['gap','row-gap','padding','width']),
        statsCS: cs(s, ['min-height','margin-top','transform','contain']),
    };
}"""


def run_one(p, name: str, w: int, h: int, dpr: float, lang: str) -> dict:
    lang_short = lang.split("-")[0]
    tag = f"{name}_{lang_short}_dpr{dpr:.1f}".replace(".", "_")
    print(f"[{tag}] {w}×{h} @ {dpr}× lang={lang} launching chromium …", flush=True)
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        viewport={"width": w, "height": h},
        device_scale_factor=dpr,
    )
    ctx.add_init_script(
        f"""try {{
            localStorage.setItem('vga.disclosureAcked.v1', '1');
            localStorage.setItem('vga.lang', {json.dumps(lang_short)});
        }} catch (e) {{}}"""
    )
    page = ctx.new_page()
    console: list[str] = []
    page.on("console", lambda msg: console.append(f"[{msg.type}] {msg.text[:200]}"))
    page.on("pageerror", lambda e: console.append(f"[err] {e!r}"))

    page.goto(BASE, wait_until="load")
    page.wait_for_load_state("networkidle", timeout=10_000)

    has_input = page.evaluate("() => !!document.getElementById('file-input')")
    if not has_input:
        page.screenshot(path=str(OUT / f"{tag}_no_input.png"), full_page=True)
        browser.close()
        return {"viewport": {"name": name, "w": w, "h": h, "dpr": dpr, "lang": lang},
                "error": "no-file-input", "console": console}

    page.evaluate(
        "() => { const f = document.getElementById('file-input'); if (f) f.hidden = false; }"
    )
    page.set_input_files("#file-input", str(FIXTURE))

    try:
        analyze = page.locator("#analyze-btn")
        analyze.wait_for(state="visible", timeout=5000)
        page.wait_for_function(
            "() => !document.getElementById('analyze-btn').disabled", timeout=10_000
        )
        analyze.click()
    except PWTimeout as e:
        console.append(f"[probe] analyze trigger failed: {e}")

    try:
        page.wait_for_selector("#phone-timeline-root:not([hidden])", timeout=180_000)
        page.wait_for_selector(".vga-gender-legend", timeout=20_000)
        print(f"[{tag}] timeline rendered", flush=True)
    except PWTimeout as e:
        console.append(f"[probe] timeline wait failed: {e}")
        page.screenshot(path=str(OUT / f"{tag}_failed.png"), full_page=True)
        browser.close()
        return {"viewport": {"name": name, "w": w, "h": h, "dpr": dpr, "lang": lang},
                "error": "timeline-timeout", "console": console}

    # t0: mid-fadeUp (no settling)
    page.evaluate(
        "() => document.querySelector('.vga-gender-legend')?.scrollIntoView({block: 'center'})"
    )
    metrics_t0 = page.evaluate(PROBE_JS)
    page.screenshot(path=str(OUT / f"{tag}_t0.png"), full_page=False)

    # t1: settled
    time.sleep(1.5)
    page.evaluate(
        "() => document.querySelector('.vga-gender-legend')?.scrollIntoView({block: 'center'})"
    )
    time.sleep(0.2)
    metrics_t1 = page.evaluate(PROBE_JS)
    page.screenshot(path=str(OUT / f"{tag}_t1.png"), full_page=False)
    page.screenshot(path=str(OUT / f"{tag}_full.png"), full_page=True)

    browser.close()
    return {
        "viewport": {"name": name, "w": w, "h": h, "dpr": dpr, "lang": lang},
        "metrics_t0": metrics_t0,
        "metrics_t1": metrics_t1,
        "console": console[-15:],
    }


def classify(m: dict) -> str:
    """Map metrics to F1/F2/F3/F4/OK."""
    if m is None:
        return "—"
    vis = m.get("labels_visible") or {}
    clip = m.get("labels_clipped") or {}
    bar_h = m.get("gradient_bar_height") or 0
    gap = m.get("statsTop_minus_labelsTextBottom")
    if not (vis.get("left") and vis.get("mid") and vis.get("right")):
        return "F1-hidden"
    if bar_h is not None and bar_h < 5:
        return "F1-collapsed"
    if any(clip.values()):
        return "F2-clipped"
    if gap is not None and gap < 8:
        return "F3-tight"
    return "OK"


def main() -> int:
    if not FIXTURE.is_file():
        print(f"missing fixture: {FIXTURE}")
        return 2
    runs: list[dict] = []
    with sync_playwright() as p:
        for lang in LOCALES:
            for n, w, h in VIEWPORTS:
                for dpr in DPRS:
                    runs.append(run_one(p, n, w, h, dpr, lang))

    (OUT / "report.json").write_text(json.dumps(runs, indent=2, ensure_ascii=False))
    print("\n=== summary (label gap, vis = L/M/R visible, clip = any clipped) ===")
    print(
        f"  {'viewport':>10}  {'lang':>4}  {'pcW':>5}  {'phase':>4}  {'gap':>6}  "
        f"{'rowH':>5}  {'barH':>5}  {'vis':>5}  {'clip':>4}  {'class':>13}"
    )
    for r in runs:
        if "error" in r:
            v = r["viewport"]
            print(f"  {v['name']:>10}  {v.get('lang','?'):>4}  ERR: {r['error']}")
            continue
        v = r["viewport"]
        for phase in ("t0", "t1"):
            m = r.get(f"metrics_{phase}") or {}
            gap = m.get("statsTop_minus_labelsTextBottom")
            bar = m.get("gradient_bar_height")
            vis = m.get("labels_visible") or {}
            clip = m.get("labels_clipped") or {}
            row = (m.get("labelsRow") or {}).get("height")
            pc = (m.get("panelCenter") or {}).get("width")
            vis_str = "".join("Y" if vis.get(k) else "n" for k in ("left", "mid", "right"))
            clip_str = "Y" if any(clip.values()) else "n"
            cls = classify(m)
            gap_s = f"{gap:.1f}" if isinstance(gap, (int, float)) else "—"
            bar_s = f"{bar:.1f}" if isinstance(bar, (int, float)) else "—"
            row_s = f"{row:.1f}" if isinstance(row, (int, float)) else "—"
            pc_s = f"{pc:.0f}" if isinstance(pc, (int, float)) else "—"
            lang_s = (v.get("lang") or "").split("-")[0]
            print(
                f"  {v['name']:>10}  {lang_s:>4}  {pc_s:>5}  {phase:>4}  {gap_s:>6}  "
                f"{row_s:>5}  {bar_s:>5}  {vis_str:>5}  {clip_str:>4}  {cls:>13}"
            )
    print(f"\n[report] {OUT.relative_to(REPO)}/report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
