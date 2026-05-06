"""Phase A diagnostic: empirical en-US resonance distribution.

Mirrors scripts/audit_resonance_{zh,fr}.py but for English.  Consumes the
hand-curated regression corpus at /mnt/d/.../audio/en/{cis_female_en,
cis_male_en}/ — primarily CMU-Arctic (clb, slt = F; awb, bdl, jmk, rms = M)
and VCTK (~14 speakers, gender from VCTK's speaker_info.txt).  Total ~65
clips across ~16 speakers — enough for a directional collapse-check report
but per-percentile estimates are noisy (single-digit speakers per zone).

Differences vs zh/fr audits:
- ARPABET phone inventory (AA, IY, EH, …) instead of IPA — stress digits
  (0/1/2) stripped before bucketing.
- One clip = one analysis call (no ffmpeg-stitch needed; CMU-Arctic +
  VCTK clips are 4-15 s individually, plenty for advice_v2 standard tier).
- Speaker derived from filename prefix (cmu_arctic_<spk>_*, vctk_<spk>_*,
  test_<name>, synth_<spk>_*).
- Transcripts via faster-whisper base.en — sidecar requires a transcript
  for MFA alignment, and we don't ship one per fixture clip.

Sidecar must already be up.  Run with::

    uv run python scripts/audit_resonance_en.py
"""

from __future__ import annotations

import argparse
import csv  # noqa: F401 — symmetry with fr audit; tsv writers may want it later
import json
import logging
import os
import random
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("audit_en")

REPO_ROOT = Path(__file__).resolve().parent.parent
SIDECAR_DEFAULT = "http://localhost:8001"
DEFAULT_CORPUS = Path("/mnt/d/project_vocieduck/ablation/audio/en")
DEFAULT_LIBRISPEECH = Path("/mnt/d/project_vocieduck/ablation/audio/en/LibriSpeech")
DEFAULT_RAW = Path.home() / "scratch" / "en_phase_a" / "raw"
DEFAULT_REPORT = REPO_ROOT / "tests" / "reports" / f"en_resonance_baseline_{date.today()}.md"
STATS_EN_PATH = REPO_ROOT / "voiceya" / "sidecars" / "visualizer-backend" / "stats.json"
LIBRISPEECH_SUBSET = "train-clean-100"
LIBRISPEECH_SEED = 17

# ARPABET vowel base classes — stress digits (0/1/2) stripped before lookup.
EN_VOWELS = {
    "AA",
    "AE",
    "AH",
    "AO",
    "AW",
    "AY",
    "EH",
    "ER",
    "EY",
    "IH",
    "IY",
    "OW",
    "OY",
    "UH",
    "UW",
}
_STRESS_RE = re.compile(r"[012]$")

# Hillenbrand 1995 women's vowel formant data — F2 medians at the
# midpoint of each vowel.  Diphthongs (AW, AY, EY, OW, OY) use the
# nucleus; ER uses the steady-state value.  Sources:
# Hillenbrand, Getty, Clark, Wheeler 1995 J. Acoust. Soc. Am. 97(5).
LIT_FEMALE_F2_HZ = {
    "IY": 2960,
    "IH": 2350,
    "EH": 2190,
    "EY": 2350,
    "AE": 2050,
    "AH": 1545,
    "AA": 1130,
    "AO": 840,
    "OW": 960,
    "UH": 1120,
    "UW": 1100,
    "AW": 1290,
    "AY": 1700,
    "OY": 1100,
    "ER": 1590,
}


def _strip_stress(phn: str) -> str:
    return _STRESS_RE.sub("", phn) if phn else phn


def _drift_guard() -> None:
    """ARPABET vowel set is hardcoded by convention (no vendored counterpart
    to drift against) — this just sanity-checks _STRESS_RE behaviour so the
    audit doesn't silently bucket ``IY1`` and ``IY`` separately if the
    regex changes."""
    for stress in ("0", "1", "2"):
        assert _strip_stress(f"IY{stress}") == "IY"
        assert _strip_stress(f"AA{stress}") == "AA"
    assert _strip_stress("IY") == "IY"
    assert _strip_stress("sil") == "sil"


# ── corpus walking ─────────────────────────────────────────────────


_SPEAKER_PATTERNS = [
    # (regex, group-id-extractor)
    (re.compile(r"^cmu_arctic_([a-z]+)_"), lambda m: f"cmu_arctic_{m.group(1)}"),
    (re.compile(r"^vctk_(p\d+|s\d+)_"), lambda m: f"vctk_{m.group(1)}"),
    (re.compile(r"^test_([a-z]+)"), lambda m: f"test_{m.group(1)}"),
    (re.compile(r"^synth_([a-z]+)_"), lambda m: f"synth_{m.group(1)}"),
]


def _spk_from_filename(stem: str) -> str:
    for rx, fn in _SPEAKER_PATTERNS:
        m = rx.match(stem)
        if m:
            return fn(m)
    # Fallback — anything we don't recognise gets its own speaker.
    return stem


def enumerate_clips(corpus_root: Path) -> list[dict]:
    """Walk cis_female_en + cis_male_en, return [{wav, sex, spk_id}]."""
    rows: list[dict] = []
    for sex_dir, sex in (("cis_female_en", "F"), ("cis_male_en", "M")):
        d = corpus_root / sex_dir
        if not d.is_dir():
            log.warning("missing dir: %s", d)
            continue
        for wav in sorted(d.glob("*.wav")):
            rows.append(
                {
                    "wav": str(wav),
                    "sex": sex,
                    "spk_id": _spk_from_filename(wav.stem),
                    "stem": wav.stem,
                }
            )
    return rows


# ── LibriSpeech enumeration (large-N alternative to curated corpus) ─────


def _parse_librispeech_speakers(speakers_txt: Path, subset: str) -> dict[str, str]:
    """Parse SPEAKERS.TXT → {reader_id: 'F'|'M'} restricted to ``subset``.

    Format (pipe-separated, lines starting with ``;`` are comments):
        <id> | <sex> | <subset> | <minutes> | <name>
    """
    out: dict[str, str] = {}
    for line in speakers_txt.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.lstrip().startswith(";"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        spk_id, sex, sub = parts[0], parts[1], parts[2]
        if sub != subset:
            continue
        if sex not in ("F", "M"):
            continue
        out[spk_id] = sex
    return out


def _resolve_librispeech_transcript(flac_path: Path) -> str | None:
    """LibriSpeech ships transcripts at ``<spk>-<chap>.trans.txt``; one line
    per utterance keyed by ``<spk>-<chap>-<utt>``. Return the transcript or
    None if missing.
    """
    parent = flac_path.parent
    stem = flac_path.stem  # e.g. "103-1240-0000"
    try:
        spk, chap, _utt = stem.split("-", 2)
    except ValueError:
        return None
    trans_file = parent / f"{spk}-{chap}.trans.txt"
    if not trans_file.is_file():
        return None
    for line in trans_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line:
            continue
        head, _, body = line.partition(" ")
        if head == stem:
            return body.strip()
    return None


def enumerate_clips_librispeech(
    librispeech_root: Path,
    *,
    target_f: int,
    target_m: int,
    clips_per_spk: int,
    seed: int = LIBRISPEECH_SEED,
) -> list[dict]:
    """Sample ``target_f`` F + ``target_m`` M speakers from train-clean-100,
    take ``clips_per_spk`` clips each. Transcripts pulled from the .trans.txt
    files so the analyze phase can skip ASR. Returns the same dict shape as
    ``enumerate_clips`` plus a ``transcript`` key.
    """
    speakers_txt = librispeech_root / "SPEAKERS.TXT"
    if not speakers_txt.is_file():
        log.error("LibriSpeech SPEAKERS.TXT missing at %s", speakers_txt)
        return []
    spk_sex = _parse_librispeech_speakers(speakers_txt, LIBRISPEECH_SUBSET)
    subset_root = librispeech_root / LIBRISPEECH_SUBSET
    if not subset_root.is_dir():
        log.error("LibriSpeech subset missing: %s", subset_root)
        return []

    rng = random.Random(seed)
    f_speakers = sorted(s for s, x in spk_sex.items() if x == "F")
    m_speakers = sorted(s for s, x in spk_sex.items() if x == "M")
    rng.shuffle(f_speakers)
    rng.shuffle(m_speakers)

    rows: list[dict] = []
    for sex_pool, target, sex_label in (
        (f_speakers, target_f, "F"),
        (m_speakers, target_m, "M"),
    ):
        picked = 0
        for spk_id in sex_pool:
            if picked >= target:
                break
            spk_dir = subset_root / spk_id
            if not spk_dir.is_dir():
                continue
            flacs = sorted(spk_dir.rglob("*.flac"))
            if not flacs:
                continue
            rng.shuffle(flacs)
            took = 0
            for flac in flacs:
                if took >= clips_per_spk:
                    break
                transcript = _resolve_librispeech_transcript(flac)
                if not transcript:
                    continue
                stem = f"librispeech_{spk_id}_{flac.stem}"
                rows.append(
                    {
                        "wav": str(flac),
                        "sex": sex_label,
                        "spk_id": f"librispeech_{spk_id}",
                        "stem": stem,
                        "transcript": transcript,
                    }
                )
                took += 1
            if took:
                picked += 1
    log.info(
        "librispeech enumerated %d clips (%dF / %dM) across %d speakers",
        len(rows),
        sum(1 for r in rows if r["sex"] == "F"),
        sum(1 for r in rows if r["sex"] == "M"),
        len({r["spk_id"] for r in rows}),
    )
    return rows


def enumerate_for_args(args: argparse.Namespace) -> list[dict]:
    """Dispatcher: pick curated or librispeech enumerator from CLI flags."""
    if args.corpus_mode == "librispeech":
        return enumerate_clips_librispeech(
            Path(args.librispeech),
            target_f=args.target_spk_f,
            target_m=args.target_spk_m,
            clips_per_spk=args.clips_per_spk,
        )
    return enumerate_clips(Path(args.corpus))


# ── ASR + sidecar ──────────────────────────────────────────────────


def _transcribe_one(wav_path: Path, model) -> str | None:
    """Run faster-whisper on one clip, return concatenated transcript.
    Returns None on failure so the caller can drop the row gracefully."""
    try:
        segments, _info = model.transcribe(str(wav_path), language="en", beam_size=1)
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception as exc:
        log.debug("ASR failed for %s: %s", wav_path.name, exc)
        return None


def _post_one(sidecar_url: str, token: str, wav: Path, transcript: str) -> dict:
    import requests  # noqa: PLC0415

    headers = {}
    if token:
        headers["X-Engine-C-Token"] = token
    with wav.open("rb") as f:
        resp = requests.post(
            f"{sidecar_url}/engine_c/analyze",
            files={"audio": (wav.name, f, "audio/wav")},
            data={"transcript": transcript, "language": "en-US"},
            headers=headers,
            timeout=120,
        )
    resp.raise_for_status()
    return resp.json()


def analyze_phase(args: argparse.Namespace) -> int:
    clips = enumerate_for_args(args)
    if not clips:
        log.error("no clips enumerated for corpus_mode=%s", args.corpus_mode)
        sys.exit(2)
    log.info(
        "enumerated %d clips (%dF / %dM) across %d speakers",
        len(clips),
        sum(1 for c in clips if c["sex"] == "F"),
        sum(1 for c in clips if c["sex"] == "M"),
        len({c["spk_id"] for c in clips}),
    )

    raw_dir = Path(args.raw)
    raw_dir.mkdir(parents=True, exist_ok=True)
    token = os.environ.get(args.token_env, "").strip()

    import requests  # noqa: PLC0415

    try:
        health = requests.get(f"{args.sidecar}/healthz", timeout=10).json()
    except Exception as exc:
        log.error("sidecar unreachable: %s", exc)
        sys.exit(2)
    if "en" not in health.get("languages", []):
        log.error("sidecar /healthz does not advertise en: %s", health)
        sys.exit(2)
    log.info("sidecar healthy: %s", health)

    # Lazy faster-whisper load — only if we actually need to ASR (cache miss).
    asr_model = None

    t0 = time.time()
    done = skipped = failed = 0
    for i, row in enumerate(clips, 1):
        out = raw_dir / f"{row['stem']}.json"
        if out.exists() and out.stat().st_size > 256:
            skipped += 1
            continue
        wav_path = Path(row["wav"])

        # If the enumerator already resolved a transcript (LibriSpeech mode),
        # use it verbatim — skips the faster-whisper load entirely on big runs.
        transcript = row.get("transcript")
        if not transcript:
            if asr_model is None:
                log.info("loading faster-whisper base.en …")
                from faster_whisper import WhisperModel  # noqa: PLC0415

                asr_model = WhisperModel("base.en", device="cpu", compute_type="int8")
                log.info("ASR model ready")

            transcript = _transcribe_one(wav_path, asr_model)
            if not transcript:
                failed += 1
                continue
        try:
            data = _post_one(args.sidecar, token, wav_path, transcript)
        except Exception as exc:
            log.warning("clip %s: %s", row["stem"], exc)
            failed += 1
            continue
        # Persist transcript alongside data so report phase doesn't re-ASR.
        data["__transcript__"] = transcript
        out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        done += 1
        if i % 5 == 0 or i == len(clips):
            elapsed = time.time() - t0
            rate = (done + 0.001) / elapsed
            eta = (len(clips) - i) / rate if rate > 0 else 0
            log.info(
                "analyze %d/%d  done=%d skipped=%d failed=%d  rate=%.2f/s  eta=%.0fs",
                i,
                len(clips),
                done,
                skipped,
                failed,
                rate,
                eta,
            )

    log.info("done=%d skipped=%d failed=%d wall=%.0fs", done, skipped, failed, time.time() - t0)
    return failed


# ── report ─────────────────────────────────────────────────────────


def _percentiles(xs: list[float], pcts: tuple[int, ...]) -> dict[int, float]:
    if not xs:
        return {p: float("nan") for p in pcts}
    xs = sorted(xs)
    out: dict[int, float] = {}
    for p in pcts:
        idx = max(0, min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1)))))
        out[p] = xs[idx]
    return out


def _z(value: float | None, ref: dict | None) -> float | None:
    if value is None or ref is None or ref.get("stdev") in (None, 0):
        return None
    return (value - ref["mean"]) / ref["stdev"]


def report_phase(args: argparse.Namespace) -> Path:
    raw_dir = Path(args.raw)
    if not raw_dir.is_dir():
        log.error("missing %s — run --analyze first", raw_dir)
        sys.exit(2)
    clips = enumerate_for_args(args)

    stats = json.loads(STATS_EN_PATH.read_text(encoding="utf-8"))

    clip_data: list[dict] = []
    dropped: list[tuple[str, str]] = []
    for row in clips:
        raw = raw_dir / f"{row['stem']}.json"
        if not raw.is_file():
            dropped.append((row["stem"], "no raw json"))
            continue
        try:
            ec = json.loads(raw.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            dropped.append((row["stem"], "json decode"))
            continue
        if not ec.get("phones"):
            dropped.append((row["stem"], "zero phones"))
            continue
        clip_data.append(
            {
                "stem": row["stem"],
                "spk_id": row["spk_id"],
                "sex": row["sex"],
                "phones": ec["phones"],
                "medianResonance": ec.get("medianResonance"),
                "ceiling_hz": ec.get("formant_ceiling_hz"),
            }
        )

    # Group clips by speaker for per-speaker median resonance (avoids
    # per-clip noise dominating the percentile bands when one speaker
    # contributes 5+ clips).
    by_spk: dict[tuple[str, str], list[float]] = defaultdict(list)
    for c in clip_data:
        if c.get("medianResonance") is not None:
            by_spk[(c["spk_id"], c["sex"])].append(float(c["medianResonance"]))

    by_sex_spkmed: dict[str, list[float]] = {"F": [], "M": []}
    for (spk, sex), meds in by_spk.items():
        if meds:
            by_sex_spkmed[sex].append(statistics.median(meds))

    pcts = (5, 25, 50, 75, 95)
    table1 = {
        sex: {
            "n": len(vs),
            **_percentiles(vs, pcts),
            "mean": statistics.mean(vs) if vs else float("nan"),
        }
        for sex, vs in by_sex_spkmed.items()
    }

    per_vowel_F: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    per_vowel_M: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    per_vowel_sat: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))

    for c in clip_data:
        bucket = per_vowel_F if c["sex"] == "F" else per_vowel_M
        for ph in c["phones"]:
            label_raw = ph.get("phoneme")
            if not label_raw:
                continue
            label = _strip_stress(label_raw)
            if label not in EN_VOWELS:
                continue
            # stats.json keys may include stress-digited phones (cmudict-
            # derived); try base-class first, then raw — same fallback the
            # sidecar's resonance.compute_resonance uses.
            ref = stats.get(label) or stats.get(label_raw)
            if ref is None or len(ref) < 4:
                continue
            f_arr = ph.get("F") or [None, None, None, None]
            if len(f_arr) < 4:
                continue
            f1, f2, f3 = f_arr[1], f_arr[2], f_arr[3]
            for hz, idx, key in ((f1, 1, "F1"), (f2, 2, "F2"), (f3, 3, "F3")):
                if hz is None:
                    continue
                bucket[label][key].append(hz)
                z = _z(hz, ref[idx])
                if z is not None:
                    bucket[label][f"z_{key}"].append(z)
            res = ph.get("resonance")
            if res is not None:
                per_vowel_sat[c["sex"]][label].append(1 if (res <= 0.02 or res >= 0.98) else 0)

    collapse_rows: list[dict] = []
    for vowel, lit_hz in LIT_FEMALE_F2_HZ.items():
        f2s = per_vowel_F.get(vowel, {}).get("F2", [])
        if len(f2s) < 5:
            collapse_rows.append(
                {"vowel": vowel, "n": len(f2s), "f2_med": None, "lit": lit_hz, "verdict": "n<5"}
            )
            continue
        med = statistics.median(f2s)
        ratio = med / lit_hz
        if ratio < 0.75:
            verdict = "COLLAPSE"
        elif ratio < 0.85:
            verdict = "low"
        else:
            verdict = "ok"
        collapse_rows.append(
            {"vowel": vowel, "n": len(f2s), "f2_med": med, "lit": lit_hz, "verdict": verdict}
        )

    pf = table1["F"]
    zone_thresholds = {
        "clearly_male": ("<", round(pf[5], 3)),
        "leans_male": (f"[{round(pf[5], 3)}, {round(pf[25], 3)})", None),
        "neutral": (f"[{round(pf[25], 3)}, {round(pf[75], 3)})", None),
        "leans_female": (f"[{round(pf[75], 3)}, {round(pf[95], 3)})", None),
        "clearly_female": ("≥", round(pf[95], 3)),
    }

    out_path = Path(args.report_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append(f"# en-US resonance baseline ({date.today()})\n")
    if args.corpus_mode == "librispeech":
        source_desc = (
            f"LibriSpeech {LIBRISPEECH_SUBSET} subset at `{args.librispeech}` "
            f"(seed={LIBRISPEECH_SEED}, target_f={args.target_spk_f}, "
            f"target_m={args.target_spk_m}, clips_per_spk={args.clips_per_spk}). "
            "Transcripts pulled from .trans.txt files (no ASR)."
        )
    else:
        source_desc = (
            f"hand-curated VCTK + CMU-Arctic + test fixtures at `{args.corpus}` "
            "(cis_female_en + cis_male_en)."
        )
    lines.append(
        f"**Source**: {source_desc}  Total clips: {len(clip_data)}; "
        f"speakers: {len(by_spk)}.  Per-spk median is the median of that "
        "speaker's clip-medians.\n"
    )
    lines.append(
        "Sidecar formant ceiling: pinned 5000 Hz (en NOT in `_ADAPTIVE_LANGS`).  "
        "stats.json baseline: cmudict-derived, 5000 Hz extraction (upstream).\n"
    )
    lines.append(
        "**⚠ Small sample**: ~16 unique speakers total — P5/P95 estimates have "
        "wide CIs.  Treat as directional, not as a calibration anchor without "
        "a larger corpus (CV en, LibriSpeech).\n\n"
    )

    lines.append("## Table 1 — per-spk median `resonance` distribution\n")
    lines.append("| sex | n_spk | P5 | P25 | P50 | P75 | P95 | mean |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for sex in ("F", "M"):
        t = table1[sex]
        lines.append(
            f"| {sex} | {t['n']} | {t[5]:.3f} | {t[25]:.3f} | {t[50]:.3f} | {t[75]:.3f} | {t[95]:.3f} | {t['mean']:.3f} |"
        )
    lines.append("")

    lines.append("## Table 2 — per-vowel z-scores (relative to `stats.json`)\n")
    lines.append(
        "ARPABET phones with stress digits stripped (IY1/IY2/IY0 → IY).  "
        "Z relative to the female reference distribution in `stats.json`.\n"
    )
    for sex in ("F", "M"):
        bucket = per_vowel_F if sex == "F" else per_vowel_M
        lines.append(f"### {sex} speakers\n")
        lines.append(
            "| vowel | n | F1_med Hz | F2_med Hz | F3_med Hz | z_F1_med | z_F2_med | z_F3_med | sat_rate |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for v in sorted(bucket.keys(), key=lambda x: -len(bucket[x].get("z_F1", []))):
            d = bucket[v]
            n = len(d.get("z_F1", []))
            if n < 3:
                continue
            f1m = statistics.median(d["F1"]) if d["F1"] else float("nan")
            f2m = statistics.median(d["F2"]) if d["F2"] else float("nan")
            f3m = statistics.median(d["F3"]) if d["F3"] else float("nan")
            z1m = statistics.median(d["z_F1"]) if d["z_F1"] else float("nan")
            z2m = statistics.median(d["z_F2"]) if d["z_F2"] else float("nan")
            z3m = statistics.median(d["z_F3"]) if d["z_F3"] else float("nan")
            sat_list = per_vowel_sat[sex].get(v, [])
            sat = (sum(sat_list) / len(sat_list)) if sat_list else float("nan")
            lines.append(
                f"| {v} | {n} | {f1m:.0f} | {f2m:.0f} | {f3m:.0f} | "
                f"{z1m:+.2f} | {z2m:+.2f} | {z3m:+.2f} | {sat:.2f} |"
            )
        lines.append("")

    lines.append("## Table 3 — F2 collapse check (female speakers vs Hillenbrand 1995)\n")
    lines.append("| vowel | n | F2_med (this run) | F2 lit | ratio | verdict |")
    lines.append("|---|---|---|---|---|---|")
    for r in collapse_rows:
        f2m = "—" if r["f2_med"] is None else f"{r['f2_med']:.0f}"
        ratio = "—" if r["f2_med"] is None else f"{r['f2_med'] / r['lit']:.2f}"
        lines.append(f"| {r['vowel']} | {r['n']} | {f2m} | {r['lit']} | {ratio} | {r['verdict']} |")
    lines.append("")

    lines.append("## Table 4 — 5-zone candidate thresholds (en F percentiles)\n")
    lines.append("| zone_key | range |")
    lines.append("|---|---|")
    for k, (op, num) in zone_thresholds.items():
        rng = f"{op} {num}" if num is not None else op
        lines.append(f"| `{k}` | {rng} |")
    lines.append("")

    lines.append("## Decision points\n")
    collapsed = [r for r in collapse_rows if r["verdict"] == "COLLAPSE"]
    soft = [r for r in collapse_rows if r["verdict"] == "low"]
    if collapsed:
        worst = collapsed[0]
        lines.append(
            f"1. **F2 collapse confirmed** on /{', /'.join(r['vowel'] for r in collapsed)}/ "
            f"(worst: /{worst['vowel']}/ measured {worst['f2_med']:.0f} Hz vs Hillenbrand "
            f"{worst['lit']} Hz = {worst['f2_med'] / worst['lit']:.0%}).  Same fingerprint as "
            "fr/zh; recommend adding en to `_ADAPTIVE_LANGS` once stats.json is re-trained @ 5500 Hz."
        )
        if soft:
            lines.append(f"   Soft-low: /{', /'.join(r['vowel'] for r in soft)}/.")
    elif soft:
        lines.append(
            f"1. **F2 soft-low** on /{', /'.join(r['vowel'] for r in soft)}/ — below Hillenbrand "
            "but >75 %.  Adding en to adaptive ceiling would help marginally."
        )
    else:
        lines.append(
            "1. **F2 collapse not detected** — pinned 5000 Hz holds for en within this sample."
        )

    f_meds = by_sex_spkmed["F"]
    n_sat_F_top = sum(1 for v in f_meds if v >= 0.98)
    lines.append(
        f"2. **Score ceiling check**: {n_sat_F_top}/{len(f_meds)} F speakers saturate "
        f"medianResonance ≥ 0.98; F P95 = {table1['F'][95]:.3f}."
    )

    overlap_lo = max(table1["M"][5], table1["F"][5])
    overlap_hi = min(table1["M"][95], table1["F"][95])
    if overlap_lo < overlap_hi:
        lines.append(f"3. **F-M overlap band**: [{overlap_lo:.3f}, {overlap_hi:.3f}].")
    gap = table1["F"][50] - table1["M"][50]
    lines.append(f"4. Female–male median gap (P50): {gap:+.3f}.")
    lines.append(
        "5. **Sample size warning**: only ~16 speakers total.  Treat conclusions as "
        "directional.  For Phase B-style retrain (en @ 5500 Hz), download Common "
        "Voice en or LibriSpeech first."
    )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("wrote %s", out_path)
    return out_path


# ── cli ────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument(
        "--corpus-mode",
        choices=("curated", "librispeech"),
        default="curated",
        help="curated = cis_female_en/cis_male_en (~16 spk); librispeech = train-clean-100 sample",
    )
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--librispeech", default=str(DEFAULT_LIBRISPEECH))
    ap.add_argument("--target-spk-f", type=int, default=50)
    ap.add_argument("--target-spk-m", type=int, default=30)
    ap.add_argument("--clips-per-spk", type=int, default=3)
    ap.add_argument("--raw", default=str(DEFAULT_RAW))
    ap.add_argument("--report-out", default=str(DEFAULT_REPORT))
    ap.add_argument("--sidecar", default=SIDECAR_DEFAULT)
    ap.add_argument("--token-env", default="ENGINE_C_SIDECAR_TOKEN")
    args = ap.parse_args()
    # LibriSpeech raws live in their own scratch tree so curated + librispeech
    # caches don't collide — same wav stems would shadow each other otherwise.
    if args.corpus_mode == "librispeech" and args.raw == str(DEFAULT_RAW):
        args.raw = str(Path.home() / "scratch" / "en_phase_a" / "raw_librispeech")

    _drift_guard()

    if not (args.analyze or args.report):
        args.analyze = args.report = True

    if args.analyze:
        failed = analyze_phase(args)
        if failed > 0:
            log.warning("analyze finished with %d failures — report may be incomplete", failed)
    if args.report:
        report_phase(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
