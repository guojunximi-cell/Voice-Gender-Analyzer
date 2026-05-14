"""Aggregate calibration corpus v1 .vga.json bundles into committable summaries.

Reads ``<out>/<lang>/sessions/{F,M}/session_*.vga.json`` (produced by
``build_corpus.py pack``) and emits, under ``--report-out`` (default
``tests/reports/calibration_v1/``):

  * ``aggregate.csv``        — per (lang, sex) bucket: n, p5/25/50/75/95,
                                mean, std, n_at_ceiling (≥0.98), n_low_align
  * ``per_vowel_<lang>_<sex>.csv``  — per-vowel z-scores, F1/F2/F3 medians,
                                resonance_med, n
  * ``histograms.png``       — 6 histograms, one per bucket, of per-session
                                median_resonance.  Falls back to ``.txt``
                                ascii bars if matplotlib not available.
  * ``README.md``            — provenance, sample counts, headline numbers.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("aggregate")

DEFAULT_OUT = Path("/mnt/d/project_vocieduck/calibration_v1")
DEFAULT_REPORT_OUT = (
    Path(__file__).resolve().parent.parent.parent / "tests" / "reports" / "calibration_v1"
)
LANGS = ["zh-CN", "en-US", "fr-FR"]
SEXES = ["F", "M"]
PCTS = (5, 25, 50, 75, 95)


def _percentile(xs: list[float], pct: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * pct / 100
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _load_bundles(out_root: Path) -> dict[tuple[str, str], list[dict]]:
    """Return {(lang, sex): [bundle, ...]}."""
    bundles: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for lang in LANGS:
        sessions_root = out_root / lang / "sessions"
        if not sessions_root.is_dir():
            log.warning("missing %s — run pack first", sessions_root)
            continue
        for sex in SEXES:
            d = sessions_root / sex
            if not d.is_dir():
                continue
            for p in sorted(d.glob("session_*.vga.json")):
                try:
                    bundles[(lang, sex)].append(json.loads(p.read_text(encoding="utf-8")))
                except Exception as exc:
                    log.warning("could not read %s: %s", p.name, exc)
    return bundles


def _aggregate_bucket(bundles: list[dict]) -> dict:
    """Return summary stats over ``median_resonance`` per session."""
    res: list[float] = []
    f0: list[float] = []
    n_at_ceiling = 0
    n_low_align = 0
    for b in bundles:
        ec = b.get("payload", {}).get("sessions", [{}])[0].get("summary", {}).get("engine_c", {})
        m = ec.get("median_resonance")
        if isinstance(m, (int, float)):
            res.append(float(m))
            if m >= 0.98:
                n_at_ceiling += 1
        f = ec.get("median_pitch_hz")
        if isinstance(f, (int, float)):
            f0.append(float(f))
        ac = ec.get("alignment_confidence") or {}
        if ac.get("low_quality"):
            n_low_align += 1
    out: dict = {
        "n": len(bundles),
        "n_with_resonance": len(res),
        "n_at_ceiling": n_at_ceiling,
        "n_low_align": n_low_align,
    }
    for p in PCTS:
        out[f"p{p}"] = _percentile(res, p)
    out["mean"] = statistics.fmean(res) if res else None
    out["std"] = statistics.pstdev(res) if len(res) > 1 else None
    out["f0_p50"] = _percentile(f0, 50)
    return out


def _aggregate_per_vowel(bundles: list[dict]) -> list[dict]:
    """Pool per-vowel rows across sessions, return median over sessions."""
    by_vowel: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for b in bundles:
        ec = b.get("payload", {}).get("sessions", [{}])[0].get("summary", {}).get("engine_c", {})
        for row in ec.get("resonance_per_vowel") or []:
            v = row.get("vowel")
            if not v:
                continue
            for k in (
                "z_F1_med",
                "z_F2_med",
                "z_F3_med",
                "F1_med_hz",
                "F2_med_hz",
                "F3_med_hz",
                "resonance_med",
            ):
                val = row.get(k)
                if isinstance(val, (int, float)):
                    by_vowel[v][k].append(float(val))
            by_vowel[v]["n_per_session"].append(row.get("n") or 0)

    out: list[dict] = []
    for vowel, vals in by_vowel.items():
        n_sessions = len(vals.get("resonance_med") or [])
        if n_sessions == 0:
            continue
        row = {
            "vowel": vowel,
            "n_sessions": n_sessions,
            "n_phones_total": sum(int(x) for x in vals.get("n_per_session") or []),
        }
        for k in (
            "z_F1_med",
            "z_F2_med",
            "z_F3_med",
            "F1_med_hz",
            "F2_med_hz",
            "F3_med_hz",
            "resonance_med",
        ):
            xs = vals.get(k) or []
            row[f"{k}_p50"] = _percentile(xs, 50)
        out.append(row)
    out.sort(key=lambda r: -r["n_phones_total"])
    return out


def _write_aggregate_csv(rows: dict[tuple[str, str], dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = (
        ["bucket", "n", "n_with_resonance"]
        + [f"p{p}" for p in PCTS]
        + [
            "mean",
            "std",
            "f0_p50",
            "n_at_ceiling",
            "n_low_align",
        ]
    )
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for (lang, sex), agg in sorted(rows.items()):
            bucket = f"{lang}_{sex}"
            row = [bucket, agg["n"], agg["n_with_resonance"]]
            for p in PCTS:
                v = agg[f"p{p}"]
                row.append(f"{v:.4f}" if v is not None else "")
            for k in ("mean", "std", "f0_p50"):
                v = agg[k]
                row.append(f"{v:.4f}" if v is not None else "")
            row.extend([agg["n_at_ceiling"], agg["n_low_align"]])
            w.writerow(row)
    log.info("wrote %s", path)


def _write_per_vowel_csv(per_vowel: list[dict], path: Path) -> None:
    if not per_vowel:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "vowel",
        "n_sessions",
        "n_phones_total",
        "resonance_med_p50",
        "z_F1_med_p50",
        "z_F2_med_p50",
        "z_F3_med_p50",
        "F1_med_hz_p50",
        "F2_med_hz_p50",
        "F3_med_hz_p50",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in per_vowel:
            row = [r["vowel"], r["n_sessions"], r["n_phones_total"]]
            for k in (
                "resonance_med",
                "z_F1_med",
                "z_F2_med",
                "z_F3_med",
                "F1_med_hz",
                "F2_med_hz",
                "F3_med_hz",
            ):
                v = r.get(f"{k}_p50")
                row.append(f"{v:.3f}" if v is not None else "")
            w.writerow(row)
    log.info("wrote %s", path)


def _ascii_histogram(xs: list[float], width: int = 40, n_bins: int = 20) -> list[str]:
    """Cheap ascii histogram on [0,1].  Bars scaled to ``width`` chars."""
    if not xs:
        return ["(empty)"]
    bins = [0] * n_bins
    for v in xs:
        idx = max(0, min(n_bins - 1, int(v * n_bins)))
        bins[idx] += 1
    peak = max(bins) or 1
    lines = []
    for i, c in enumerate(bins):
        lo = i / n_bins
        hi = (i + 1) / n_bins
        bar = "█" * int(c / peak * width)
        lines.append(f"  {lo:.2f}-{hi:.2f} | {bar} {c}")
    return lines


def _try_render_histograms(buckets: dict[tuple[str, str], list[float]], path: Path) -> Path:
    """Render PNG via matplotlib; if missing, fall back to .txt ascii bars."""
    try:
        import matplotlib  # noqa: PLC0415

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415

        fig, axes = plt.subplots(3, 2, figsize=(11, 10), sharex=True, sharey=False)
        for (lang, sex), xs in sorted(buckets.items()):
            r = LANGS.index(lang)
            c = SEXES.index(sex)
            ax = axes[r, c]
            if xs:
                ax.hist(xs, bins=20, range=(0, 1), edgecolor="black", alpha=0.78)
                ax.axvline(
                    statistics.median(xs),
                    color="red",
                    linestyle="--",
                    linewidth=1.0,
                    label=f"P50 = {statistics.median(xs):.3f}",
                )
                ax.legend(fontsize=8, loc="upper right")
            ax.set_title(f"{lang} · {sex}  (n={len(xs)})", fontsize=10)
            ax.set_xlim(0, 1)
            ax.grid(True, alpha=0.25)
            if r == 2:
                ax.set_xlabel("median_resonance")
            if c == 0:
                ax.set_ylabel("speakers / sessions")
        fig.suptitle(
            "Calibration corpus v1 — per-session median_resonance distribution", fontsize=12
        )
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        fig.savefig(path, dpi=120)
        plt.close(fig)
        log.info("wrote %s", path)
        return path
    except ImportError:
        txt = path.with_suffix(".txt")
        lines: list[str] = []
        for (lang, sex), xs in sorted(buckets.items()):
            lines.append(f"## {lang} · {sex}  (n={len(xs)})")
            lines.extend(_ascii_histogram(xs))
            lines.append("")
        txt.write_text("\n".join(lines), encoding="utf-8")
        log.info("matplotlib unavailable; wrote ascii fallback %s", txt)
        return txt


def _write_readme(
    rows: dict[tuple[str, str], dict], hist_path: Path, report_dir: Path, out_root: Path
) -> None:
    lines = [
        "# Calibration corpus v1 — resonance%% empirical distribution",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat()} from `{out_root}`._",
        "",
        "## Provenance",
        "",
        "Sources (speaker-disjoint where applicable from existing stats):",
        "",
        "| Bucket | Source | Notes |",
        "| --- | --- | --- |",
        "| zh-CN F | AISHELL-3 train+test | 175 F speakers available; 1 session per spk |",
        "| zh-CN M | AISHELL-3 train+test | 42 M speakers, multi-session (disjoint clip windows) |",
        "| en-US F | LibriSpeech train-clean-100 | 125 F speakers; 1 session per spk |",
        "| en-US M | LibriSpeech train-clean-100 | 126 M speakers; 1 session per spk |",
        "| fr-FR F | Common Voice fr (validated.tsv, gender=female_feminine) | round-robin per client_id |",
        "| fr-FR M | Common Voice fr (validated.tsv, gender=male_masculine)   | round-robin per client_id |",
        "",
        "Mode = ``script`` (transcripts known) → no ASR error in the chain.",
        "Engine C sidecar @ `localhost:8001`, faithful re-emission of",
        "`summary.engine_c` via ``build_corpus._summarize_engine_c``.",
        "",
        "## Headline (median_resonance, per-session)",
        "",
        "| Bucket | n | P5 | P25 | P50 | P75 | P95 | mean | std | F0 P50 (Hz) |",
        "| --- | ---:| ---:| ---:| ---:| ---:| ---:| ---:| ---:| ---:|",
    ]
    for (lang, sex), agg in sorted(rows.items()):
        cells = [f"{lang} · {sex}", str(agg["n"])]
        for p in PCTS:
            v = agg[f"p{p}"]
            cells.append(f"{v:.3f}" if v is not None else "—")
        for k in ("mean", "std", "f0_p50"):
            v = agg[k]
            if v is None:
                cells.append("—")
            elif k == "f0_p50":
                cells.append(f"{v:.0f}")
            else:
                cells.append(f"{v:.3f}")
        lines.append("| " + " | ".join(cells) + " |")

    lines += [
        "",
        f"![histograms]({hist_path.name})"
        if hist_path.suffix == ".png"
        else f"See `{hist_path.name}` for ascii histograms.",
        "",
        "## Reading guide",
        "",
        "- **Resonance% formula**: `clamp(0, 1, w_F2·z_F2 + w_F3·z_F3 + w_F4·z_F4 + 0.5)`.",
        "  0.5 ≡ female reference distribution mean.  This is **not** the male/female",
        "  midline — male speech routinely sits in the 0.30–0.45 range.",
        "- **`p50` is the bucket median**.  If `zh-CN_M.p50 ≈ 0.40` and `zh-CN_F.p50 ≈ 0.68`,",
        "  then 50% on the meter = ~midway between the two genders, *not* neutral.",
        "- **`n_at_ceiling`** counts sessions whose median saturates at ≥ 0.98 — those",
        "  speakers exceed the meter's headroom and the score is no longer informative",
        "  for them; per-vowel z is the better signal.",
        "- Per-vowel breakdowns: ``per_vowel_<lang>_<sex>.csv``.",
        "",
        "## Use",
        "",
        "Downstream Phase B (re-train stats) and Phase C (advice / How-to-use copy",
        "edits) consume these CSVs.  The raw `.vga.json` bundles live in",
        f"`{out_root}` and are intentionally **not** committed (privacy: speech",
        "carries speaker identity).  Only this report goes into git.",
    ]
    p = report_dir / "README.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("wrote %s", p)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="root with <lang>/sessions/{F,M}/session_*.vga.json",
    )
    ap.add_argument(
        "--report-out",
        type=Path,
        default=DEFAULT_REPORT_OUT,
        help="where to write committable artifacts",
    )
    args = ap.parse_args()

    bundles = _load_bundles(args.out)
    if not bundles:
        log.error("no .vga.json bundles found under %s", args.out)
        return 1

    args.report_out.mkdir(parents=True, exist_ok=True)

    # Aggregate per bucket
    bucket_stats: dict[tuple[str, str], dict] = {}
    bucket_resonances: dict[tuple[str, str], list[float]] = {}
    for key, bs in bundles.items():
        bucket_stats[key] = _aggregate_bucket(bs)
        bucket_resonances[key] = []
        for b in bs:
            ec = (
                b.get("payload", {}).get("sessions", [{}])[0].get("summary", {}).get("engine_c", {})
            )
            m = ec.get("median_resonance")
            if isinstance(m, (int, float)):
                bucket_resonances[key].append(float(m))

    _write_aggregate_csv(bucket_stats, args.report_out / "aggregate.csv")

    # Per-vowel CSVs
    for (lang, sex), bs in bundles.items():
        per_vowel = _aggregate_per_vowel(bs)
        if per_vowel:
            _write_per_vowel_csv(per_vowel, args.report_out / f"per_vowel_{lang}_{sex}.csv")

    # Histograms
    hist_path = _try_render_histograms(bucket_resonances, args.report_out / "histograms.png")

    # README
    _write_readme(bucket_stats, hist_path, args.report_out, args.out)

    log.info("aggregate done — %d buckets", len(bundles))
    return 0


if __name__ == "__main__":
    sys.exit(main())
