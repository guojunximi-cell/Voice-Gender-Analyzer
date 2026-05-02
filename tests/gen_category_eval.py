"""Generate detailed category evaluation report.

Reads manifest.yaml, runs Engine A (T=2.0, C1 margin), and writes
tests/reports/category_eval_<DATE>.md with per-category margin percentiles,
accuracy, mixed-segment ratios, and per-file detail. This report is the
sole source of truth for advice_v2 threshold derivation.

Usage:
    uv run python tests/gen_category_eval.py
"""

from __future__ import annotations

import gc
import os
import sys
import warnings
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import yaml
from pathlib import Path

from voiceya.inaSpeechSegmenter.inaSpeechSegmenter.segmenter import (
    DnnSegmenter,
    Segmenter,
    _binidx2seglist,
    _get_patches,
    _media2feats,
)
from voiceya.inaSpeechSegmenter.inaSpeechSegmenter.pyannote_viterbi import viterbi_decoding
from voiceya.inaSpeechSegmenter.inaSpeechSegmenter.viterbi_utils import diag_trans_exp

FIXTURE_DIR = Path(__file__).parent / "fixtures"
REPORT_DIR = Path(__file__).parent / "reports"

CATEGORY_ORDER = [
    "cis_female", "cis_male_standard", "cis_male_high_f0",
    "trans_fem_early", "trans_fem_mid", "trans_fem_late",
    "trans_masc", "neutral",
]

PERCENTILES = [5, 10, 25, 50, 75, 90, 95]


def load_manifest() -> list[dict]:
    with open(FIXTURE_DIR / "manifest.yaml") as fh:
        data = yaml.safe_load(fh)
    out = []
    for item in data.get("samples", []):
        p = FIXTURE_DIR / item["filename"]
        if not p.exists():
            continue
        out.append({
            "path": p,
            "name": p.name,
            "category": item["category"],
            "true_label": item["ground_truth_label"],
            "f0": item.get("estimated_f0_median_hz", 0),
            "source": item.get("source", ""),
            "notes": item.get("notes", ""),
        })
    return out


def _capture_call(self: DnnSegmenter, mspec, lseg, difflen: int = 0):
    """Override DnnSegmenter.__call__ to capture margin per segment."""
    if self.nmel < 24:
        mspec = mspec[:, : self.nmel].copy()
    patches, finite = _get_patches(mspec, 68, 2)
    if difflen > 0:
        patches = patches[: -int(difflen / 2), :, :]
        finite = finite[: -int(difflen / 2)]
    batch = [patches[s:e] for lab, s, e, *_ in lseg if lab == self.inlabel]
    if not batch:
        return []
    raw = self.nn.predict(np.expand_dims(np.concatenate(batch), 3),
                          batch_size=self.batch_size, verbose=0)
    gc.collect()

    # Apply T-scaling for production view
    raw_tx = raw.copy()
    if self.temperature != 1.0:
        lp = np.log(np.clip(raw_tx, 1e-10, 1.0)) / self.temperature
        lp -= lp.max(axis=1, keepdims=True)
        raw_tx = np.exp(lp)
        raw_tx /= raw_tx.sum(axis=1, keepdims=True)

    self._records = getattr(self, "_records", [])
    ret = []
    for lab, start, stop, *_ in lseg:
        if lab != self.inlabel:
            ret.append((lab, start, stop))
            continue
        n = stop - start
        r_tx, raw_tx = raw_tx[:n], raw_tx[n:]
        mask = ~finite[start:stop]
        r_tx[mask] = 0.5
        pred = viterbi_decoding(np.log(r_tx), diag_trans_exp(self.viterbi_arg, len(self.outlabels)))
        for lab2, s2, e2 in _binidx2seglist(pred):
            seg = r_tx[s2:e2]
            if len(seg):
                sp = np.sort(seg, axis=1)
                margin = float((sp[:, -1] - sp[:, -2]).mean())
            else:
                margin = None
            self._records.append((self.outlabels[int(lab2)], margin, e2 - s2))
            ret.append((self.outlabels[int(lab2)], s2 + start, e2 + start))
    return ret


def run_one(seg: Segmenter, path: Path):
    for dnn in [seg.vad, seg.gender]:
        dnn._records = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mspec, loge, difflen = _media2feats(str(path), None, None, "ffmpeg")
    seg.segment_feats(mspec, loge, difflen, 0.0)
    return list(seg.gender._records)


def pct_str(arr, ps=PERCENTILES):
    if len(arr) == 0:
        return "—"
    a = np.array(arr)
    return "[" + ", ".join(f"p{p}={np.percentile(a, p):.3f}" for p in ps) + "]"


def main():
    DnnSegmenter.__call__ = _capture_call  # type: ignore

    print("Loading models…")
    seg = Segmenter(vad_engine="smn", detect_gender=True, batch_size=32)
    from voiceya.inaSpeechSegmenter.inaSpeechSegmenter.segmenter import Gender
    T = Gender.temperature

    print("Loading manifest…")
    entries = load_manifest()
    print(f"  {len(entries)} files\n")

    # per_file: {name → entry + segs: [(label, margin, dur_frames)]}
    per_file = {}
    for e in entries:
        recs = run_one(seg, e["path"])
        recs = [(lab, m, d) for lab, m, d in recs if lab in ("female", "male") and m is not None]
        per_file[e["name"]] = {**e, "segs": recs}
        print(f"  {e['name']:<42} [{e['category']:<22}] {len(recs)} segs")

    # ── compute per-category aggregates ────────────────────────────────────
    REPORT_DIR.mkdir(exist_ok=True)
    today = date.today().isoformat()
    out_path = REPORT_DIR / f"category_eval_{today}.md"

    lines = []
    lines.append(f"# Category evaluation report — {today}")
    lines.append("")
    lines.append(f"- Engine A: inaSpeechSegmenter, **T = {T}**, confidence = C1 margin (mean per-frame best−second-best).")
    lines.append(f"- Total files: **{len(per_file)}**")
    lines.append("- Source: tests/fixtures/manifest.yaml")
    lines.append("- Generator: tests/gen_category_eval.py")
    lines.append("- **READ ALSO**: tests/fixtures/KNOWN_LIMITATIONS.md")
    lines.append("")
    lines.append("Categories with `ground_truth_label == neutral` are excluded from accuracy. ")
    lines.append("All margins reported are at production T = 2.0 (C1).")
    lines.append("")

    # Table 1: overall per-category stats
    lines.append("## 1. Per-category margin distribution (C1 @ T=2.0)")
    lines.append("")
    lines.append(f"Percentiles over **per-segment** margins (each segment's mean per-frame margin).")
    lines.append("")
    lines.append("| category | files | segs | mean | p5 | p10 | p25 | p50 | p75 | p90 | p95 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    cat_data = {}
    for cat in CATEGORY_ORDER:
        keys = [k for k, v in per_file.items() if v["category"] == cat]
        margins = [m for k in keys for _, m, _ in per_file[k]["segs"]]
        cat_data[cat] = margins
        if not margins:
            lines.append(f"| {cat} | {len(keys)} | 0 | — | — | — | — | — | — | — | — |")
            continue
        a = np.array(margins)
        row = f"| {cat} | {len(keys)} | {len(a)} | {a.mean():.3f}"
        for p in PERCENTILES:
            row += f" | {np.percentile(a, p):.3f}"
        lines.append(row + " |")
    lines.append("")

    # Table 2: accuracy
    lines.append("## 2. Per-category classification accuracy")
    lines.append("")
    lines.append("Accuracy = fraction of voiced segments whose predicted label matches `ground_truth_label`.")
    lines.append("Segments in `neutral`-label categories are not scored.")
    lines.append("")
    lines.append("| category | files | segs | accuracy | note |")
    lines.append("|---|---:|---:|---:|---|")
    for cat in CATEGORY_ORDER:
        keys = [k for k, v in per_file.items() if v["category"] == cat]
        if not keys: continue
        true_lab = per_file[keys[0]]["true_label"]
        total = sum(len(per_file[k]["segs"]) for k in keys)
        if true_lab == "neutral" or total == 0:
            note = "(neutral, not scored)" if true_lab == "neutral" else "(no voiced segments)"
            lines.append(f"| {cat} | {len(keys)} | {total} | — | {note} |")
            continue
        correct = sum(sum(1 for lab, _, _ in per_file[k]["segs"] if lab == true_lab) for k in keys)
        acc = 100.0 * correct / total
        lines.append(f"| {cat} | {len(keys)} | {total} | **{acc:.1f}%** | gt={true_lab} |")
    lines.append("")

    # Table 3: mixed-segment analysis (per-file minority ratio)
    lines.append("## 3. Mixed-segment analysis (minority label ratio per file)")
    lines.append("")
    lines.append("`minority_dur_ratio` = duration-weighted fraction of segments whose label != file's modal label.")
    lines.append("For homogeneous predictions this is 0; for mixed predictions it indicates the boundary region.")
    lines.append("")
    lines.append("| category | files | mean min_ratio | p50 | p90 | p95 | max | files with min_ratio>0 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for cat in CATEGORY_ORDER:
        keys = [k for k, v in per_file.items() if v["category"] == cat]
        ratios = []
        for k in keys:
            segs = per_file[k]["segs"]
            if not segs: continue
            from collections import Counter
            dur_by_lab = {}
            total_dur = 0
            for lab, _, d in segs:
                dur_by_lab[lab] = dur_by_lab.get(lab, 0) + d
                total_dur += d
            if total_dur == 0: continue
            modal = max(dur_by_lab, key=dur_by_lab.get)
            minority = total_dur - dur_by_lab[modal]
            ratios.append(minority / total_dur)
        if not ratios:
            lines.append(f"| {cat} | {len(keys)} | — | — | — | — | — | — |")
            continue
        a = np.array(ratios)
        nonzero = int((a > 0).sum())
        lines.append(f"| {cat} | {len(keys)} | {a.mean():.3f} | {np.percentile(a,50):.3f} | "
                     f"{np.percentile(a,90):.3f} | {np.percentile(a,95):.3f} | {a.max():.3f} | {nonzero}/{len(a)} |")
    lines.append("")

    # Table 4: F0 metadata distribution per category
    lines.append("## 4. F0 (estimated) distribution per category")
    lines.append("")
    lines.append("F0 values from `manifest.yaml::estimated_f0_median_hz` (pyin[60-250] median).")
    lines.append("Used only for reference — Engine A does not consume F0.")
    lines.append("")
    lines.append("| category | files | mean F0 | p10 | p50 | p90 | min | max |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for cat in CATEGORY_ORDER:
        keys = [k for k, v in per_file.items() if v["category"] == cat]
        f0s = [per_file[k]["f0"] for k in keys if per_file[k]["f0"] > 0]
        if not f0s:
            lines.append(f"| {cat} | {len(keys)} | — | — | — | — | — | — |")
            continue
        a = np.array(f0s)
        lines.append(f"| {cat} | {len(keys)} | {a.mean():.0f} | {np.percentile(a,10):.0f} | "
                     f"{np.percentile(a,50):.0f} | {np.percentile(a,90):.0f} | {a.min()} | {a.max()} |")
    lines.append("")

    # Table 5: per-file detail (for manual review)
    lines.append("## 5. Per-file detail")
    lines.append("")
    lines.append("Sorted by category, then file. `mean margin` is segment-duration-weighted.")
    lines.append("")
    lines.append("| file | category | gt | F0 | n_segs | preds | mean margin | min margin | acc% |")
    lines.append("|---|---|---|---:|---:|---|---:|---:|---:|")
    for cat in CATEGORY_ORDER:
        for fname in sorted(k for k, v in per_file.items() if v["category"] == cat):
            d = per_file[fname]
            segs = d["segs"]
            if not segs:
                lines.append(f"| {fname} | {cat} | {d['true_label']} | {d['f0']} | 0 | — | — | — | — |")
                continue
            from collections import Counter
            preds_count = Counter(lab for lab, _, _ in segs)
            preds = "/".join(f"{c}{n}" for c, n in preds_count.most_common())
            margins = [m for _, m, _ in segs]
            durs = [d_ for _, _, d_ in segs]
            mean_m = float(np.average(margins, weights=durs))
            min_m  = min(margins)
            if d["true_label"] == "neutral":
                acc_str = "—"
            else:
                correct = sum(1 for lab, _, _ in segs if lab == d["true_label"])
                acc_str = f"{100.0*correct/len(segs):.0f}%"
            lines.append(f"| {fname} | {cat} | {d['true_label']} | {d['f0']} | {len(segs)} | "
                         f"{preds} | {mean_m:.3f} | {min_m:.3f} | {acc_str} |")
    lines.append("")

    out_path.write_text("\n".join(lines))
    print(f"\nReport written: {out_path}")
    print(f"  {len(lines)} lines, {sum(len(per_file[k]['segs']) for k in per_file)} total segments")


if __name__ == "__main__":
    main()
