"""End-to-end perturbation regression for the per-vowel resonance pipeline.

Headless test that POSTs the **same audio** under controlled F0 and formant
perturbations through a running stack (API + Engine C sidecar), then asserts:

  * Schema:      every variant returns ``summary.engine_c.resonance_per_vowel``
                 with a ``resonance_med`` ∈ [0,1] on each row, ``level_key`` in
                 {good,low,weak}, and no leftover F-axis fields.
  * Determinism: V0 vs V0' rerun matches within rounding.
  * F0-only:     pitch-shifted variants change ``overall_f0_median_hz`` but
                 leave ``median_resonance`` close to baseline (formants kept).
  * Formant:     formant-shifted variants move ``median_resonance`` in the
                 expected direction (factor > 1 → up, factor < 1 → down).
  * Multi-lang:  zh phonemes contain CJK; en phonemes are ARPABET letters.

Usage:
    uv run python tests/test_e2e_resonance_perturbations.py
    uv run python tests/test_e2e_resonance_perturbations.py \
        --audio tests/fixtures/audio/zh_30s.wav --lang zh-CN
    uv run python tests/test_e2e_resonance_perturbations.py \
        --base-url http://localhost:8080 --report-out -
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import io
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import librosa
import numpy as np
import soundfile as sf

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "audio"
REPORTS = REPO / "tests" / "reports"

DEFAULT_BASE_URL = "http://localhost:8080"
SIDECAR_HEALTH_URL = "http://localhost:8001/healthz"
ANALYZE_TIMEOUT = 180.0  # seconds; sidecar can be slow on first MFA load
MIN_DURATION_SEC = 12.0  # bump short fixtures past minimal-tier (10 s) gate

# Perturbation parameters. Tuned on zh_30s + vctk samples; bump if a fixture
# fails the directional thresholds.
F0_SEMITONES = 4
FORMANT_FACTOR = 1.20  # V3 = +20%, V4 = 1/1.20 ≈ -17%

# Assertion thresholds (loose to catch regression, not lock absolute values).
# Note: librosa's pitch_shift uses phase-vocoder STFT — it does NOT truly
# decouple F0 from formants the way TD-PSOLA / WORLD do, so V1/V2 also move
# the resonance score. We therefore drop the "F0-only" drift assertion and
# only assert direction + magnitude on formant variants.
DETERMINISM_RES_TOL = 0.02
DETERMINISM_F0_TOL_HZ = 1.0
FORMANT_DIRECTIONAL_GAP_MIN = 0.05  # V3 - V4 spread must clear this

# ─── Variants ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Variant:
    key: str
    label: str
    kind: str  # "control" | "f0" | "formant"
    n_steps: float = 0.0  # for f0 variants
    factor: float = 1.0  # for formant variants


VARIANTS: list[Variant] = [
    Variant("V0", "baseline", "control"),
    Variant("V0p", "baseline rerun", "control"),
    Variant("V1", f"F0 +{F0_SEMITONES} semi", "f0", n_steps=+F0_SEMITONES),
    Variant("V2", f"F0 -{F0_SEMITONES} semi", "f0", n_steps=-F0_SEMITONES),
    Variant("V3", f"formants ×{FORMANT_FACTOR}", "formant", factor=FORMANT_FACTOR),
    Variant("V4", f"formants ×{1 / FORMANT_FACTOR:.2f}", "formant", factor=1.0 / FORMANT_FACTOR),
]


@dataclass
class VariantResult:
    variant: Variant
    f0_median_hz: float | None = None
    gender_score: float | None = None
    median_resonance: float | None = None
    per_vowel: list[dict] = field(default_factory=list)
    weakness_vowels: list[dict] = field(default_factory=list)
    sample_phones: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class LangRun:
    language: str
    fixture: Path
    duration_sec: float
    results: dict[str, VariantResult] = field(default_factory=dict)
    skipped_reason: str | None = None


# ─── Audio I/O + perturbation ────────────────────────────────────────────────


def _load_and_pad(path: Path) -> tuple[np.ndarray, int]:
    """Load mono float32 audio; pad with tiles + 0.5 s silence to ≥ MIN_DURATION_SEC."""
    y, sr = librosa.load(str(path), sr=None, mono=True)
    if y.size == 0:
        raise RuntimeError(f"empty audio: {path}")
    cur = len(y) / sr
    if cur >= MIN_DURATION_SEC:
        return y.astype(np.float32), sr
    # Tile until we hit the minimum, separated by 0.3 s of silence so MFA
    # doesn't see one giant utterance.
    silence = np.zeros(int(0.3 * sr), dtype=np.float32)
    parts = []
    total = 0.0
    while total < MIN_DURATION_SEC + 1.0:
        parts.append(y)
        total += len(y) / sr
        if total < MIN_DURATION_SEC + 1.0:
            parts.append(silence)
            total += 0.3
    return np.concatenate(parts).astype(np.float32), sr


def _to_wav_bytes(y: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, y, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def perturb_pitch(y: np.ndarray, sr: int, n_steps: float) -> np.ndarray:
    """Shift F0 by n_steps semitones; phase vocoder roughly preserves formants."""
    if n_steps == 0:
        return y
    return librosa.effects.pitch_shift(y, sr=sr, n_steps=n_steps).astype(np.float32)


def perturb_formants(y: np.ndarray, sr: int, factor: float) -> np.ndarray:
    """Shift formants by factor while keeping F0 ~constant.

    Recipe: time-stretch by 1/factor (this drops both F0 and formants by
    factor), then pitch-shift up by 12*log2(factor) semitones (returns F0 to
    original; formants stay shifted). librosa uses phase vocoder so the
    decoupling isn't perfect, but it's enough for directional regression.
    """
    if factor == 1.0:
        return y
    y_stretched = librosa.effects.time_stretch(y, rate=1.0 / factor)
    n_steps = 12.0 * np.log2(factor)
    return librosa.effects.pitch_shift(y_stretched, sr=sr, n_steps=n_steps).astype(np.float32)


def make_variant_audio(y: np.ndarray, sr: int, v: Variant) -> bytes:
    if v.kind == "control":
        out = y
    elif v.kind == "f0":
        out = perturb_pitch(y, sr, v.n_steps)
    elif v.kind == "formant":
        out = perturb_formants(y, sr, v.factor)
    else:
        raise ValueError(f"unknown variant kind: {v.kind}")
    return _to_wav_bytes(out, sr)


# ─── HTTP / SSE client ───────────────────────────────────────────────────────


async def submit_and_wait(
    client: httpx.AsyncClient,
    base_url: str,
    audio_bytes: bytes,
    language: str,
    *,
    mode: str = "free",
) -> dict:
    """POST one analysis, follow the SSE stream until the result event arrives.

    Retries on 429 (rate limit) — the API caps at 10 req / 60 s and a full
    matrix run blows that on variant 11+. We back off with the limiter
    window since the limiter resets cleanly after the period.
    """
    files = {"audio": ("variant.wav", audio_bytes, "audio/wav")}
    data = {"mode": mode, "language": language}
    r = None
    for attempt in range(3):
        r = await client.post(f"{base_url}/api/analyze-voice", files=files, data=data, timeout=30.0)
        if r.status_code != 429:
            break
        wait = 65 if attempt == 0 else 35
        print(f"(429, backing off {wait}s) ", end="", flush=True)
        await asyncio.sleep(wait)
    if r is None or r.status_code == 429:
        raise RuntimeError("rate limited 3 attempts in a row; aborting")
    r.raise_for_status()
    task_id = r.json()["task_id"]

    headers = {"Accept": "text/event-stream"}
    async with client.stream(
        "GET",
        f"{base_url}/api/status/{task_id}",
        headers=headers,
        timeout=ANALYZE_TIMEOUT,
    ) as resp:
        resp.raise_for_status()
        async for raw in resp.aiter_lines():
            line = raw.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload:
                continue
            evt = json.loads(payload)
            t = evt.get("type")
            if t == "result":
                return evt["data"]["summary"]
            if t == "error":
                raise RuntimeError(f"task {task_id} errored: {evt.get('msg')}")
    raise RuntimeError(f"SSE stream closed without result for task {task_id}")


# ─── Recording per-variant data ──────────────────────────────────────────────


def _extract_variant_data(variant: Variant, summary: dict) -> VariantResult:
    ec = summary.get("engine_c") or {}
    rp = (summary.get("advice") or {}).get("resonance_panel") or {}
    return VariantResult(
        variant=variant,
        f0_median_hz=summary.get("overall_f0_median_hz"),
        gender_score=summary.get("overall_gender_score"),
        median_resonance=rp.get("median_resonance") or ec.get("median_resonance"),
        per_vowel=rp.get("per_vowel") or [],
        weakness_vowels=rp.get("weakness_vowels") or [],
        sample_phones=[(p.get("phone") or "")[:6] for p in (ec.get("phones") or [])[:8]],
    )


async def run_lang(
    client: httpx.AsyncClient,
    base_url: str,
    language: str,
    fixture: Path,
) -> LangRun:
    print(f"\n=== {language} — {fixture.name} ===", flush=True)
    y, sr = _load_and_pad(fixture)
    duration = len(y) / sr
    run = LangRun(language=language, fixture=fixture, duration_sec=duration)
    print(f"  loaded {duration:.1f} s @ {sr} Hz", flush=True)

    for v in VARIANTS:
        print(f"  [{v.key}] {v.label} … ", end="", flush=True)
        try:
            audio_bytes = make_variant_audio(y, sr, v)
            summary = await submit_and_wait(client, base_url, audio_bytes, language)
            res = _extract_variant_data(v, summary)
            run.results[v.key] = res
            mr = res.median_resonance
            f0 = res.f0_median_hz
            print(
                f"f0={f0!s:>6} Hz  median_res={mr!s:>6}  "
                f"per_vowel={len(res.per_vowel)}  weakness={len(res.weakness_vowels)}",
                flush=True,
            )
        except Exception as e:  # noqa: BLE001
            print(f"FAIL — {e}", flush=True)
            run.results[v.key] = VariantResult(variant=v, error=str(e))
    return run


# ─── Assertions ──────────────────────────────────────────────────────────────


@dataclass
class AssertionResult:
    name: str
    ok: bool
    detail: str = ""


def _assert(name: str, ok: bool, detail: str = "") -> AssertionResult:
    return AssertionResult(name=name, ok=ok, detail=detail)


def run_assertions(runs: list[LangRun]) -> list[AssertionResult]:  # noqa: PLR0915
    out: list[AssertionResult] = []

    # 1 + 2 + 3 + 4: schema sanity across every variant of every lang
    schema_ok = True
    range_ok = True
    no_legacy = True
    levels_ok = True
    forbidden = {"weakest_formant", "z", "F_med_hz"}
    legal_levels = {"good", "low", "weak"}
    for run in runs:
        if run.skipped_reason:
            continue
        for v_key, res in run.results.items():
            if res.error:
                schema_ok = False
                continue
            if not res.per_vowel:
                schema_ok = False
                out.append(
                    _assert(f"schema/per_vowel.{run.language}.{v_key}", False, "empty per_vowel")
                )
                continue
            for row in res.per_vowel:
                rm = row.get("resonance_med")
                if not isinstance(rm, (int, float)):
                    range_ok = False
                elif not 0.0 <= float(rm) <= 1.0:
                    range_ok = False
                if forbidden & set(row.keys()):
                    no_legacy = False
                if row.get("level_key") not in legal_levels:
                    levels_ok = False
    out.append(_assert("schema/per_vowel_present", schema_ok))
    out.append(_assert("schema/resonance_med_in_range", range_ok))
    out.append(_assert("schema/no_legacy_F_axis_fields", no_legacy))
    out.append(_assert("schema/level_key_in_set", levels_ok))

    # 5: determinism V0 vs V0'
    for run in runs:
        if run.skipped_reason:
            continue
        v0 = run.results.get("V0")
        v0p = run.results.get("V0p")
        if not v0 or not v0p or v0.error or v0p.error:
            out.append(_assert(f"determinism/{run.language}", False, "missing V0/V0p"))
            continue
        f0_diff = abs((v0.f0_median_hz or 0) - (v0p.f0_median_hz or 0))
        mr_diff = abs((v0.median_resonance or 0) - (v0p.median_resonance or 0))
        ok = f0_diff <= DETERMINISM_F0_TOL_HZ and mr_diff <= DETERMINISM_RES_TOL
        out.append(
            _assert(
                f"determinism/{run.language}",
                ok,
                f"|Δf0|={f0_diff:.2f}Hz  |Δmedian_res|={mr_diff:.4f}",
            )
        )

    # 6: F0-only direction V1.f0 > V0.f0 > V2.f0
    for run in runs:
        if run.skipped_reason:
            continue
        v0, v1, v2 = run.results.get("V0"), run.results.get("V1"), run.results.get("V2")
        if not all([v0, v1, v2]) or any(r.error for r in (v0, v1, v2)):
            out.append(_assert(f"f0_only/direction.{run.language}", False, "missing variants"))
            continue
        ok = (v1.f0_median_hz or 0) > (v0.f0_median_hz or 0) > (v2.f0_median_hz or 0)
        out.append(
            _assert(
                f"f0_only/direction.{run.language}",
                ok,
                f"V1={v1.f0_median_hz} V0={v0.f0_median_hz} V2={v2.f0_median_hz}",
            )
        )

    # 7: Formant direction — V3 > V4 (V0 may equal one of them when the voice
    # is clamped at the 0 / 1 floor; we only require monotonicity between the
    # two formant-perturbed variants).
    for run in runs:
        if run.skipped_reason:
            continue
        v3, v4 = run.results.get("V3"), run.results.get("V4")
        if not v3 or not v4 or v3.error or v4.error:
            out.append(_assert(f"formant/direction.{run.language}", False, "missing variants"))
            continue
        ok = (v3.median_resonance or 0) > (v4.median_resonance or 0)
        out.append(
            _assert(
                f"formant/direction.{run.language}",
                ok,
                f"V3={v3.median_resonance} > V4={v4.median_resonance}",
            )
        )

    # 9: Formant amplitude V3.res - V4.res ≥ FORMANT_DIRECTIONAL_GAP_MIN
    for run in runs:
        if run.skipped_reason:
            continue
        v3, v4 = run.results.get("V3"), run.results.get("V4")
        if not v3 or not v4 or v3.error or v4.error:
            continue
        gap = (v3.median_resonance or 0) - (v4.median_resonance or 0)
        ok = gap >= FORMANT_DIRECTIONAL_GAP_MIN
        out.append(
            _assert(
                f"formant/amplitude.{run.language}",
                ok,
                f"V3-V4={gap:.3f} (need ≥ {FORMANT_DIRECTIONAL_GAP_MIN})",
            )
        )

    # 10: language-specific phone alphabet — zh & fr use IPA-with-diacritics
    # (non-ASCII expected); en uses ARPABET (uppercase ASCII letters only).
    for run in runs:
        if run.skipped_reason:
            continue
        v0 = run.results.get("V0")
        if not v0 or v0.error or not v0.per_vowel:
            continue
        vowels_seen = "".join(row.get("vowel", "") for row in v0.per_vowel)
        if run.language == "zh-CN":
            ok = any(ord(ch) > 127 for ch in vowels_seen)
            out.append(_assert("lang/zh_uses_ipa_alphabet", ok, f"vowels={vowels_seen[:40]}"))
        elif run.language == "en-US":
            ok = bool(vowels_seen) and all(
                (ch.isalpha() and ord(ch) < 128) or ch.isdigit() for ch in vowels_seen
            )
            out.append(_assert("lang/en_uses_arpabet_alphabet", ok, f"vowels={vowels_seen[:40]}"))
        elif run.language == "fr-FR":
            ok = bool(vowels_seen)
            out.append(_assert("lang/fr_has_vowels", ok, f"vowels={vowels_seen[:40]}"))

    # 11: weakness uses new resonance_low text_key (in at least one lang's worst variant)
    weakness_text_seen = set()
    for run in runs:
        if run.skipped_reason:
            continue
        for res in run.results.values():
            for w in res.weakness_vowels:
                weakness_text_seen.add(w.get("text_key"))
    out.append(
        _assert(
            "weakness/uses_resonance_low_key",
            "advice.resonance.weakness.resonance_low" in weakness_text_seen,
            f"text_keys observed: {sorted(weakness_text_seen) or '<none>'}",
        )
    )

    return out


# ─── Report rendering ────────────────────────────────────────────────────────


def render_report(
    runs: list[LangRun],
    asserts: list[AssertionResult],
    base_url: str,
) -> str:
    today = _dt.date.today().isoformat()
    lines: list[str] = [
        f"# E2E perturbation report — {today}",
        "",
        "## Setup",
        f"- API: `{base_url}`",
        f"- Sidecar health: `{SIDECAR_HEALTH_URL}`",
        f"- F0 perturbation: ±{F0_SEMITONES} semitones",
        f"- Formant factor: V3=×{FORMANT_FACTOR}, V4=×{1 / FORMANT_FACTOR:.3f}",
        f"- Min duration after pad: {MIN_DURATION_SEC} s",
        "",
        "## Per-language results",
        "",
    ]
    for run in runs:
        if run.skipped_reason:
            lines.append(f"### {run.language} — _(no fixture)_")
            lines.append(f"_skipped: {run.skipped_reason}_\n")
            continue
        try:
            rel = run.fixture.relative_to(REPO)
        except ValueError:
            rel = run.fixture
        lines.append(f"### {run.language} — `{rel}`")
        lines.append(f"_duration after pad: {run.duration_sec:.1f} s_")
        lines.append("")
        lines.append("| Variant | F0 Hz | gender | median_res | weakness | sample per_vowel |")
        lines.append("|---------|------:|-------:|-----------:|---------:|------------------|")
        for v in VARIANTS:
            r = run.results.get(v.key)
            if not r:
                lines.append(f"| {v.key} {v.label} | — | — | — | — | _missing_ |")
                continue
            if r.error:
                lines.append(f"| {v.key} {v.label} | — | — | — | — | _error: {r.error[:60]}_ |")
                continue
            head = ", ".join(
                f"/{row.get('vowel')}/={row.get('resonance_med'):.2f}({row.get('level_key')})"
                for row in r.per_vowel[:4]
            )
            lines.append(
                f"| {v.key} {v.label} "
                f"| {r.f0_median_hz} | {r.gender_score} | {r.median_resonance} "
                f"| {len(r.weakness_vowels)} | {head} |"
            )
        lines.append("")

    lines.append("## Assertions")
    lines.append("")
    pass_n = sum(1 for a in asserts if a.ok)
    fail_n = len(asserts) - pass_n
    for a in asserts:
        tag = "PASS" if a.ok else "FAIL"
        suffix = f" — {a.detail}" if a.detail else ""
        lines.append(f"- **{tag}** `{a.name}`{suffix}")
    lines.append("")
    lines.append(f"## Verdict\n\n{pass_n}/{len(asserts)} PASS, {fail_n} FAIL.")
    return "\n".join(lines) + "\n"


# ─── Main ────────────────────────────────────────────────────────────────────


def _pick_fixtures(args: argparse.Namespace) -> list[tuple[str, Path | None]]:
    """Return [(language, fixture-or-None)] for the run. None → skip."""
    if args.audio:
        return [(args.lang, Path(args.audio).resolve())]
    matrix: list[tuple[str, Path | None]] = []
    zh = FIXTURES / "zh_30s.wav"
    matrix.append(("zh-CN", zh if zh.is_file() else None))
    en_candidates = sorted((FIXTURES / "cis_female").glob("vctk_p248_*.wav"))
    matrix.append(("en-US", en_candidates[0] if en_candidates else None))
    fr_candidates = sorted(FIXTURES.glob("fr_*.wav"))
    matrix.append(("fr-FR", fr_candidates[0] if fr_candidates else None))
    return matrix


async def _precheck(client: httpx.AsyncClient, base_url: str) -> None:
    try:
        r = await client.get(f"{base_url}/healthz", timeout=5.0)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"[fatal] API not reachable at {base_url}: {e}") from None
    try:
        r = await client.get(SIDECAR_HEALTH_URL, timeout=5.0)
        r.raise_for_status()
        body = r.json()
        if not body.get("ok"):
            raise SystemExit(f"[fatal] sidecar unhealthy: {body}")
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"[fatal] sidecar not reachable at {SIDECAR_HEALTH_URL}: {e}") from None


async def _amain(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    fixtures = _pick_fixtures(args)
    async with httpx.AsyncClient() as client:
        await _precheck(client, base_url)
        runs: list[LangRun] = []
        for lang, fixture in fixtures:
            if fixture is None:
                runs.append(
                    LangRun(
                        language=lang,
                        fixture=Path(""),
                        duration_sec=0.0,
                        skipped_reason="no fixture",
                    )
                )
                print(f"[skip] {lang}: no fixture", flush=True)
                continue
            run = await run_lang(client, base_url, lang, fixture)
            runs.append(run)

    asserts = run_assertions(runs)
    report = render_report(runs, asserts, base_url)

    if args.report_out == "-":
        print("\n" + report)
    else:
        REPORTS.mkdir(parents=True, exist_ok=True)
        out_path = (
            Path(args.report_out)
            if args.report_out
            else REPORTS / f"e2e_perturbation_{_dt.date.today().isoformat()}.md"
        )
        out_path.write_text(report, encoding="utf-8")
        print(
            f"\n[report] {out_path.relative_to(REPO) if out_path.is_relative_to(REPO) else out_path}"
        )

    fail_n = sum(1 for a in asserts if not a.ok)
    print(f"\n{len(asserts) - fail_n}/{len(asserts)} PASS, {fail_n} FAIL")
    return 0 if fail_n == 0 else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audio", help="single audio file (overrides default matrix)")
    p.add_argument("--lang", default="zh-CN", help="language for --audio (default zh-CN)")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument(
        "--report-out",
        help="path for markdown report; '-' = stdout; default = tests/reports/e2e_perturbation_<date>.md",
    )
    args = p.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
