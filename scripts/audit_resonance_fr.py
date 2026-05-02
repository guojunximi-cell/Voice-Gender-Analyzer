"""Phase A diagnostic: empirical fr-FR resonance distribution.

Mirror of scripts/audit_resonance_zh.py, but consumes Common Voice fr v17
via the manifest produced by scripts/stage_cv_fr_subset.py instead of the
AISHELL-3 directory tree.  Same 4-table report shape so post-Phase-B
diffs against zh are apples-to-apples.

Pipeline::

    ~/scratch/cv_fr_ext4/{clips/, subset.tsv}  ──[stage]──>  stitched wavs
                                                          (ffmpeg concat 5 mp3s)
    stitched wavs                              ──[analyze]─> sidecar JSON
    raw JSON + stats_fr.json                   ──[report]──> markdown report

Usage::

    python scripts/stage_cv_fr_subset.py    # one-shot, ~5 min on 9P
    python scripts/audit_resonance_fr.py    # stage + analyze + report

Sidecar must be reachable.  Bring it up with::

    docker compose --profile engine-c up -d
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import statistics
import subprocess
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("audit_fr")

REPO_ROOT = Path(__file__).resolve().parent.parent
SIDECAR_DEFAULT = "http://localhost:8001"
DEFAULT_SUBSET = Path.home() / "scratch" / "cv_fr_ext4"
DEFAULT_STITCHED = Path.home() / "scratch" / "fr_phase_a" / "stitched"
DEFAULT_RAW = Path.home() / "scratch" / "fr_phase_a" / "raw"
DEFAULT_REPORT = REPO_ROOT / "tests" / "reports" / f"fr_resonance_baseline_{date.today()}.md"
STATS_FR_PATH = REPO_ROOT / "voiceya" / "sidecars" / "visualizer-backend" / "stats_fr.json"

# Vowel nuclei from acousticgender/library/resonance.py FR_VOWELS — kept in
# sync via drift guard at startup.  NFC normalisation handles nasal vowels
# (combining tilde U+0303) consistently across the corpus.
FR_VOWELS = {
    "a",
    "ɑ",
    "e",
    "ɛ",
    "i",
    "o",
    "ɔ",
    "u",
    "y",
    "ø",
    "œ",
    "ə",
    "ɛ̃",
    "ɑ̃",
    "ɔ̃",
    "œ̃",
}

# Literature reference values for fr female F2 — used for the F2-collapse
# check.  Sources: Calliope 1989/2002 (Le langage parlé français) +
# Gendrot/Adda-Decker 2007 LREC ("Phonetic characteristics of French oral
# vowels").  Ranges are tighter than zh because fr has less inter-speaker
# variation in vowel space.  Nasal vowels intentionally absent — nasal
# coupling lowers F2 by 100-300 Hz unpredictably and would noise the
# collapse signal.
LIT_FEMALE_F2_HZ = {
    "i": 2700,
    "y": 1900,
    "e": 2400,
    "ɛ": 2000,
    "ə": 1500,
    "ø": 1700,
    "œ": 1600,
    "a": 1500,
    "ɑ": 1200,
    "o": 950,
    "ɔ": 1100,
    "u": 850,
}


def _drift_guard() -> None:
    """Crash early if our local FR_VOWELS diverges from the vendored set."""
    res_py = (
        REPO_ROOT
        / "voiceya"
        / "sidecars"
        / "visualizer-backend"
        / "acousticgender"
        / "library"
        / "resonance.py"
    )
    src = res_py.read_text(encoding="utf-8")
    import re as _re

    m = _re.search(r"FR_VOWELS\s*=\s*\{([^}]+)\}", src, _re.DOTALL)
    if not m:
        raise RuntimeError("could not find FR_VOWELS in resonance.py — refresh drift guard")
    vendored = set(_re.findall(r"'([^']+)'", m.group(1)))
    # NFC-normalise both sides — vendored uses combining-tilde nasal vowels
    # too, but a future PR could mix in NFD; normalising is cheap insurance.
    local_nfc = {unicodedata.normalize("NFC", v) for v in FR_VOWELS}
    vendored_nfc = {unicodedata.normalize("NFC", v) for v in vendored}
    if vendored_nfc != local_nfc:
        raise RuntimeError(f"FR_VOWELS drift: vendored={vendored} ours={FR_VOWELS}")


# ── stage ────────────────────────────────────────────────────────────


def load_subset(subset_dir: Path) -> list[dict]:
    """Read the manifest produced by stage_cv_fr_subset.py."""
    path = subset_dir / "subset.tsv"
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            rows.append(r)
    return rows


def pick_speakers(
    subset: list[dict],
    n_female: int,
    n_male: int,
    seed: int,
    clips_per_spk: int,
) -> list[tuple[str, str, list[dict]]]:
    """Return [(client_id, sex, clips)] picked balanced.

    Sex code: "F" = female_feminine, "M" = male_masculine.  Each speaker
    contributes up to ``clips_per_spk`` clips so the stitched audio crosses
    multiple sentences (richer phone coverage).
    """
    by_speaker: dict[str, list[dict]] = defaultdict(list)
    for row in subset:
        by_speaker[row["client_id"]].append(row)

    # Sort speakers by gender, deterministic order before shuffle.
    female_spks = sorted(s for s, rs in by_speaker.items() if rs[0]["gender"] == "female_feminine")
    male_spks = sorted(s for s, rs in by_speaker.items() if rs[0]["gender"] == "male_masculine")

    # Need at least clips_per_spk segments per speaker; CV fr's distribution
    # is long-tailed (lots of one-clip speakers), so filter early.
    female_spks = [s for s in female_spks if len(by_speaker[s]) >= clips_per_spk]
    male_spks = [s for s in male_spks if len(by_speaker[s]) >= clips_per_spk]

    rng = random.Random(seed)
    rng.shuffle(female_spks)
    rng.shuffle(male_spks)

    picked: list[tuple[str, str, list[dict]]] = []
    for s in female_spks[:n_female]:
        picked.append((s, "F", by_speaker[s][:clips_per_spk]))
    for s in male_spks[:n_male]:
        picked.append((s, "M", by_speaker[s][:clips_per_spk]))
    return picked


def stitch_one(
    clips: list[dict],
    subset_dir: Path,
    out_wav: Path,
) -> dict | None:
    """ffmpeg-concat ``clips`` (CV fr mp3s) into a single wav.

    Re-encoding is required because mp3 stream-copy concat is finicky with
    differing encoder settings; we lock to 16 kHz mono PCM s16le, which is
    what the sidecar's preprocessing.process resamples to anyway.
    """
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if out_wav.exists() and out_wav.stat().st_size > 1024:
        # Idempotent: already stitched.  Read back the cached transcript by
        # joining the source sentences in order.
        return {
            "wav": str(out_wav),
            "transcript": " ".join(c["sentence"] for c in clips),
            "source_clips": [c["path"] for c in clips],
            "duration_sec": _probe_duration(out_wav),
        }

    list_path = out_wav.with_suffix(".concat.txt")
    list_path.write_text(
        "".join(f"file '{(subset_dir / 'clips' / c['path']).absolute()}'\n" for c in clips),
        encoding="utf-8",
    )
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(out_wav),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as exc:
        log.warning(
            "ffmpeg failed for %s: %s", out_wav.name, exc.stderr.decode("utf-8", "replace")[-300:]
        )
        return None
    finally:
        list_path.unlink(missing_ok=True)

    return {
        "wav": str(out_wav),
        "transcript": " ".join(c["sentence"] for c in clips),
        "source_clips": [c["path"] for c in clips],
        "duration_sec": _probe_duration(out_wav),
    }


def _probe_duration(wav: Path) -> float:
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(wav),
            ],
            timeout=10,
        )
        return round(float(out.strip()), 3)
    except (subprocess.CalledProcessError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def stage_phase(args: argparse.Namespace) -> Path:
    subset_dir = Path(args.subset_dir)
    if not (subset_dir / "subset.tsv").is_file():
        log.error(
            "subset.tsv not found under %s — run scripts/stage_cv_fr_subset.py first",
            subset_dir,
        )
        sys.exit(2)

    subset = load_subset(subset_dir)
    log.info("loaded %d subset rows", len(subset))
    picked = pick_speakers(
        subset,
        args.n_female,
        args.n_male,
        args.seed,
        args.clips_per_spk,
    )
    log.info("picked %d speakers (%d F / %d M target)", len(picked), args.n_female, args.n_male)

    stitched_root = Path(args.stitched)
    manifest_path = stitched_root / "manifest.jsonl"
    stitched_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    t0 = time.time()
    for i, (spk, sex, clips) in enumerate(picked, 1):
        out_wav = stitched_root / sex / f"{spk[:16]}.wav"
        row = stitch_one(clips, subset_dir, out_wav)
        if row is None:
            continue
        row.update({"spk_id": spk, "sex": sex})
        rows.append(row)
        if i % 10 == 0 or i == len(picked):
            log.info("staged %d/%d spk (%.1fs)", i, len(picked), time.time() - t0)

    manifest_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    log.info("wrote %s (%d rows)", manifest_path, len(rows))
    return manifest_path


# ── analyze ──────────────────────────────────────────────────────────


def _post_one(sidecar_url: str, token: str, wav: Path, transcript: str) -> dict:
    import requests  # noqa: PLC0415

    headers = {}
    if token:
        headers["X-Engine-C-Token"] = token
    with wav.open("rb") as f:
        resp = requests.post(
            f"{sidecar_url}/engine_c/analyze",
            files={"audio": (wav.name, f, "audio/wav")},
            data={"transcript": transcript, "language": "fr-FR"},
            headers=headers,
            timeout=300,
        )
    resp.raise_for_status()
    return resp.json()


def analyze_phase(args: argparse.Namespace) -> int:
    manifest = Path(args.stitched) / "manifest.jsonl"
    if not manifest.is_file():
        log.error("missing %s — run --stage first", manifest)
        sys.exit(2)

    rows = [json.loads(line) for line in manifest.read_text().splitlines() if line]
    raw_dir = Path(args.raw)
    raw_dir.mkdir(parents=True, exist_ok=True)
    token = os.environ.get(args.token_env, "").strip()

    import requests  # noqa: PLC0415

    try:
        health = requests.get(f"{args.sidecar}/healthz", timeout=10).json()
    except Exception as exc:
        log.error("sidecar unreachable at %s: %s", args.sidecar, exc)
        sys.exit(2)
    if "fr" not in health.get("languages", []):
        log.error("sidecar /healthz does not advertise fr: %s", health)
        sys.exit(2)
    log.info("sidecar healthy: %s", health)

    t0 = time.time()
    done = skipped = failed = 0
    for i, row in enumerate(rows, 1):
        out = raw_dir / f"{row['spk_id'][:16]}.json"
        if out.exists() and out.stat().st_size > 256:
            skipped += 1
            continue
        try:
            data = _post_one(args.sidecar, token, Path(row["wav"]), row["transcript"])
        except Exception as exc:
            log.warning("spk %s: %s", row["spk_id"][:16], exc)
            failed += 1
            continue
        out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        done += 1
        if i % 5 == 0 or i == len(rows):
            elapsed = time.time() - t0
            rate = (done + 0.001) / elapsed
            eta = (len(rows) - i) / rate if rate > 0 else 0
            log.info(
                "analyze %d/%d  done=%d skipped=%d failed=%d  rate=%.2f/s  eta=%.0fs",
                i,
                len(rows),
                done,
                skipped,
                failed,
                rate,
                eta,
            )
    log.info("done=%d skipped=%d failed=%d wall=%.0fs", done, skipped, failed, time.time() - t0)
    return failed


# ── report ───────────────────────────────────────────────────────────


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
    manifest_path = Path(args.stitched) / "manifest.jsonl"
    if not manifest_path.is_file():
        log.error("missing %s — run --stage first", manifest_path)
        sys.exit(2)
    rows = [json.loads(line) for line in manifest_path.read_text().splitlines() if line]
    raw_dir = Path(args.raw)
    stats = json.loads(STATS_FR_PATH.read_text(encoding="utf-8"))

    spk_data: list[dict] = []
    dropped: list[tuple[str, str]] = []
    for row in rows:
        raw = raw_dir / f"{row['spk_id'][:16]}.json"
        if not raw.is_file():
            dropped.append((row["spk_id"][:16], "no raw json"))
            continue
        try:
            ec = json.loads(raw.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            dropped.append((row["spk_id"][:16], "json decode"))
            continue
        if not ec.get("phones"):
            dropped.append((row["spk_id"][:16], "zero phones"))
            continue
        spk_data.append(
            {
                "spk_id": row["spk_id"][:16],
                "sex": row["sex"],
                "duration_sec": row.get("duration_sec"),
                "phones": ec["phones"],
                "medianResonance": ec.get("medianResonance"),
                "meanResonance": ec.get("meanResonance"),
                "ceiling_hz": ec.get("formant_ceiling_hz"),
            }
        )

    by_sex_med: dict[str, list[float]] = {"F": [], "M": []}
    for s in spk_data:
        med = s.get("medianResonance")
        if med is None:
            rs = [p.get("resonance") for p in s["phones"] if p.get("resonance") is not None]
            if rs:
                med = statistics.median(rs)
        if med is not None:
            by_sex_med[s["sex"]].append(float(med))

    pcts = (5, 25, 50, 75, 95)
    table1 = {
        sex: {
            "n": len(vs),
            **_percentiles(vs, pcts),
            "mean": statistics.mean(vs) if vs else float("nan"),
        }
        for sex, vs in by_sex_med.items()
    }

    per_vowel_F: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    per_vowel_M: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    per_vowel_sat: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))

    for s in spk_data:
        bucket = per_vowel_F if s["sex"] == "F" else per_vowel_M
        for ph in s["phones"]:
            label_raw = ph.get("phoneme")
            if not label_raw:
                continue
            label = unicodedata.normalize("NFC", label_raw)
            if label not in FR_VOWELS:
                continue
            ref = stats.get(label)
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
                per_vowel_sat[s["sex"]][label].append(1 if (res <= 0.02 or res >= 0.98) else 0)

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

    # Distribution of which formant ceiling the selector picked across speakers.
    ceiling_hist: dict[int, int] = defaultdict(int)
    for s in spk_data:
        c = s.get("ceiling_hz")
        if c is not None:
            ceiling_hist[c] += 1

    out_path = Path(args.report_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append(f"# fr-FR resonance baseline ({date.today()})\n")
    lines.append(
        f"**Source**: Common Voice fr v17 train (subset staged at "
        f"`{args.subset_dir}`), sampled {args.n_female}F + {args.n_male}M speakers, "
        f"{args.clips_per_spk} clips/spk concatenated, seed={args.seed}.\n"
    )
    lines.append(
        f"Sidecar formant ceiling: adaptive (fr in `_ADAPTIVE_LANGS`).  "
        f"stats_fr.json baseline: see `{STATS_FR_PATH.relative_to(REPO_ROOT)}`.\n"
    )
    lines.append(
        f"Speakers analyzed: {len(spk_data)} "
        f"({sum(1 for s in spk_data if s['sex'] == 'F')}F / "
        f"{sum(1 for s in spk_data if s['sex'] == 'M')}M).  Dropped: {len(dropped)}.\n\n"
    )

    lines.append("## Table 1 — per-spk median `resonance` distribution\n")
    lines.append("| sex | n | P5 | P25 | P50 | P75 | P95 | mean |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for sex in ("F", "M"):
        t = table1[sex]
        lines.append(
            f"| {sex} | {t['n']} | {t[5]:.3f} | {t[25]:.3f} | {t[50]:.3f} | {t[75]:.3f} | {t[95]:.3f} | {t['mean']:.3f} |"
        )
    lines.append("")

    lines.append("## Table 1b — adaptive-ceiling pick distribution\n")
    lines.append("| ceiling Hz | n speakers |")
    lines.append("|---|---|")
    for c in sorted(ceiling_hist):
        lines.append(f"| {c} | {ceiling_hist[c]} |")
    lines.append("")

    lines.append("## Table 2 — per-vowel z-scores (relative to `stats_fr.json`)\n")
    lines.append(
        "Z is computed against the reference distribution in `stats_fr.json`. "
        "Negative ⇒ measurement falls below the reference mean (more male-like in F1/F2 space).  "
        "`sat_rate` = fraction of `resonance` values clamped to [0, 0.02] ∪ [0.98, 1].\n"
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

    lines.append("## Table 3 — F2 collapse check (female speakers vs literature)\n")
    lines.append(
        "Literature targets: Calliope 2002 + Gendrot/Adda-Decker 2007 LREC.  "
        "Nasal vowels excluded (nasal coupling lowers F2 by 100-300 Hz unpredictably).\n"
    )
    lines.append("| vowel | n | F2_med (this run) | F2 lit | ratio | verdict |")
    lines.append("|---|---|---|---|---|---|")
    for r in collapse_rows:
        f2m = "—" if r["f2_med"] is None else f"{r['f2_med']:.0f}"
        ratio = "—" if r["f2_med"] is None else f"{r['f2_med'] / r['lit']:.2f}"
        lines.append(f"| {r['vowel']} | {r['n']} | {f2m} | {r['lit']} | {ratio} | {r['verdict']} |")
    lines.append("")

    lines.append("## Table 4 — 5-zone candidate thresholds for `resonance_zone_key`\n")
    lines.append(
        "Anchored to fr female P5/P25/P75/P95 from Table 1.  `resonance_calibration._ZONES_FR` "
        "currently inherits the zh table; this report's numbers are the input for re-anchoring.\n"
    )
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
            f"(worst: /{worst['vowel']}/ measured {worst['f2_med']:.0f} Hz vs literature "
            f"{worst['lit']} Hz = {worst['f2_med'] / worst['lit']:.0%}).  Recommend re-train "
            "stats_fr.json @ 5500 Hz (mirror the Phase B zh path)."
        )
        if soft:
            lines.append(
                f"   Soft-low (75-85 % of literature, watch list): /{', /'.join(r['vowel'] for r in soft)}/."
            )
    elif soft:
        lines.append(
            f"1. **F2 soft-low** on /{', /'.join(r['vowel'] for r in soft)}/.  Below literature but >75 %; "
            "marginal — re-train still recommended for consistency with zh."
        )
    else:
        lines.append("1. **F2 collapse not detected** — current pipeline holds for fr.")

    f_meds = by_sex_med["F"]
    n_sat_F_top = sum(1 for v in f_meds if v >= 0.98)
    lines.append(
        f"2. **Score ceiling check**: {n_sat_F_top}/{len(f_meds)} F speakers "
        f"({100 * n_sat_F_top / max(1, len(f_meds)):.0f} %) saturate medianResonance ≥ 0.98; "
        f"F P95 = {table1['F'][95]:.3f}.  "
        f"M P50 = {table1['M'][50]:.3f}.  "
        "If F saturation > 15 %, the runtime ceiling lift is over-correcting against "
        "the 5000-Hz-baseline stats_fr.json — Phase B retrain will compress the F distribution."
    )

    overlap_lo = max(table1["M"][5], table1["F"][5])
    overlap_hi = min(table1["M"][95], table1["F"][95])
    if overlap_lo < overlap_hi:
        lines.append(
            f"3. **F-M overlap band**: [{overlap_lo:.3f}, {overlap_hi:.3f}].  Inside this band the score "
            "isn't sex-discriminative on its own."
        )
    gap = table1["F"][50] - table1["M"][50]
    lines.append(
        f"4. Female–male median gap (P50): {gap:+.3f}.  "
        f"{'Wide enough for percentile-anchored zones' if gap > 0.15 else 'Narrow — needs investigation'}."
    )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("wrote %s", out_path)
    return out_path


# ── cli ──────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--stage", action="store_true")
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--subset-dir", default=str(DEFAULT_SUBSET))
    ap.add_argument("--stitched", default=str(DEFAULT_STITCHED))
    ap.add_argument("--raw", default=str(DEFAULT_RAW))
    ap.add_argument("--report-out", default=str(DEFAULT_REPORT))
    ap.add_argument("--n-female", type=int, default=50)
    ap.add_argument("--n-male", type=int, default=50)
    ap.add_argument("--clips-per-spk", type=int, default=5)
    ap.add_argument("--sidecar", default=SIDECAR_DEFAULT)
    ap.add_argument("--token-env", default="ENGINE_C_SIDECAR_TOKEN")
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()

    _drift_guard()

    if not (args.stage or args.analyze or args.report):
        args.stage = args.analyze = args.report = True

    if args.stage:
        stage_phase(args)
    if args.analyze:
        failed = analyze_phase(args)
        if failed > 0:
            log.warning("analyze finished with %d failures — report may be incomplete", failed)
    if args.report:
        report_phase(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
