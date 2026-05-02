"""
Engine A confidence: three-way comparison (old / C1-T1.0 / C1-T_current).

All three metrics from one nn.predict() call per file — no redundant inference.

Columns:
  OLD    winner-class mean, no temperature (original baseline)
  C1-T1  C1 margin, T=1.0  (C1 only, no temperature scaling)
  C1-Tx  C1 margin, T=<current Gender.temperature>

Source of truth: tests/fixtures/manifest.yaml
  Each entry: filename / category / ground_truth_label / estimated_f0_median_hz / source / notes
  Files listed but not present on disk are skipped with a warning.

Target criteria for C1-Tx vs C1-T1 (T1 is the comparison baseline):
  1. Segments with margin in [0.4, 0.7] should increase.
  2. male_4.wav mean margin < 0.80.
  3. cis_female min mean margin >= 0.60.

Usage:
    uv run python tests/test_confidence_c1.py
"""

from __future__ import annotations

import gc
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML not found — run: pip install pyyaml")

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
MANIFEST_PATH = FIXTURE_DIR / "manifest.yaml"

CATEGORY_ORDER = [
    "cis_female",
    "cis_male_standard",
    "cis_male_high_f0",
    "trans_fem_early",
    "trans_fem_mid",
    "trans_fem_late",
    "trans_masc",
    "neutral",
]


# ── manifest loading ──────────────────────────────────────────────────────────

def load_manifest() -> list[dict]:
    with open(MANIFEST_PATH) as fh:
        data = yaml.safe_load(fh)
    entries = []
    for item in data.get("samples", []):
        path = FIXTURE_DIR / item["filename"]
        if not path.exists():
            print(f"  [skip] {item['filename']} (not found)")
            continue
        entries.append({
            "path": path,
            "name": path.name,
            "category": item["category"],
            "true_label": item["ground_truth_label"],
            "f0": item.get("estimated_f0_median_hz", 0),
            "source": item.get("source", ""),
            "notes": item.get("notes", ""),
        })
    return entries


# ── three-metric capture wrapper ──────────────────────────────────────────────

def _triple_call(self: DnnSegmenter, mspec, lseg, difflen: int = 0):
    """Replaces DnnSegmenter.__call__; appends to self._records."""
    if self.nmel < 24:
        mspec = mspec[:, : self.nmel].copy()

    patches, finite = _get_patches(mspec, 68, 2)
    if difflen > 0:
        patches = patches[: -int(difflen / 2), :, :]
        finite  = finite[: -int(difflen / 2)]

    batch = [patches[s:e] for lab, s, e, *_ in lseg if lab == self.inlabel]
    if not batch:
        return []

    batch_arr = np.expand_dims(np.concatenate(batch), 3)
    raw = self.nn.predict(batch_arr, batch_size=self.batch_size, verbose=0)
    gc.collect()

    raw_old = raw.copy()
    raw_t1  = raw.copy()

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
        r_old, raw_old = raw_old[:n], raw_old[n:]
        r_t1,  raw_t1  = raw_t1[:n],  raw_t1[n:]
        r_tx,  raw_tx  = raw_tx[:n],  raw_tx[n:]

        mask = ~finite[start:stop]
        r_old[mask] = 0.5
        r_t1[mask]  = 0.5
        r_tx[mask]  = 0.5

        pred = viterbi_decoding(
            np.log(r_tx), diag_trans_exp(self.viterbi_arg, len(self.outlabels))
        )
        for lab2, s2, e2 in _binidx2seglist(pred):
            idx = int(lab2)
            so, st1, stx = r_old[s2:e2], r_t1[s2:e2], r_tx[s2:e2]
            if len(stx):
                old_conf = float(so[:, idx].mean())
                def _margin(m):
                    sp = np.sort(m, axis=1)
                    return float((sp[:, -1] - sp[:, -2]).mean())
                c1_t1 = _margin(st1)
                c1_tx = _margin(stx)
                fm    = np.sort(stx, axis=1)
                frame_margin = (fm[:, -1] - fm[:, -2]).tolist()
            else:
                old_conf = c1_t1 = c1_tx = None
                frame_margin = []

            self._records.append(
                (self.outlabels[idx], old_conf, c1_t1, c1_tx, e2 - s2)
            )
            ret.append((self.outlabels[idx], s2+start, e2+start, c1_tx, frame_margin))

    return ret


# ── helpers ───────────────────────────────────────────────────────────────────

def _stats_row(vals: list[float], label: str = "") -> str:
    if not vals:
        return f"{label:>9}  —  (no segments)"
    a = np.array(vals)
    mid = int(((a >= 0.4) & (a <= 0.7)).sum())
    return (
        f"{label:>9}  n={len(a):>3}  mean={a.mean():.3f}  "
        f"p10/50/90=[{np.percentile(a,10):.2f},{np.percentile(a,50):.2f},{np.percentile(a,90):.2f}]  "
        f"hi>0.9={int((a>0.9).sum()):>3}  [0.4–0.7]={mid:>3} ({100*mid/len(a):.0f}%)"
    )


def _run(seg: Segmenter, path: Path) -> list[tuple]:
    for dnn in [seg.vad, seg.gender]:
        dnn._records = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mspec, loge, difflen = _media2feats(str(path), None, None, "ffmpeg")
    seg.segment_feats(mspec, loge, difflen, 0.0)
    out = []
    for dnn in [seg.vad, seg.gender]:
        out.extend(getattr(dnn, "_records", []))
    return out


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    DnnSegmenter.__call__ = _triple_call  # type: ignore[method-assign]

    print("Loading models…")
    seg = Segmenter(vad_engine="smn", detect_gender=True, batch_size=32)
    from voiceya.inaSpeechSegmenter.inaSpeechSegmenter.segmenter import Gender
    T = Gender.temperature
    assert T == 2.0, f"Expected Gender.temperature=2.0, got {T}"
    print(f"Gender.temperature = {T}  ✓\n")

    print("Loading manifest…")
    entries = load_manifest()
    print(f"  {len(entries)} files found on disk\n")

    # per_file: name → {entry, old, t1, tx, segs: [(predicted_label, old, t1, tx, dur)]}
    per_file: dict[str, dict] = {}

    for entry in entries:
        print(f"  {entry['name']} [{entry['category']}]…", end=" ", flush=True)
        recs = _run(seg, entry["path"])
        voiced = [
            (lab, o, t1, tx, d)
            for lab, o, t1, tx, d in recs
            if lab in ("female", "male") and o is not None
        ]
        print(f"{len(voiced)} voiced segments")
        per_file[entry["name"]] = {
            **entry,
            "old": [o  for _, o, _, _, _ in voiced],
            "t1":  [t1 for _, _, t1, _, _ in voiced],
            "tx":  [tx for _, _, _, tx, _ in voiced],
            "pred_labels": [lab for lab, *_ in voiced],
        }

    # ── overall ───────────────────────────────────────────────────────────────
    all_old = [x for d in per_file.values() for x in d["old"]]
    all_t1  = [x for d in per_file.values() for x in d["t1"]]
    all_tx  = [x for d in per_file.values() for x in d["tx"]]
    n = len(all_tx)

    print(f"\n{'='*88}")
    print(f"RESULTS  T={T}   ({n} voiced segments across {len(per_file)} files)")
    print(f"{'='*88}")

    print("\n── OVERALL ──────────────────────────────────────────────────────────────────────────")
    print(_stats_row(all_old, "OLD"))
    print(_stats_row(all_t1,  "C1-T1"))
    print(_stats_row(all_tx,  f"C1-T{T}"))

    # ── per-category margin distribution ──────────────────────────────────────
    print(f"\n── PER-CATEGORY MARGIN DISTRIBUTION (C1-T{T}) ───────────────────────────────────────")
    for cat in CATEGORY_ORDER:
        keys = [k for k, v in per_file.items() if v["category"] == cat]
        if not keys:
            continue
        old_v = [x for k in keys for x in per_file[k]["old"]]
        t1_v  = [x for k in keys for x in per_file[k]["t1"]]
        tx_v  = [x for k in keys for x in per_file[k]["tx"]]
        print(f"\n  [{cat}]  files={len(keys)}")
        print(f"  {_stats_row(old_v, 'OLD')}")
        print(f"  {_stats_row(t1_v,  'C1-T1')}")
        print(f"  {_stats_row(tx_v,  f'C1-T{T}')}")

    # ── per-category classification accuracy ──────────────────────────────────
    print(f"\n── PER-CATEGORY CLASSIFICATION ACCURACY ─────────────────────────────────────────────")
    hdr = f"  {'category':<20}  {'files':>5}  {'segs':>5}  {'acc%':>5}  {'note'}"
    print(hdr); print("  " + "-" * (len(hdr)-2))
    for cat in CATEGORY_ORDER:
        keys = [k for k, v in per_file.items() if v["category"] == cat]
        if not keys:
            continue
        true_lab = per_file[keys[0]]["true_label"]
        total = sum(len(per_file[k]["tx"]) for k in keys)
        if true_lab == "neutral" or total == 0:
            note = "(not scored — neutral category)" if true_lab == "neutral" else "(no voiced segments)"
            print(f"  {cat:<20}  {len(keys):>5}  {total:>5}  {'—':>5}  {note}")
            continue
        correct = sum(
            sum(1 for pl in per_file[k]["pred_labels"] if pl == true_lab)
            for k in keys
        )
        acc = 100.0 * correct / total
        note = f"ground_truth={true_lab}"
        print(f"  {cat:<20}  {len(keys):>5}  {total:>5}  {acc:>4.1f}%  {note}")

    # ── per-file outlier table (highest and lowest margin per category) ────────
    print(f"\n── OUTLIERS: HIGHEST/LOWEST C1-T{T} MARGIN PER CATEGORY ─────────────────────────────")
    for cat in CATEGORY_ORDER:
        keys = [k for k, v in per_file.items() if v["category"] == cat and per_file[k]["tx"]]
        if not keys:
            continue
        means = {k: float(np.mean(per_file[k]["tx"])) for k in keys}
        sorted_keys = sorted(means, key=means.__getitem__)
        lo_k, hi_k = sorted_keys[0], sorted_keys[-1]
        print(f"\n  [{cat}]")
        if lo_k == hi_k:
            print(f"    only one file: {lo_k}  mean={means[lo_k]:.4f}")
        else:
            print(f"    LOWEST  {lo_k:<28} mean={means[lo_k]:.4f}  true={per_file[lo_k]['true_label']}")
            print(f"    HIGHEST {hi_k:<28} mean={means[hi_k]:.4f}  true={per_file[hi_k]['true_label']}")

    # ── per-file detail table ─────────────────────────────────────────────────
    print(f"\n── PER-FILE DETAIL ──────────────────────────────────────────────────────────────────")
    hdr2 = f"  {'file':<26}  {'category':<20}  {'true':>6}  {'acc%':>4}  {'old':>7}  {'c1-T1':>7}  {'c1-Tx':>7}  Δ"
    print(hdr2); print("  " + "-" * (len(hdr2)-2))
    for cat in CATEGORY_ORDER:
        for fname in sorted(k for k, v in per_file.items() if v["category"] == cat):
            d = per_file[fname]
            total = len(d["tx"])
            if total == 0:
                continue
            true_lab = d["true_label"]
            if true_lab == "neutral":
                acc_str = "  —"
            else:
                correct = sum(1 for pl in d["pred_labels"] if pl == true_lab)
                acc_str = f"{100.0*correct/total:3.0f}%"
            o_m  = float(np.mean(d["old"]))
            t1_m = float(np.mean(d["t1"]))
            tx_m = float(np.mean(d["tx"]))
            print(f"  {fname:<26}  {cat:<20}  {true_lab:>6}  {acc_str:>4}  "
                  f"{o_m:>7.4f}  {t1_m:>7.4f}  {tx_m:>7.4f}  {tx_m-t1_m:>+.4f}")

    # ── target criteria ───────────────────────────────────────────────────────
    print(f"\n── TARGET CRITERIA (C1-T{T} vs C1-T1 baseline) ──────────────────────────────────────")
    a_t1 = np.array(all_t1) if all_t1 else np.array([])
    a_tx = np.array(all_tx) if all_tx else np.array([])

    if len(a_t1) and len(a_tx):
        mid_t1 = int(((a_t1 >= 0.4) & (a_t1 <= 0.7)).sum())
        mid_tx = int(((a_tx >= 0.4) & (a_tx <= 0.7)).sum())
        c1 = mid_tx > mid_t1
        print(f"  1. [0.4–0.7] count: T1={mid_t1}/{n} ({100*mid_t1/n:.0f}%) → "
              f"T{T}={mid_tx}/{n} ({100*mid_tx/n:.0f}%)  {'✓ PASS' if c1 else '✗ FAIL'}")
    else:
        c1 = False
        print("  1. no data")

    male4 = per_file.get("male_4.wav")
    m4_tx = float(np.mean(male4["tx"])) if male4 and male4["tx"] else None
    m4_t1 = float(np.mean(male4["t1"])) if male4 and male4["t1"] else None
    c2 = m4_tx is not None and m4_tx < 0.80
    if m4_tx is not None:
        print(f"  2. male_4 mean C1: T1={m4_t1:.4f} → T{T}={m4_tx:.4f}  "
              f"{'✓ PASS (<0.80)' if c2 else '✗ FAIL (≥0.80)'}")
    else:
        c2 = False
        print("  2. male_4.wav not in manifest or no voiced segments")

    fem_keys = [k for k, v in per_file.items() if v["category"] == "cis_female" and v["tx"]]
    fem_means = {k: float(np.mean(per_file[k]["tx"])) for k in fem_keys}
    f_min = min(fem_means.values()) if fem_means else 0.0
    c3 = f_min >= 0.60
    print(f"  3. cis_female min mean C1-T{T}: {f_min:.4f}  {'✓ PASS (≥0.60)' if c3 else '✗ FAIL (<0.60)'}")
    for k, v in sorted(fem_means.items()):
        t1_m = float(np.mean(per_file[k]["t1"]))
        print(f"       {k:<28} T1={t1_m:.4f} → T{T}={v:.4f}")

    print(f"\n{'='*88}")
    passed = sum([c1, c2, c3])
    verdict = f"ALL 3 PASS — T={T} locked" if passed == 3 else f"{passed}/3 PASS — review above"
    print(f"VERDICT: {verdict}")


if __name__ == "__main__":
    main()
