"""Render advice v2 over all manifest fixtures and write a markdown report.

Drives the same code path as the production pipeline (Engine A → advice_v2),
without spinning up FastAPI / Taskiq / SSE. One section per sample with both
zh-CN and en-US text rendered for human review.

Usage:
    .venv/bin/python tests/render_advice_v2.py
    # → tests/reports/advice_v2_render_<YYYY-MM-DD>.md

Outputs are not asserted automatically — see docs/plans/v2_redesign_measurement.md §9
for the human-review checklist (silent-failure cases, sanity checks, gating).
"""

from __future__ import annotations

import datetime
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import yaml  # noqa: E402

from voiceya.services.audio_analyser.advice_v2 import compute_advice  # noqa: E402
from voiceya.services.audio_analyser.seg_analyser import AnalyseResultItem  # noqa: E402

MANIFEST = ROOT / "tests/fixtures/manifest.yaml"
REPORT_DIR = ROOT / "tests/reports"

# i18n templates kept in sync with web/src/modules/i18n.js. The renderer
# reproduces them so the report shows what users will read; if these drift
# from i18n.js, fix both at once.
ZONE_LABELS = {
    "low": ("低基频", "Low"),
    "mid_lower": ("中低基频", "Mid-low"),
    "mid_neutral": ("声学中性区间", "Acoustically neutral"),
    "mid_upper": ("中高基频", "Mid-high"),
    "high": ("高基频", "High"),
}

TONE_LABELS = {
    "leans_feminine": ("倾向偏女", "Leans feminine"),
    "leans_masculine": ("倾向偏男", "Leans masculine"),
    "weakly_feminine": ("轻微偏女", "Slightly feminine"),
    "weakly_masculine": ("轻微偏男", "Slightly masculine"),
    "not_clearly_leaning": ("倾向不明显", "Not clearly leaning"),
}

CAVEAT_ZH = (
    "声学性别分类主要由音高 (F0) 驱动，在 165–200 Hz 区间无法可靠区分男女声。"
    "共振峰、音色等特征本系统暂未纳入。"
    "本结果仅为粗略声学倾向，不应作为性别判断的唯一依据。"
)
CAVEAT_EN = (
    "Voice gender classification here is primarily F0-driven and does not "
    "reliably distinguish male and female voices in the 165–200 Hz range. "
    "Resonance and timbre features are not yet incorporated. This is a rough "
    "acoustic tendency only — not a basis for gender determination."
)

WARNING_ZH = {
    "advice.warning.short_recording_minimal": (
        "录音少于 10 秒，仅显示原始测量值。tonal 倾向需 10 秒以上录音。"
    ),
    "advice.warning.short_recording_standard": (
        "录音较短（{duration} 秒），结果稳定性有限。建议录制 30 秒以上以获得稳定结果。"
    ),
}
WARNING_EN = {
    "advice.warning.short_recording_minimal": (
        "Recording is under 10 seconds; only raw measurements are shown. "
        "Tonal tendency requires 10 s+."
    ),
    "advice.warning.short_recording_standard": (
        "Recording is short ({duration} s); result stability is limited. "
        "30 s+ recommended for stable output."
    ),
}

SUMMARY_ZH = "F0 中位数 {f0} Hz，{zone_clause}。{tone_text}"
SUMMARY_EN = "F0 median {f0} Hz, {zone_clause_en}. {tone_text_en}"

ZONE_CLAUSES_ZH = {
    "low": "位于低基频区间",
    "mid_lower": "位于中低基频区间",
    "mid_neutral": "处于声学中性区间",
    "mid_upper": "位于中高基频区间",
    "high": "位于高基频区间",
}
ZONE_CLAUSES_EN = {
    "low": "low range",
    "mid_lower": "mid-low range",
    "mid_neutral": "acoustically neutral range",
    "mid_upper": "mid-high range",
    "high": "high range",
}
TONE_TEXT_ZH = {
    "leans_feminine": "声学倾向偏女。",
    "leans_masculine": "声学倾向偏男。",
    "weakly_feminine": "声学轻微偏女。",
    "weakly_masculine": "声学轻微偏男。",
    "not_clearly_leaning": "倾向不明显。",
}
TONE_TEXT_EN = {
    "leans_feminine": "Leans feminine",
    "leans_masculine": "Leans masculine",
    "weakly_feminine": "Slightly feminine",
    "weakly_masculine": "Slightly masculine",
    "not_clearly_leaning": "Not clearly leaning",
}


def _render_summary(advice: dict) -> tuple[str, str]:
    sp = advice.get("summary_panel")
    if not sp:
        return ("(无 summary)", "(no summary)")
    f0 = sp["text_params"]["f0"]
    # Parse "advice.summary.<zone>_<tendency>"
    parts = sp["text_key"].split(".")[-1]  # "<zone>_<tendency>"
    for tend in (
        "leans_feminine",
        "leans_masculine",
        "weakly_feminine",
        "weakly_masculine",
        "not_clearly_leaning",
    ):
        if parts.endswith("_" + tend):
            zone = parts[: -(len(tend) + 1)]
            zh = f"F0 中位数 {f0} Hz，{ZONE_CLAUSES_ZH[zone]}。{TONE_TEXT_ZH[tend]}"
            en = f"F0 median {f0} Hz, {ZONE_CLAUSES_EN[zone]}. {TONE_TEXT_EN[tend]}."
            return zh, en
    return (sp["text_key"], sp["text_key"])


def _render_warnings(advice: dict) -> list[tuple[str, str]]:
    out = []
    for w in advice.get("warnings", []):
        params = w.get("params") or {}
        zh = WARNING_ZH.get(w["key"], w["key"]).format(**params)
        en = WARNING_EN.get(w["key"], w["key"]).format(**params)
        out.append((zh, en))
    return out


def _engine_a_run(seg, audio_path: Path) -> list[AnalyseResultItem]:
    """Run Engine A on a 16 kHz mono float64 wav. Returns analyse_results."""
    raw = seg(str(audio_path))
    items: list[AnalyseResultItem] = []
    for tup in raw:
        label = tup[0]
        start = float(tup[1])
        end = float(tup[2])
        conf = float(tup[3]) if len(tup) > 3 and tup[3] is not None else None
        items.append(
            AnalyseResultItem(
                label=label,
                start_time=start,
                end_time=end,
                duration=round(end - start, 3),
                confidence=conf,
                confidence_frames=None,
                acoustics=None,
            )
        )
    return items


def _dominant_label(items: list[AnalyseResultItem]) -> str | None:
    fem = sum(r.duration for r in items if r.label == "female")
    mal = sum(r.duration for r in items if r.label == "male")
    if fem == 0 and mal == 0:
        return None
    return "female" if fem >= mal else "male"


def _load_audio(path: Path) -> tuple[np.ndarray, int]:
    y, sr = sf.read(str(path))
    if y.ndim > 1:
        y = y.mean(axis=1)
    return y.astype(np.float32), int(sr)


def _slugify(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def _format_section(entry: dict, advice: dict, items: list[AnalyseResultItem]) -> str:
    f0 = advice["f0_panel"]
    tone = advice.get("tone_panel")
    summary_zh, summary_en = _render_summary(advice)
    warnings = _render_warnings(advice)

    zh_zone = ZONE_LABELS.get(f0.get("range_zone_key"), ("—", "—"))[0]
    en_zone = ZONE_LABELS.get(f0.get("range_zone_key"), ("—", "—"))[1]

    lines: list[str] = []
    lines.append(f"### {entry['name']}")
    lines.append("")
    lines.append(
        f"- **category**: `{entry['category']}` · "
        f"**ground_truth**: `{entry['true_label']}` · "
        f"**manifest F0**: {entry['f0']} Hz · "
        f"**duration**: {advice['recording_duration_sec']:.1f} s"
    )
    lines.append(
        f"- **gating_tier**: `{advice['gating_tier']}` · "
        f"**dominant_label** (Engine A): `{_dominant_label(items)}`"
    )
    lines.append("")
    lines.append("**f0_panel**")
    lines.append("")
    lines.append("```json")
    lines.append(_json(f0))
    lines.append("```")
    lines.append("")
    if f0.get("reliability") == "ok":
        lines.append(f"→ F0 zone: `{f0['range_zone_key']}` ({zh_zone} / {en_zone})")
    else:
        lines.append(f"→ reliability: `{f0.get('reliability')}` (no zone label)")
    lines.append("")

    if tone:
        zh_tone, en_tone = TONE_LABELS[tone["tone_tendency_key"]]
        dist = tone["ina_label_distribution"]
        lines.append("**tone_panel**")
        lines.append("")
        lines.append(f"- tendency: `{tone['tone_tendency_key']}` ({zh_tone} / {en_tone})")
        lines.append(
            f"- ina label distribution: female {dist['female_frame_ratio']:.0%}, "
            f"male {dist['male_frame_ratio']:.0%}, "
            f"other {dist['other_frame_ratio']:.0%}"
        )
        lines.append("")
        lines.append("Caveat (zh-CN):")
        lines.append("")
        lines.append(f"> {CAVEAT_ZH}")
        lines.append("")
        lines.append("Caveat (en-US):")
        lines.append("")
        lines.append(f"> {CAVEAT_EN}")
        lines.append("")
    else:
        lines.append("**tone_panel**: hidden (minimal tier)")
        lines.append("")

    lines.append("**summary_panel**")
    lines.append("")
    lines.append(f"- zh-CN: {summary_zh}")
    lines.append(f"- en-US: {summary_en}")
    lines.append("")

    if warnings:
        lines.append("**warnings**")
        lines.append("")
        for zh, en in warnings:
            lines.append(f"- zh-CN: {zh}")
            lines.append(f"- en-US: {en}")
        lines.append("")

    lines.append("**Manual review** (fill in):")
    lines.append("")
    lines.append("- Y/N: ___")
    lines.append("- Notes: ___")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _json(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, indent=2)


def main() -> int:
    if not MANIFEST.exists():
        print(f"missing manifest: {MANIFEST}", file=sys.stderr)
        return 1

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    out_path = REPORT_DIR / f"advice_v2_render_{today}.md"

    with open(MANIFEST) as fh:
        data = yaml.safe_load(fh)

    samples = []
    for item in data.get("samples", []):
        path = MANIFEST.parent / item["filename"]
        if not path.exists():
            print(f"  [skip] {item['filename']} (not found)")
            continue
        samples.append(
            {
                "path": path,
                "name": path.name,
                "category": item["category"],
                "true_label": item["ground_truth_label"],
                "f0": item.get("estimated_f0_median_hz", 0),
                "notes": item.get("notes", ""),
            }
        )

    print(f"Rendering advice v2 over {len(samples)} samples → {out_path}")

    # Load Engine A once (~10 s warm-up). We use the production patch so frame
    # confidence is exposed; advice_v2 only needs the per-segment C1 mean
    # margin so frame_conf_list is dropped after AnalyseResultItem build.
    from voiceya.services.audio_analyser.seg import (  # noqa: E402
        _patch_segmenter_for_frame_confidence,
        _warmup_segmenter,
    )

    _patch_segmenter_for_frame_confidence()
    from inaSpeechSegmenter.segmenter import Segmenter  # noqa: E402

    print("Loading Engine A …", flush=True)
    energy_ratio = float(os.getenv("ENGINE_A_ENERGY_RATIO", "0.07"))
    seg = Segmenter(detect_gender=True, ffmpeg=None, energy_ratio=energy_ratio)
    _warmup_segmenter(seg)

    sections: list[str] = []
    sections.append(f"# Advice v2 render report ({today})\n")
    sections.append(
        "Generated by `tests/render_advice_v2.py`. One entry per manifest sample.\n"
        "See `docs/plans/v2_redesign_measurement.md` §9 for the review rubric.\n"
    )
    sections.append(f"Total samples: {len(samples)}\n")
    sections.append("---\n")

    by_category: dict[str, list[str]] = {}

    for i, entry in enumerate(samples, 1):
        print(f"  [{i}/{len(samples)}] {entry['name']}", flush=True)
        try:
            y, sr = _load_audio(entry["path"])
            if sr != 16_000:
                print(f"    skip (sr={sr})", flush=True)
                continue
            duration_sec = len(y) / sr
            items = _engine_a_run(seg, entry["path"])
            dominant = _dominant_label(items)
            advice = compute_advice(y, sr, items, duration_sec, dominant)
            section = _format_section(entry, advice, items)
            by_category.setdefault(entry["category"], []).append(section)
        except Exception as e:  # noqa: BLE001
            section = f"### {entry['name']}\n\n_error rendering: {e}_\n\n---\n"
            by_category.setdefault(entry["category"], []).append(section)

    for cat in sorted(by_category):
        sections.append(f"## category: `{cat}`\n")
        sections.extend(by_category[cat])

    out_path.write_text("\n".join(sections), encoding="utf-8")
    print(f"Done → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
