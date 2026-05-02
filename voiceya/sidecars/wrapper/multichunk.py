"""Multi-chunk MFA pipeline for parallel alignment (Engine C).

Given a chunk plan from ``chunker.plan_chunks`` + the raw audio bytes,
this module:

  1. Decodes the source audio to 16 kHz mono WAV via ffmpeg.
  2. Slices per-chunk WAVs and writes per-chunk transcripts into an MFA
     corpus laid out as ``tmp_dir/corpus/spk/chunk_NNN.{wav,txt}`` — one
     speaker folder so MFA can share speaker-adapted features across
     chunks of the same clip.
  3. Invokes MFA ``align`` **once** with ``--num_jobs N`` so feature
     extraction + Viterbi run in parallel inside the MFA process, instead
     of paying MFA's startup cost N times.
  4. Runs Praat formant extraction per chunk (the vendored Praat script
     is per-recording) and collects the TSVs.
  5. Parses each TSV via ``phones.parse``, offsets times by each chunk's
     start-in-original-audio, re-maps ``word_index`` across chunks, and
     returns a single merged ``data`` dict.

The returned dict matches ``phones.parse``'s shape so the caller can
pass it straight to ``resonance.compute_resonance`` — outlier removal +
z-score statistics are computed on the merged phone list, preserving
the single-block semantics.

This module doesn't touch the vendored ``preprocessing.py``
(CLAUDE.md §2).  The MFA command construction mirrors the vendored
sequence but lives here so the multi-chunk knobs (``--num_jobs``, the
corpus layout) don't require patching upstream.
"""

from __future__ import annotations

import glob
import logging
import os
import subprocess
import sys
import wave
from collections import Counter

import acousticgender.library.phones as phones

# Production: uvicorn loads us as ``wrapper.multichunk`` so the relative form
# resolves.  Tests import this module directly with ``wrapper/`` on sys.path
# (mirroring the ``acousticgender.*`` absolute-import style above), so the
# fallback covers that too.  Both branches bind the same ``ceiling_selector``
# name; the fallback is exercised by tests/test_multichunk_*.py.
try:
    from . import ceiling_selector
except ImportError:
    import ceiling_selector  # noqa: F401

logger = logging.getLogger("engine_c.multichunk")


# ── Audio decode + slice ─────────────────────────────────────────────


def decode_to_wav(audio_bytes: bytes, dst_wav: str, ffmpeg: str) -> float:
    """Decode arbitrary audio bytes to 16 kHz mono pcm_s16le WAV.

    Returns duration in seconds, read back from the decoded file so we
    don't trust container-level duration metadata from the input.
    """
    src = dst_wav + ".src"
    try:
        with open(src, "wb") as f:
            f.write(audio_bytes)
        subprocess.check_output(
            [ffmpeg, "-y", "-i", src, "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000", dst_wav],
            stderr=subprocess.STDOUT,
        )
    finally:
        if os.path.exists(src):
            os.unlink(src)

    with wave.open(dst_wav, "rb") as w:
        return w.getnframes() / float(w.getframerate())


def slice_chunks(
    src_wav: str,
    chunks: list[dict],
    corpus_root: str,
    ffmpeg: str,
) -> list[tuple[dict, str]]:
    """ffmpeg -ss/-t slice the decoded WAV into per-chunk WAV files.

    Layout: ``corpus_root/spk_{NNN}/chunk_{NNN}.{wav,txt}`` — **one speaker
    folder per chunk**.  MFA's ``--num_jobs N`` parallelises across
    speakers, not across files within a speaker (observed via its own
    warning: "Number of jobs was specified as N, but due to only having
    1 speakers, ..." when we grouped all chunks under one speaker).  The
    tradeoff is losing cross-chunk speaker adaptation, but each chunk is
    still >= MIN_CHUNK_SEC (default 3 s), which is enough for MFA's
    per-speaker GMM adaptation to behave reasonably.

    Returns [(chunk_dict, wav_path)] in chunk order.
    """
    os.makedirs(corpus_root, exist_ok=True)
    out: list[tuple[dict, str]] = []
    for c in chunks:
        stem = f"chunk_{c['index']:03d}"
        spk_dir = os.path.join(corpus_root, f"spk_{c['index']:03d}")
        os.makedirs(spk_dir, exist_ok=True)
        wav_path = os.path.join(spk_dir, stem + ".wav")
        txt_path = os.path.join(spk_dir, stem + ".txt")
        dur = c["end_sec"] - c["start_sec"]
        # -ss BEFORE -i seeks the container (fast); -t bounds the output.
        # Re-encode to the same pcm_s16le 16k mono so MFA doesn't complain
        # about format drift across chunks.
        subprocess.check_output(
            [
                ffmpeg,
                "-y",
                "-ss",
                f"{c['start_sec']:.3f}",
                "-t",
                f"{dur:.3f}",
                "-i",
                src_wav,
                "-acodec",
                "pcm_s16le",
                "-ac",
                "1",
                "-ar",
                "16000",
                wav_path,
            ],
            stderr=subprocess.STDOUT,
        )
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(c["transcript"])
        out.append((c, wav_path))
    return out


# ── MFA invocation ───────────────────────────────────────────────────


def build_mfa_cmd(settings_dict: dict) -> tuple[list[str], dict]:
    """Construct the platform-appropriate ``mfa`` invocation prefix + env.

    Mirrors voiceya/sidecars/visualizer-backend/acousticgender/library/
    preprocessing.py:87-111.  Kept here so we don't import the vendored
    module just for its cmd-building side effects.
    """
    scripts_dir = os.path.dirname(settings_dict["mfa"])
    env_dir = os.path.dirname(scripts_dir)
    env = os.environ.copy()

    if sys.platform == "win32":
        mfa_python = os.path.join(env_dir, "python.exe")
        mfa_script = os.path.join(scripts_dir, "mfa-script.py")
        cmd = [mfa_python, mfa_script]
        path_additions = os.pathsep.join(
            [
                os.path.join(env_dir, "Library", "bin"),
                os.path.join(env_dir, "Library", "mingw-w64", "bin"),
                os.path.join(env_dir, "Library", "usr", "bin"),
                os.path.join(env_dir, "Scripts"),
                env_dir,
            ]
        )
        env["PATH"] = path_additions + os.pathsep + env.get("PATH", "")
    else:
        cmd = [settings_dict["mfa"]]
        env["PATH"] = scripts_dir + os.pathsep + env.get("PATH", "")

    env["CONDA_PREFIX"] = env_dir
    return cmd, env


def run_mfa(
    tmp_dir: str,
    lang: str,
    num_jobs: int,
    mfa_cmd: list[str],
    mfa_env: dict,
    *,
    beam: str = "",
    retry_beam: str = "",
) -> None:
    """Run ``mfa align`` on the corpus under ``tmp_dir``.

    Changes cwd to ``tmp_dir`` because MFA's argv uses ``./corpus/`` and
    ``./output/`` — matches the vendored convention.  Caller is responsible
    for restoring cwd in a finally.

    ``lang``: "zh" → mandarin_mfa acoustic + mandarin_china_mfa dict.
    "en" → english_us_arpa for both (NOT english_mfa — that one emits IPA,
    incompatible with the ARPABET stats.json/cmudict.txt this sidecar
    ships; same mapping the wrapper's fast-mode shim applies for the
    single-block path).  "fr" → french_mfa for both (acoustic + dict
    share the registry name, IPA phoneset).  See visualizer-backend.Dockerfile
    for why zh's acoustic and dict names diverge — pairing the legacy
    mandarin_mfa dict with the v3 acoustic model leaves common hanzi as
    ``<unk>``.
    """
    if lang == "zh":
        mfa_acoustic, mfa_dict = "mandarin_mfa", "mandarin_china_mfa"
    elif lang == "fr":
        mfa_acoustic = mfa_dict = "french_mfa"
    else:
        mfa_acoustic = mfa_dict = "english_us_arpa"
    args = mfa_cmd + [
        "align",
        "./corpus/",
        mfa_dict,
        mfa_acoustic,
        "./output/",
        "--clean",
        "--num_jobs",
        str(num_jobs),
    ]
    if beam:
        args += ["--beam", beam]
    if retry_beam:
        args += ["--retry_beam", retry_beam]
    if os.environ.get("ENGINE_C_MFA_SINGLE_SPEAKER", "0").lower() in ("1", "true", "yes", "on"):
        # MFA's warning mentions --single_speaker as the way to split
        # utterances across jobs regardless of their speaker folder.  Also
        # skips fMLLR speaker adaptation (a sizable chunk of total MFA
        # wall time on short clips).  Off by default so we can A/B it.
        args.append("--single_speaker")

    cwd = os.getcwd()
    os.chdir(tmp_dir)
    try:
        logger.info("multichunk MFA cmd: %s", args)
        out = subprocess.check_output(args, stderr=subprocess.STDOUT, env=mfa_env)
        decoded = out.decode("utf-8", errors="replace")
        # Surface a tiny subset of MFA's stdout so we can still verify
        # parallelism took effect without flooding the container log.
        for line in decoded.splitlines():
            s = line.strip()
            if (
                ("Found" in s and "speaker" in s)
                or "Everything took" in s
                or ("WARNING" in s and "Number of jobs" in s)
            ):
                logger.info("MFA: %s", s.replace("INFO", "", 1).strip()[:180])
    except subprocess.CalledProcessError as e:
        tail = e.output.decode("utf-8", errors="replace")[-800:]
        raise RuntimeError(f"multichunk MFA align failed: {tail}") from e
    finally:
        os.chdir(cwd)


# ── Praat per-chunk ──────────────────────────────────────────────────


def run_praat_per_chunk(
    tmp_dir: str,
    chunks: list[dict],
    praat_bin: str,
    praat_script_path: str,
) -> dict[int, str]:
    """Run the vendored textgrid-formants.praat script once per chunk.

    Returns ``{chunk_index: praat_tsv_text}``.  A chunk that's missing its
    TextGrid (MFA failed to align that chunk in isolation) gets an empty
    TSV — ``phones.parse`` on an empty TSV returns zero phones which the
    merge step surfaces as a fallback signal.
    """
    # MFA mirrors the input corpus tree in the output dir:
    #   corpus/spk_NNN/chunk_NNN.wav → output/spk_NNN/chunk_NNN.TextGrid
    results: dict[int, str] = {}

    for c in chunks:
        stem = f"chunk_{c['index']:03d}"
        spk = f"spk_{c['index']:03d}"
        wav = os.path.join(tmp_dir, "corpus", spk, stem + ".wav")
        grid = os.path.join(tmp_dir, "output", spk, stem + ".TextGrid")
        if not os.path.exists(grid):
            logger.warning("multichunk: missing TextGrid for %s", stem)
            results[c["index"]] = ""
            continue
        try:
            out = subprocess.check_output(
                [praat_bin, "--run", praat_script_path, wav, grid],
                stderr=subprocess.STDOUT,
            ).decode("utf-8")
            # kalpy's TextGrid labels silence intervals "<eps>"; MFA CLI
            # writes "" (empty).  phones.parse would otherwise surface
            # "<eps>" as a spoken word in the downstream response.  Match
            # MFA's convention by stripping the placeholder; the Praat
            # script already prints the label verbatim so this is the
            # cheapest fix point.
            out = out.replace("\t<eps>", "\t")
            results[c["index"]] = out
        except subprocess.CalledProcessError as e:
            logger.warning(
                "multichunk: praat failed on %s: %s",
                stem,
                e.output.decode("utf-8", errors="replace")[-400:],
            )
            results[c["index"]] = ""
    return results


# ── Parse + merge ────────────────────────────────────────────────────


def merge_parses(
    chunks: list[dict],
    praat_tsvs: dict[int, str],
    lang: str,
) -> dict:
    """Parse each chunk's TSV, shift times, remap word_index, concat.

    The output matches ``phones.parse``'s shape:
        {"words": [{time, word, expected}],
         "phones": [{time, phoneme, word_index, word, word_time, expected, F}]}

    All ``time`` / ``word_time`` fields are rewritten to be absolute in the
    original (pre-chunk) audio timeline.  ``word_index`` is re-mapped so
    each phone still points at its owning word in the merged ``words``
    list.  Caller must run ``resonance.compute_resonance`` on the result —
    we deliberately skip it here so compute_resonance sees the full phone
    list and its global statistics stay equivalent to the single-block path.

    Returns ``None`` if any chunk parses to zero phones (MFA couldn't align
    that chunk) — caller falls back to single-block.
    """
    merged_words: list[dict] = []
    merged_phones: list[dict] = []

    for c in sorted(chunks, key=lambda x: x["index"]):
        tsv = praat_tsvs.get(c["index"], "")
        if not tsv:
            logger.warning("multichunk: empty TSV for chunk %d", c["index"])
            return None
        parsed = phones.parse(tsv, lang)
        if not parsed.get("phones"):
            logger.warning(
                "multichunk: chunk %d parsed to zero phones (tsv len=%d)",
                c["index"],
                len(tsv),
            )
            return None

        offset = float(c["start_sec"])
        word_idx_shift = len(merged_words)

        for w in parsed["words"]:
            merged_words.append(
                {
                    "time": float(w["time"]) + offset,
                    "word": w["word"],
                    "expected": w["expected"],
                }
            )

        for p in parsed["phones"]:
            merged_phones.append(
                {
                    "time": (float(p["time"]) + offset) if p.get("time") is not None else None,
                    "phoneme": p["phoneme"],
                    "word_index": p["word_index"] + word_idx_shift,
                    "word": p["word"],  # reference — compute_resonance doesn't use this
                    "word_time": (float(p["word_time"]) + offset)
                    if p.get("word_time") is not None
                    else None,
                    "expected": p["expected"],
                    "F": list(p["F"]) if p.get("F") is not None else [None, None, None, None],
                }
            )

    return {"words": merged_words, "phones": merged_phones}


# ── Orchestration ────────────────────────────────────────────────────


def process_from_wav(
    full_wav: str,
    chunks: list[dict],
    tmp_dir: str,
    lang: str,
    settings_dict: dict,
    praat_script_path: str,
    *,
    mfa_beam: str = "",
    mfa_retry_beam: str = "",
    preloaded_aligner=None,
) -> dict | None:
    """Multi-chunk pipeline starting from an already-decoded 16 kHz mono WAV.

    Caller is responsible for:
      - Producing ``full_wav`` (see ``decode_to_wav``) so the wrapper can
        reuse whatever it already needed for duration-probing + chunk
        planning, without re-decoding.
      - Creating ``tmp_dir`` and cleaning it up in a finally.
      - Passing ``praat_script_path`` — textgrid-formants.praat lives in
        the sidecar's WORKDIR, and this module doesn't assume cwd.

    If ``preloaded_aligner`` is provided, per-chunk alignment runs through
    kalpy (no MFA CLI subprocess, no per-request acoustic-model reload —
    the 27 s startup tax is amortised away).  Falls back to subprocess
    MFA with ``--num_jobs N`` when the aligner is ``None``.
    """
    corpus_root = os.path.join(tmp_dir, "corpus")
    slice_chunks(full_wav, chunks, corpus_root, settings_dict["ffmpeg"])
    os.makedirs(os.path.join(tmp_dir, "output"), exist_ok=True)

    if preloaded_aligner is not None:
        _align_with_kalpy(tmp_dir, chunks, preloaded_aligner)
    else:
        mfa_cmd, mfa_env = build_mfa_cmd(settings_dict)
        num_jobs = min(len(chunks), os.cpu_count() or 1)
        run_mfa(
            tmp_dir,
            lang,
            num_jobs,
            mfa_cmd,
            mfa_env,
            beam=mfa_beam,
            retry_beam=mfa_retry_beam,
        )

    # Confirm alignment produced something before Praat — fast-fail with
    # a clearer message than "empty TSV" further down.  Glob across all
    # spk_NNN/ output subdirs (one per chunk).
    grids = glob.glob(os.path.join(tmp_dir, "output", "spk_*", "*.TextGrid"))
    if len(grids) == 0:
        logger.warning("multichunk: alignment produced 0 TextGrids")
        return None

    praat_tsvs = run_praat_per_chunk(
        tmp_dir,
        chunks,
        settings_dict["praat"],
        praat_script_path,
    )

    rewritten_tsvs, recording_ceiling = _apply_ceiling_selector(praat_tsvs, lang)
    merged = merge_parses(chunks, rewritten_tsvs, lang)
    if merged is not None and recording_ceiling is not None:
        merged["formant_ceiling_hz"] = recording_ceiling
    return merged


# voiceya patch (2026-05-01): per-chunk adaptive formant ceiling.  Each
# chunk's Praat TSV carries a Multi-Ceiling-Formants section (5 candidate
# ceilings × 3 formants per phone).  Pick the per-chunk optimum and rewrite
# the Phonemes section so merge_parses + phones.parse see only the chosen
# ceiling's formants.  Extracted from process_from_wav so it can be unit-
# tested without spinning up ffmpeg / MFA / Praat.
def _apply_ceiling_selector(
    praat_tsvs: dict[int, str],
    lang: str,
) -> tuple[dict[int, str], int | None]:
    """Pick per-chunk optimal ceiling, rewrite each chunk's Phonemes section.

    Returns ``(rewritten_tsvs, recording_level_ceiling_hz | None)``.  The
    recording-level ceiling is the most-common pick across chunks (typical
    5–60 s clips rarely span enough vocal-tract change for chunks to
    disagree); ``None`` only when ``praat_tsvs`` is empty.
    """
    chosen_ceilings: dict[int, int] = {}
    rewritten_tsvs: dict[int, str] = {}
    for idx, tsv in praat_tsvs.items():
        ceiling_hz, rewritten = ceiling_selector.pick_best(tsv, lang)
        chosen_ceilings[idx] = ceiling_hz
        rewritten_tsvs[idx] = rewritten
    if not chosen_ceilings:
        return rewritten_tsvs, None
    return rewritten_tsvs, Counter(chosen_ceilings.values()).most_common(1)[0][0]


def _align_with_kalpy(
    tmp_dir: str,
    chunks: list[dict],
    aligner,  # PreloadedAligner
) -> None:
    """Align each chunk via the preloaded kalpy aligner.

    Writes ``output/spk_NNN/chunk_NNN.TextGrid`` for each chunk, mirroring
    the directory layout MFA CLI would have produced so downstream
    ``run_praat_per_chunk`` doesn't need to branch.

    Any per-chunk alignment failure is logged and re-raised so the
    caller can surface it as a multichunk-path failure and fall back to
    the single-block path.  (Partial chunk results aren't safe — the
    merge step would see an empty TextGrid and bail anyway.)
    """
    import time  # noqa: PLC0415 — only needed inside the kalpy path
    from pathlib import Path  # noqa: PLC0415

    t0 = time.perf_counter()
    for c in chunks:
        stem = f"chunk_{c['index']:03d}"
        spk = f"spk_{c['index']:03d}"
        wav = Path(tmp_dir) / "corpus" / spk / (stem + ".wav")
        grid_dir = Path(tmp_dir) / "output" / spk
        grid_dir.mkdir(parents=True, exist_ok=True)
        grid = grid_dir / (stem + ".TextGrid")
        aligner.align_one(wav, c["transcript"], grid)
    logger.info(
        "kalpy aligned %d chunks in %.2fs",
        len(chunks),
        time.perf_counter() - t0,
    )
