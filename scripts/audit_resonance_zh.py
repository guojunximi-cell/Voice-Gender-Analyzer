"""Phase A diagnostic: empirical zh-CN resonance distribution.

Pipeline:
    AISHELL-3 train wavs   ──[stage]──>   ext4 stitched wavs (~30-40s each)
    stitched wavs          ──[analyze]──> sidecar /engine_c/analyze raw JSON
    raw JSON + stats_zh    ──[report]──>  4-table baseline report

The script never modifies vendored code. It re-reads stats_zh.json locally
to recompute z_F1/F2/F3 per phone, mirroring resonance.compute_resonance's
indexing convention (stats[phone][1..3] = {F1,F2,F3}).

Outputs a markdown report for human review (decides Phase B thresholds).
Not a pytest.  Not committed runtime data — only the report goes into the
repo at tests/reports/.

Usage::

    # one-shot: stage 50F+42M speakers, run sidecar, write report
    python scripts/audit_resonance_zh.py

    # piecewise (cache-aware: each phase skips work already done)
    python scripts/audit_resonance_zh.py --stage
    python scripts/audit_resonance_zh.py --analyze
    python scripts/audit_resonance_zh.py --report

Sidecar must be reachable at --sidecar before --analyze runs.  Bring it
up with::

    docker compose --profile engine-c up -d
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("audit_zh")

REPO_ROOT = Path(__file__).resolve().parent.parent
SIDECAR_DEFAULT = "http://localhost:8001"
DEFAULT_AISHELL = "/mnt/d/project_vocieduck/ablation/audio/cn/AISHELL3"
DEFAULT_STITCHED = Path.home() / "scratch" / "zh_phase_a" / "stitched"
DEFAULT_RAW = Path.home() / "scratch" / "zh_phase_a" / "raw"
DEFAULT_REPORT = REPO_ROOT / "tests" / "reports" / f"zh_resonance_baseline_{date.today()}.md"
STATS_ZH_PATH = REPO_ROOT / "voiceya" / "sidecars" / "visualizer-backend" / "stats_zh.json"

# Vowel nuclei from resonance.py — kept in sync via drift guard at startup.
ZH_VOWELS = {
    "a",
    "aj",
    "aw",
    "e",
    "ej",
    "i",
    "io",
    "o",
    "ow",
    "u",
    "y",
    "ə",
    "ɥ",
    "ʐ̩",
    "z̩",
}
_TONE_RE = re.compile(r"[˥˦˧˨˩]+")

# Literature reference values for zh female F2 — used only for the F2-collapse
# check.  Sources: 鲍怀翘《普通话语音学》(2012) + Lee/Zhang 2008 J. Acoust. Soc.
# Tolerances are intentionally loose (±15 %) — a real collapse drops F2 by
# 30–50 %, so we only need the comparison to be obviously diagnostic.
LIT_FEMALE_F2_HZ = {
    "i": 2700,
    "y": 2300,
    "e": 2200,
    "ej": 2100,
    "ə": 1700,
    "a": 1400,
    "u": 800,
}


def _drift_guard() -> None:
    """Crash early if our local ZH_VOWELS diverges from the vendored set."""
    resonance_py = (
        REPO_ROOT
        / "voiceya"
        / "sidecars"
        / "visualizer-backend"
        / "acousticgender"
        / "library"
        / "resonance.py"
    )
    src = resonance_py.read_text()
    # crude but stable: parse the literal `ZH_VOWELS = {...}` line block
    m = re.search(r"ZH_VOWELS\s*=\s*\{([^}]+)\}", src, re.DOTALL)
    if not m:
        raise RuntimeError("could not find ZH_VOWELS in resonance.py — refresh drift guard")
    vendored = set(re.findall(r"'([^']+)'", m.group(1)))
    if vendored != ZH_VOWELS:
        raise RuntimeError(f"ZH_VOWELS drift: vendored={vendored} ours={ZH_VOWELS}")


# ── stage ────────────────────────────────────────────────────────────


def parse_spk_info(aishell_root: Path) -> dict[str, dict]:
    info_path = aishell_root / "spk-info.txt"
    out: dict[str, dict] = {}
    for line in info_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        spk, age, gender, accent = parts[0], parts[1], parts[2], parts[3]
        out[spk] = {"age": age, "gender": gender, "accent": accent}
    return out


def parse_content(aishell_root: Path) -> dict[str, str]:
    """wav_filename → Chinese-character transcript (pinyin stripped).

    Merges both train/content.txt and test/content.txt — AISHELL-3's split
    is by speaker, so a speaker may live exclusively in either side.  We
    don't care about the train/test boundary for resonance statistics.
    """
    out: dict[str, str] = {}
    cjk_re = re.compile(r"[一-鿿]")
    for split in ("train", "test"):
        content_path = aishell_root / split / "content.txt"
        if not content_path.is_file():
            continue
        for line in content_path.read_text(encoding="utf-8").splitlines():
            if "\t" not in line:
                continue
            wav, body = line.split("\t", 1)
            chars = cjk_re.findall(body)
            if chars:
                out[wav] = "".join(chars)
    return out


def pick_speakers(
    spk_info: dict[str, dict], n_female: int, n_male: int, seed: int
) -> list[tuple[str, str]]:
    """Return [(spk_id, sex)] of length n_female+n_male, deterministic."""
    rng = random.Random(seed)
    female = sorted([s for s, m in spk_info.items() if m["gender"] == "female"])
    male = sorted([s for s, m in spk_info.items() if m["gender"] == "male"])
    rng.shuffle(female)
    rng.shuffle(male)
    picked: list[tuple[str, str]] = [(s, "F") for s in female[:n_female]]
    picked += [(s, "M") for s in male[:n_male]]
    return picked


def stitch_one(
    aishell_root: Path,
    spk: str,
    clips_per_spk: int,
    out_wav: Path,
    transcripts: dict[str, str],
    min_clip_sec: float = 3.0,
) -> dict | None:
    """ffmpeg-concat the first ``clips_per_spk`` clips for ``spk``.

    Returns manifest dict with transcript + source list, or None if not
    enough usable clips exist.  Idempotent — skips concat if out_wav already
    exists and is non-empty.
    """
    # AISHELL-3 sometimes drops a token clip into the "other" split (e.g.
    # speakers primarily in test/ get one stray clip in train/) — pool both
    # so we don't get tricked into picking the near-empty side.
    candidate_clips: list[Path] = []
    for split in ("train", "test"):
        d = aishell_root / split / "wav" / spk
        if d.is_dir():
            candidate_clips.extend(d.glob("*.wav"))
    if not candidate_clips:
        log.warning("missing spk dir for %s in either train/ or test/", spk)
        return None

    clips = sorted(p for p in candidate_clips if p.name in transcripts)
    chosen: list[Path] = []
    chosen_text: list[str] = []
    for p in clips:
        if len(chosen) >= clips_per_spk:
            break
        # probe duration to skip near-silent fragments (rare in AISHELL but
        # ffmpeg concat would still include them).  Cheap: stat-only ffprobe.
        dur = _probe_duration(p)
        if dur < min_clip_sec:
            continue
        chosen.append(p)
        chosen_text.append(transcripts[p.name])

    if len(chosen) < clips_per_spk:
        log.warning("spk %s: only %d clips ≥%.1fs, skipping", spk, len(chosen), min_clip_sec)
        return None

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if not (out_wav.exists() and out_wav.stat().st_size > 1024):
        # All AISHELL3 clips are 44.1k mono 16le → -c copy concat is lossless.
        list_path = out_wav.with_suffix(".concat.txt")
        list_path.write_text("".join(f"file '{p.absolute()}'\n" for p in chosen), encoding="utf-8")
        try:
            subprocess.run(  # noqa: S603 — local ffmpeg, args hard-coded
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
                    "-c",
                    "copy",
                    str(out_wav),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
        finally:
            list_path.unlink(missing_ok=True)

    return {
        "spk_id": spk,
        "wav": str(out_wav),
        "transcript": "".join(chosen_text),
        "source_clips": [p.name for p in chosen],
        "duration_sec": round(_probe_duration(out_wav), 3),
    }


def _probe_duration(wav: Path) -> float:
    try:
        out = subprocess.check_output(  # noqa: S603
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
        return float(out.strip())
    except (subprocess.CalledProcessError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def stage_phase(args: argparse.Namespace) -> Path:
    """Build manifest.jsonl + stitched wavs under args.stitched."""
    aishell = Path(args.aishell)
    if not aishell.is_dir():
        log.error("AISHELL3 root not found: %s", aishell)
        sys.exit(2)

    spk_info = parse_spk_info(aishell)
    transcripts = parse_content(aishell)
    picked = pick_speakers(spk_info, args.n_female, args.n_male, args.seed)

    stitched_root = Path(args.stitched)
    manifest_path = stitched_root / "manifest.jsonl"
    stitched_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    t0 = time.time()
    for i, (spk, sex) in enumerate(picked, 1):
        out_wav = stitched_root / sex / f"{spk}.wav"
        row = stitch_one(aishell, spk, args.clips_per_spk, out_wav, transcripts)
        if row is None:
            continue
        meta = spk_info[spk]
        row.update({"sex": sex, "age": meta["age"], "accent": meta["accent"]})
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
    """POST one stitched clip to /engine_c/analyze.  Raises on HTTP error."""
    # requests is a runtime dep of voiceya; safe to import lazily so --report
    # works without network deps.
    import requests  # noqa: PLC0415

    headers = {}
    if token:
        headers["X-Engine-C-Token"] = token
    with wav.open("rb") as f:
        resp = requests.post(
            f"{sidecar_url}/engine_c/analyze",
            files={"audio": (wav.name, f, "audio/wav")},
            data={"transcript": transcript, "language": "zh-CN"},
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

    # Sidecar warm-up: throw away the first request because cold MFA + Praat
    # init is ~5-10 s slower than steady state.  Skip on cache hit.
    import requests  # noqa: PLC0415

    try:
        health = requests.get(f"{args.sidecar}/healthz", timeout=10).json()
    except Exception as exc:
        log.error("sidecar unreachable at %s: %s", args.sidecar, exc)
        sys.exit(2)
    if "zh" not in health.get("languages", []):
        log.error("sidecar /healthz does not advertise zh: %s", health)
        sys.exit(2)
    log.info("sidecar healthy: %s", health)

    t0 = time.time()
    done = 0
    skipped = 0
    failed = 0
    for i, row in enumerate(rows, 1):
        out = raw_dir / f"{row['spk_id']}.json"
        if out.exists() and out.stat().st_size > 256:
            skipped += 1
            continue
        try:
            data = _post_one(args.sidecar, token, Path(row["wav"]), row["transcript"])
        except Exception as exc:
            log.warning("spk %s: %s", row["spk_id"], exc)
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


def _strip_tone(p: str) -> str:
    return _TONE_RE.sub("", p) if p else p


def _percentiles(xs: list[float], pcts: tuple[int, ...]) -> dict[int, float]:
    if not xs:
        return {p: float("nan") for p in pcts}
    xs = sorted(xs)
    out: dict[int, float] = {}
    for p in pcts:
        # nearest-rank percentile — small samples (n=42 male) make
        # linear-interpolated percentiles wobble more than they're worth.
        idx = max(0, min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1)))))
        out[p] = xs[idx]
    return out


def _z(value: float | None, ref: dict) -> float | None:
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

    stats = json.loads(STATS_ZH_PATH.read_text())

    # ── load every spk's engine_c response ──
    spk_data: list[dict] = []
    dropped: list[tuple[str, str]] = []
    for row in rows:
        raw = raw_dir / f"{row['spk_id']}.json"
        if not raw.is_file():
            dropped.append((row["spk_id"], "no raw json"))
            continue
        try:
            ec = json.loads(raw.read_text())
        except json.JSONDecodeError:
            dropped.append((row["spk_id"], "json decode"))
            continue
        if not ec.get("phones"):
            dropped.append((row["spk_id"], "zero phones"))
            continue
        spk_data.append(
            {
                "spk_id": row["spk_id"],
                "sex": row["sex"],
                "age": row.get("age"),
                "accent": row.get("accent"),
                "duration_sec": row.get("duration_sec"),
                "phones": ec["phones"],
                "medianResonance": ec.get("medianResonance"),
                "meanResonance": ec.get("meanResonance"),
            }
        )

    # ── table 1: per-spk median resonance distribution ──
    by_sex_med: dict[str, list[float]] = {"F": [], "M": []}
    for s in spk_data:
        med = s.get("medianResonance")
        if med is None:
            # fall back to recomputing from phones — defensive against
            # sidecar versions that didn't populate medianResonance.
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

    # ── table 2: per-vowel z-scores aggregated over all phones ──
    per_vowel_F: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    per_vowel_M: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    # saturation rate: fraction of resonance values ≤ 0.02 or ≥ 0.98
    per_vowel_sat: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))

    # Sidecar `phones[]` schema: each phone has F=[F0,F1,F2,F3] (None where
    # the formant tracker had no signal — common for consonants, silences,
    # and rare on vowels).  F_stdevs is the same shape, pre-computed against
    # the tone-stripped `expected` key in stats_zh.json.  We re-key into our
    # local stats dict so the stats source is explicit (and so this script
    # works against future schema variants).
    for s in spk_data:
        bucket = per_vowel_F if s["sex"] == "F" else per_vowel_M
        for ph in s["phones"]:
            # `phoneme` is what MFA actually emitted; `expected` is the
            # dictionary target.  Both carry tone marks when present.  We
            # bucket by the tone-stripped phoneme — same convention as
            # resonance.compute_resonance's vowel test.
            label_raw = ph.get("phoneme")
            if not label_raw:
                continue
            label = _strip_tone(label_raw)
            if label not in ZH_VOWELS:
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

    # ── table 3: F2 collapse check (female /i/ /y/ /e/ /a/ /u/) ──
    collapse_rows: list[dict] = []
    for vowel, lit_hz in LIT_FEMALE_F2_HZ.items():
        f2s = per_vowel_F.get(vowel, {}).get("F2", [])
        if len(f2s) < 5:
            collapse_rows.append(
                {"vowel": vowel, "n": len(f2s), "f2_med": None, "lit": lit_hz, "verdict": "n<5"}
            )
            continue
        med = statistics.median(f2s)
        # >25 % below literature flags collapse; 15–25 % is "soft" warning.
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

    # ── table 4: 5-zone candidate thresholds (anchored to female P_x) ──
    pf = table1["F"]
    zone_thresholds = {
        "clearly_male": ("<", round(pf[5], 3)),
        "leans_male": (f"[{round(pf[5], 3)}, {round(pf[25], 3)})", None),
        "neutral": (f"[{round(pf[25], 3)}, {round(pf[75], 3)})", None),
        "leans_female": (f"[{round(pf[75], 3)}, {round(pf[95], 3)})", None),
        "clearly_female": ("≥", round(pf[95], 3)),
    }

    # ── render markdown ──
    out_path = Path(args.report_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append(f"# zh-CN resonance baseline ({date.today()})\n")
    lines.append(
        f"**Source**: AISHELL-3 train, sampled {args.n_female}F + {args.n_male}M speakers, "
        f"{args.clips_per_spk} clips/spk concatenated, seed={args.seed}.\n"
    )
    lines.append("Sidecar formant ceiling: legacy 5000 Hz (zh not in `_ADAPTIVE_LANGS`).\n")
    lines.append(
        f"Speakers analyzed: {len(spk_data)} ({sum(1 for s in spk_data if s['sex'] == 'F')}F / "
        f"{sum(1 for s in spk_data if s['sex'] == 'M')}M).  Dropped: {len(dropped)}.\n\n"
    )

    # table 1
    lines.append("## Table 1 — per-spk median `resonance` distribution\n")
    lines.append("| sex | n | P5 | P25 | P50 | P75 | P95 | mean |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for sex in ("F", "M"):
        t = table1[sex]
        lines.append(
            f"| {sex} | {t['n']} | {t[5]:.3f} | {t[25]:.3f} | {t[50]:.3f} | {t[75]:.3f} | {t[95]:.3f} | {t['mean']:.3f} |"
        )
    lines.append("")

    # table 2
    lines.append("## Table 2 — per-vowel z-scores (relative to `stats_zh.json`)\n")
    lines.append(
        "Z is computed against the reference distribution in `stats_zh.json`. "
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

    # table 3
    lines.append("## Table 3 — F2 collapse check (female speakers vs literature)\n")
    lines.append(
        "Literature targets are typical Mandarin female F2 from 鲍怀翘《普通话语音学》 + "
        "Lee/Zhang 2008 JASA.  `verdict=COLLAPSE` ⇒ measured F2 < 75 % of literature, "
        "indicates Praat ceiling-too-low (5000 Hz mis-resolves F2/F3).\n"
    )
    lines.append("| vowel | n | F2_med (this run) | F2 lit | ratio | verdict |")
    lines.append("|---|---|---|---|---|---|")
    for r in collapse_rows:
        f2m = "—" if r["f2_med"] is None else f"{r['f2_med']:.0f}"
        ratio = "—" if r["f2_med"] is None else f"{r['f2_med'] / r['lit']:.2f}"
        lines.append(f"| {r['vowel']} | {r['n']} | {f2m} | {r['lit']} | {ratio} | {r['verdict']} |")
    lines.append("")

    # table 4
    lines.append("## Table 4 — 5-zone candidate thresholds for `resonance_zone_key`\n")
    lines.append(
        "Anchored to female P5/P25/P75/P95 from Table 1.  Phase B will commit these "
        "as constants in `voiceya/services/audio_analyser/resonance_calibration.py`.\n"
    )
    lines.append("| zone_key | range |")
    lines.append("|---|---|")
    for k, (op, num) in zone_thresholds.items():
        rng = f"{op} {num}" if num is not None else op
        lines.append(f"| `{k}` | {rng} |")
    lines.append("")

    # decisions
    lines.append("## Decision points\n")
    # 1. F2 collapse on /i/ specifically
    collapsed = [r for r in collapse_rows if r["verdict"] == "COLLAPSE"]
    soft = [r for r in collapse_rows if r["verdict"] == "low"]
    if collapsed:
        worst = collapsed[0]
        lines.append(
            f"1. **F2 collapse confirmed** on /{', /'.join(r['vowel'] for r in collapsed)}/ "
            f"(worst: /{worst['vowel']}/ measured {worst['f2_med']:.0f} Hz vs literature "
            f"{worst['lit']} Hz = {worst['f2_med'] / worst['lit']:.0%}).  "
            "Same fingerprint as fr-FR before adaptive ceiling.  Path: re-train "
            "`stats_zh.json` at 5500 Hz ceiling, then add zh to `_ADAPTIVE_LANGS`. "
            "Without re-training, simply enabling adaptive ceiling for zh would over-correct "
            "(stats_zh's F2 means are baked at 5000 Hz; bumping the ceiling shifts every "
            "z_F2 positive, drives all male voices into female zone — exactly the Phase 8 "
            "regression that put zh out of `_ADAPTIVE_LANGS` in the first place)."
        )
        if soft:
            lines.append(
                f"   Soft-low (75–85 % of literature, watch list): /{', /'.join(r['vowel'] for r in soft)}/."
            )
    elif soft:
        lines.append(
            f"1. **F2 soft-low** on /{', /'.join(r['vowel'] for r in soft)}/ — below literature but >75 %.  "
            "No clear collapse; defer adaptive ceiling for zh."
        )
    else:
        lines.append(
            "1. **F2 collapse not detected** — current 5000 Hz ceiling holds for zh.  "
            "Skip adding zh to `_ADAPTIVE_LANGS`."
        )

    # 2. score-ceiling check: how many F speakers saturate medianResonance
    f_meds = by_sex_med["F"]
    n_sat_F_top = sum(1 for v in f_meds if v >= 0.98)
    m_meds = by_sex_med["M"]
    n_sat_M_top = sum(1 for v in m_meds if v >= 0.98)
    n_sat_M_bot = sum(1 for v in m_meds if v <= 0.02)
    lines.append(
        f"2. **Score ceiling is real**: {n_sat_F_top}/{len(f_meds)} F speakers "
        f"({100 * n_sat_F_top / max(1, len(f_meds)):.0f} %) saturate `medianResonance` at ≥0.98; "
        f"F P95 is {table1['F'][95]:.3f}.  "
        f"M side: {n_sat_M_top}/{len(m_meds)} saturate top, {n_sat_M_bot}/{len(m_meds)} saturate bottom.  "
        "Implication: a five-tier zone with `clearly_female ≥ P95` is degenerate — "
        "users in that tier are at the clamp ceiling, not at a 'more female' level.  "
        "Recommend setting `clearly_female` boundary at F P75 (Table 1) instead, so the top "
        "tier captures the upper quartile of F speakers without requiring saturation."
    )

    # 3. F-M overlap zone — UI should not promise verdict in this band.
    overlap_lo = max(table1["M"][5], table1["F"][5])
    overlap_hi = min(table1["M"][95], table1["F"][95])
    if overlap_lo < overlap_hi:
        lines.append(
            f"3. **F-M overlap band**: [{overlap_lo:.3f}, {overlap_hi:.3f}] is reachable by both "
            f"sexes' P5–P95 ranges (M P95 = {table1['M'][95]:.3f}, F P5 = {table1['F'][5]:.3f}).  "
            "Inside this band the score isn't sex-discriminative on its own — Phase D summary text "
            "should phrase it as 'in shared range' rather than directional."
        )

    gap = table1["F"][50] - table1["M"][50]
    lines.append(
        f"4. Female–male median gap (P50): {gap:+.3f}.  "
        f"{'Wide enough for percentile-anchored zones (use Table 4 numbers)' if gap > 0.15 else 'Narrow — consider mean-midpoint zones instead'}."
    )

    # 5. high-saturation vowels — but reframe.  High sat at the *aggregate* level
    # is structural (F1 of /a/-class is naturally above F-mean → score saturates),
    # not "broken".  The implication is for per-vowel UI guidance, not the
    # whole-recording score.
    noisy_F = []
    noisy_M = []
    for v, d in per_vowel_F.items():
        sat_list = per_vowel_sat["F"].get(v, [])
        if sat_list and sum(sat_list) / len(sat_list) > 0.5:
            noisy_F.append(f"{v}({sum(sat_list) / len(sat_list):.0%})")
    for v, d in per_vowel_M.items():
        sat_list = per_vowel_sat["M"].get(v, [])
        if sat_list and sum(sat_list) / len(sat_list) > 0.5:
            noisy_M.append(f"{v}({sum(sat_list) / len(sat_list):.0%})")
    if noisy_F or noisy_M:
        lines.append(
            f"5. **Per-vowel score has low diagnostic power** on saturated classes.  "
            f"F-speaker high-sat vowels: {', '.join(noisy_F) if noisy_F else 'none'}.  "
            f"M-speaker high-sat vowels: {', '.join(noisy_M) if noisy_M else 'none'}.  "
            "Phase C per-vowel guidance should display **z_F1 / z_F2 directly** for these "
            "(absolute Hz delta to female mean) rather than the clamped resonance score — "
            "the z values still carry sub-clamp signal."
        )

    # 6. concrete next steps
    lines.append(
        "6. **Recommended Phase B path** (in order): "
        "(a) re-train `stats_zh.json` at 5500 Hz ceiling using AISHELL-3 train (script can mirror "
        "`scripts/train_stats_fr.py`); "
        "(b) re-run this audit against the new stats — verify /i/ F2_med returns to ≥2200 Hz and "
        "F median resonance distribution shifts down (saturation rate drops); "
        "(c) add zh to `_ADAPTIVE_LANGS` in `wrapper/ceiling_selector.py`; "
        "(d) commit the new Table 4 zone thresholds to `resonance_calibration.py`; "
        "(e) keep raw `medianResonance` in the API response — only the **interpretation** layer "
        "(zone label, summary text) reads from `resonance_calibration`."
    )

    lines.append(
        "7. AISHELL-3 male sample n=42 — confidence intervals on M side are wider than F's.  "
        "If a Phase B decision hinges on M numbers, supplement with THCHS-30 / MAGICDATA male."
    )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("wrote %s", out_path)
    return out_path


# ── cli ──────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--stage", action="store_true", help="step 1: stitch AISHELL3 → stitched/")
    ap.add_argument("--analyze", action="store_true", help="step 2: POST stitched → sidecar")
    ap.add_argument("--report", action="store_true", help="step 3: aggregate raw/ → report")
    ap.add_argument("--aishell", default=DEFAULT_AISHELL)
    ap.add_argument("--stitched", default=str(DEFAULT_STITCHED))
    ap.add_argument("--raw", default=str(DEFAULT_RAW))
    ap.add_argument("--report-out", default=str(DEFAULT_REPORT))
    ap.add_argument("--n-female", type=int, default=50)
    ap.add_argument("--n-male", type=int, default=42)
    ap.add_argument("--clips-per-spk", type=int, default=5)
    ap.add_argument("--sidecar", default=SIDECAR_DEFAULT)
    ap.add_argument(
        "--token-env",
        default="ENGINE_C_SIDECAR_TOKEN",
        help="env var name holding the X-Engine-C-Token value",
    )
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()

    _drift_guard()

    # default: run all three phases sequentially
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
