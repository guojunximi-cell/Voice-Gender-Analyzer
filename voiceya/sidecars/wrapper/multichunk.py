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

import acousticgender.library.phones as phones

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
            [ffmpeg, "-y", "-i", src,
             "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000",
             dst_wav],
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
    corpus_spk_dir: str,
    ffmpeg: str,
) -> list[tuple[dict, str]]:
    """ffmpeg -ss/-t slice the decoded WAV into per-chunk WAV files.

    Writes ``chunk_{NNN}.wav`` + ``chunk_{NNN}.txt`` under ``corpus_spk_dir``
    (``spk`` = single-speaker folder convention so MFA groups them).
    Returns [(chunk_dict, wav_path)] in chunk order.
    """
    os.makedirs(corpus_spk_dir, exist_ok=True)
    out: list[tuple[dict, str]] = []
    for c in chunks:
        stem = f"chunk_{c['index']:03d}"
        wav_path = os.path.join(corpus_spk_dir, stem + ".wav")
        txt_path = os.path.join(corpus_spk_dir, stem + ".txt")
        dur = c["end_sec"] - c["start_sec"]
        # -ss BEFORE -i seeks the container (fast); -t bounds the output.
        # Re-encode to the same pcm_s16le 16k mono so MFA doesn't complain
        # about format drift across chunks.
        subprocess.check_output(
            [ffmpeg, "-y",
             "-ss", f"{c['start_sec']:.3f}",
             "-t", f"{dur:.3f}",
             "-i", src_wav,
             "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000",
             wav_path],
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
        path_additions = os.pathsep.join([
            os.path.join(env_dir, "Library", "bin"),
            os.path.join(env_dir, "Library", "mingw-w64", "bin"),
            os.path.join(env_dir, "Library", "usr", "bin"),
            os.path.join(env_dir, "Scripts"),
            env_dir,
        ])
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

    ``lang``: "zh" → mandarin_mfa.  "en" → english_us_arpa (NOT
    english_mfa — that one emits IPA, incompatible with the ARPABET
    stats.json/cmudict.txt this sidecar ships; same mapping the wrapper's
    fast-mode shim applies for the single-block path).
    """
    mfa_model = "mandarin_mfa" if lang == "zh" else "english_us_arpa"
    args = mfa_cmd + [
        "align",
        "./corpus/", mfa_model, mfa_model, "./output/",
        "--clean",
        "--num_jobs", str(num_jobs),
    ]
    if beam:
        args += ["--beam", beam]
    if retry_beam:
        args += ["--retry_beam", retry_beam]

    cwd = os.getcwd()
    os.chdir(tmp_dir)
    try:
        logger.info("multichunk MFA cmd: %s", args)
        out = subprocess.check_output(args, stderr=subprocess.STDOUT, env=mfa_env)
        logger.info("multichunk MFA ok, stdout tail: %s",
                    out.decode("utf-8", errors="replace")[-400:])
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
    # MFA outputs TextGrids preserving the input corpus tree:
    #   corpus/spk/chunk_000.wav → output/spk/chunk_000.TextGrid
    corpus_spk = os.path.join(tmp_dir, "corpus", "spk")
    output_spk = os.path.join(tmp_dir, "output", "spk")
    results: dict[int, str] = {}

    for c in chunks:
        stem = f"chunk_{c['index']:03d}"
        wav = os.path.join(corpus_spk, stem + ".wav")
        grid = os.path.join(output_spk, stem + ".TextGrid")
        if not os.path.exists(grid):
            logger.warning("multichunk: missing TextGrid for %s", stem)
            results[c["index"]] = ""
            continue
        try:
            out = subprocess.check_output(
                [praat_bin, "--run", praat_script_path, wav, grid],
                stderr=subprocess.STDOUT,
            ).decode("utf-8")
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
                c["index"], len(tsv),
            )
            return None

        offset = float(c["start_sec"])
        word_idx_shift = len(merged_words)

        for w in parsed["words"]:
            merged_words.append({
                "time": float(w["time"]) + offset,
                "word": w["word"],
                "expected": w["expected"],
            })

        for p in parsed["phones"]:
            merged_phones.append({
                "time": (float(p["time"]) + offset) if p.get("time") is not None else None,
                "phoneme": p["phoneme"],
                "word_index": p["word_index"] + word_idx_shift,
                "word": p["word"],  # reference — compute_resonance doesn't use this
                "word_time": (float(p["word_time"]) + offset) if p.get("word_time") is not None else None,
                "expected": p["expected"],
                "F": list(p["F"]) if p.get("F") is not None else [None, None, None, None],
            })

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
) -> dict | None:
    """Multi-chunk pipeline starting from an already-decoded 16 kHz mono WAV.

    Caller is responsible for:
      - Producing ``full_wav`` (see ``decode_to_wav``) so the wrapper can
        reuse whatever it already needed for duration-probing + chunk
        planning, without re-decoding.
      - Creating ``tmp_dir`` and cleaning it up in a finally.
      - Passing ``praat_script_path`` — textgrid-formants.praat lives in
        the sidecar's WORKDIR, and this module doesn't assume cwd.
    """
    corpus_spk = os.path.join(tmp_dir, "corpus", "spk")
    slice_chunks(full_wav, chunks, corpus_spk, settings_dict["ffmpeg"])
    os.makedirs(os.path.join(tmp_dir, "output"), exist_ok=True)

    mfa_cmd, mfa_env = build_mfa_cmd(settings_dict)
    num_jobs = min(len(chunks), os.cpu_count() or 1)
    run_mfa(
        tmp_dir, lang, num_jobs, mfa_cmd, mfa_env,
        beam=mfa_beam, retry_beam=mfa_retry_beam,
    )

    # Confirm MFA produced something before Praat — fast-fail with a
    # clearer message than "empty TSV" further down.
    grids = glob.glob(os.path.join(tmp_dir, "output", "spk", "*.TextGrid"))
    if len(grids) == 0:
        logger.warning("multichunk: MFA produced 0 TextGrids")
        return None

    praat_tsvs = run_praat_per_chunk(
        tmp_dir, chunks, settings_dict["praat"], praat_script_path,
    )
    return merge_parses(chunks, praat_tsvs, lang)
