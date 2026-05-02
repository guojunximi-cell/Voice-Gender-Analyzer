"""Stress test: file_F0_strict stability vs recording duration.

For each subject file, slide a window of length L across the audio with 1s step,
compute pyin strict F0 on each sub-clip, report:
  - voiced_dur >= 1s rate (i.e. fraction of sub-clips where F0 is computable)
  - median F0 distribution among computable clips
  - rate of falling in [145, 185] (ceiling zone)
"""

import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa

ROOT = Path(__file__).resolve().parents[1]

SUBJECTS = [
    ("male_4", ROOT / "tests/fixtures/audio/male_4.wav", "cis male, F0~176"),
    ("female_2", ROOT / "tests/fixtures/audio/female_2.wav", "cis female, F0~175 (adversarial)"),
    ("female_1", ROOT / "tests/fixtures/audio/female_1.wav", "cis female, F0~198 (borderline)"),
]

LENGTHS_S = [3, 5, 8, 10, 12, 15, 20, 30]
STEP_S = 1.0
PYIN_FMIN = 60.0
PYIN_FMAX = 250.0  # v2.5 spec: pyin[60-250] avoids octave doubling on low-male/low-female F0
FRAME_LENGTH = 2048
HOP_LENGTH = 512
VOICED_PROB_THRESHOLD = 0.5
VOICED_DUR_FLOOR_S = 1.0
CEILING_LO = 145
CEILING_HI = 185


def strict_pyin(y: np.ndarray, sr: int) -> tuple[float | None, float]:
    """Run pyin strict mode. Returns (median_F0_or_None, voiced_duration_sec)."""
    if len(y) < FRAME_LENGTH:
        return None, 0.0
    f0, voiced_flag, voiced_prob = librosa.pyin(
        y,
        fmin=PYIN_FMIN,
        fmax=PYIN_FMAX,
        sr=sr,
        frame_length=FRAME_LENGTH,
        hop_length=HOP_LENGTH,
    )
    strict_mask = (voiced_prob > VOICED_PROB_THRESHOLD) & ~np.isnan(f0)
    voiced_dur = float(strict_mask.sum() * HOP_LENGTH / sr)
    if voiced_dur < VOICED_DUR_FLOOR_S:
        return None, voiced_dur
    return float(np.nanmedian(f0[strict_mask])), voiced_dur


def windowize(y: np.ndarray, sr: int, win_s: float, step_s: float):
    win_n = int(win_s * sr)
    step_n = int(step_s * sr)
    out = []
    if len(y) < win_n:
        return out
    for start in range(0, len(y) - win_n + 1, step_n):
        out.append(y[start : start + win_n])
    return out


def quantiles(arr, qs=(0.10, 0.25, 0.50, 0.75, 0.90)):
    if len(arr) == 0:
        return None
    a = np.array(arr)
    return {f"p{int(q * 100):02d}": float(np.quantile(a, q)) for q in qs}


def main():
    print("=" * 110)
    print(f"Stress test: file_F0_strict (pyin {PYIN_FMIN}-{PYIN_FMAX} Hz, voiced_prob>{VOICED_PROB_THRESHOLD}, dur_floor={VOICED_DUR_FLOOR_S}s)")
    print(f"Ceiling zone: [{CEILING_LO}, {CEILING_HI}] Hz")
    print(f"Lengths: {LENGTHS_S} s | step: {STEP_S} s")
    print("=" * 110)

    for subj_name, subj_path, subj_desc in SUBJECTS:
        y, sr = sf.read(str(subj_path))
        if y.ndim > 1:
            y = y.mean(axis=1)
        full_dur = len(y) / sr
        # Reference: full-file F0
        full_f0, full_voiced = strict_pyin(y, sr)
        print()
        print("-" * 110)
        print(f"### {subj_name} ({subj_desc})")
        print(f"    file dur: {full_dur:.1f}s | full-file strict F0: {full_f0:.1f} Hz | voiced_dur: {full_voiced:.1f}s")
        print("-" * 110)
        print(f"{'win_s':>5} | {'n_subs':>6} | {'computable':>10} | {'in_ceiling':>10} | {'F0 quantiles (p10/p25/p50/p75/p90)':<46}")
        print("-" * 110)

        for win_s in LENGTHS_S:
            subs = windowize(y, sr, win_s, STEP_S)
            n_subs = len(subs)
            if n_subs == 0:
                print(f"{win_s:>5} | {n_subs:>6} | (file too short)")
                continue
            f0_list = []
            voiced_dur_list = []
            n_computable = 0
            n_in_ceiling = 0
            for sub_y in subs:
                med_f0, vd = strict_pyin(sub_y, sr)
                voiced_dur_list.append(vd)
                if med_f0 is not None:
                    n_computable += 1
                    f0_list.append(med_f0)
                    if CEILING_LO <= med_f0 <= CEILING_HI:
                        n_in_ceiling += 1
            comp_pct = 100 * n_computable / n_subs if n_subs else 0
            ceil_pct_total = 100 * n_in_ceiling / n_subs if n_subs else 0
            ceil_pct_comp = 100 * n_in_ceiling / n_computable if n_computable else 0
            comp_str = f"{n_computable}/{n_subs} ({comp_pct:.0f}%)"
            ceil_str = f"{n_in_ceiling}/{n_subs} ({ceil_pct_total:.0f}%/all, {ceil_pct_comp:.0f}%/comp)"
            qs = quantiles(f0_list) if f0_list else None
            qs_str = (
                f"{qs['p10']:.0f}/{qs['p25']:.0f}/{qs['p50']:.0f}/{qs['p75']:.0f}/{qs['p90']:.0f}"
                if qs
                else "(no computable)"
            )
            print(f"{win_s:>5} | {n_subs:>6} | {comp_str:>10} | {ceil_str:>10} | {qs_str:<46}")

        # Show voiced_dur median per length to surface "frequently <1s" threshold
        print("-" * 110)
        print(f"{'win_s':>5} | voiced_dur quantiles (p10/p25/p50/p75/p90)")
        for win_s in LENGTHS_S:
            subs = windowize(y, sr, win_s, STEP_S)
            if not subs:
                continue
            vds = []
            for sub_y in subs:
                _, vd = strict_pyin(sub_y, sr)
                vds.append(vd)
            qs = quantiles(vds)
            print(f"{win_s:>5} | {qs['p10']:.2f}/{qs['p25']:.2f}/{qs['p50']:.2f}/{qs['p75']:.2f}/{qs['p90']:.2f}")
    print("=" * 110)


if __name__ == "__main__":
    sys.exit(main() or 0)
