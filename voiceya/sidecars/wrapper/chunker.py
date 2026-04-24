"""Audio + transcript chunker for parallel MFA alignment (Engine C).

Given ASR word timestamps and ffmpeg silencedetect ranges from the same
audio, pick cut points inside silent gaps so each chunk is a self-
contained sentence-ish span.  Returns time ranges + per-chunk transcript
slices; the caller slices the audio (ffmpeg -ss/-t) and invokes MFA with
``--num_jobs N`` to align all chunks in one process.

Returns ``None`` to signal "don't chunk" (too short, no usable cut points,
degenerate word timestamps, or only one chunk would result).  Caller falls
back to the single-block MFA path.

Pure stdlib on purpose — easy to unit-test without audio dependencies.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("engine_c.chunker")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


# Defaults sized for typical voice-analyzer uploads (10-60 s clips of
# continuous speech).  Env-tunable so ops can shift the knobs without a
# redeploy — same pattern as ENGINE_C_MFA_BEAM in the wrapper.
_DEFAULT_MIN_CHUNK_SEC = _env_float("ENGINE_C_CHUNK_MIN_SEC", 3.0)
_DEFAULT_MAX_CHUNK_SEC = _env_float("ENGINE_C_CHUNK_MAX_SEC", 20.0)
_DEFAULT_TARGET_CHUNK_SEC = _env_float("ENGINE_C_CHUNK_TARGET_SEC", 10.0)
_DEFAULT_MIN_SILENCE_SEC = _env_float("ENGINE_C_CHUNK_MIN_SILENCE_SEC", 0.5)
_DEFAULT_MAX_CHUNKS = _env_int("ENGINE_C_CHUNK_MAX_COUNT", 8)


def plan_chunks(
    audio_duration_sec: float,
    word_timestamps: list[dict],
    silence_ranges: list[dict],
    *,
    min_chunk_sec: float | None = None,
    max_chunk_sec: float | None = None,
    target_chunk_sec: float | None = None,
    min_silence_sec: float | None = None,
    max_chunks: int | None = None,
) -> list[dict] | None:
    """Plan parallel-alignment chunks.

    Args:
        audio_duration_sec: total audio length.
        word_timestamps: list of ``{word, start, end}`` from ASR, sorted by
            start.  ``transcript.split()`` order is assumed to match this
            list 1:1.
        silence_ranges: list of ``{start, end}`` from ffmpeg silencedetect.
        Knobs override the ``ENGINE_C_CHUNK_*`` env defaults.

    Returns:
        List of ``{index, start_sec, end_sec, transcript, word_count}`` in
        time order, or ``None`` if chunking is inadvisable.
    """
    min_chunk = min_chunk_sec if min_chunk_sec is not None else _DEFAULT_MIN_CHUNK_SEC
    max_chunk = max_chunk_sec if max_chunk_sec is not None else _DEFAULT_MAX_CHUNK_SEC
    target_chunk = target_chunk_sec if target_chunk_sec is not None else _DEFAULT_TARGET_CHUNK_SEC
    min_silence = min_silence_sec if min_silence_sec is not None else _DEFAULT_MIN_SILENCE_SEC
    max_n = max_chunks if max_chunks is not None else _DEFAULT_MAX_CHUNKS

    # 1. Preconditions.
    if not word_timestamps or len(word_timestamps) < 2:
        return None
    if audio_duration_sec < min_chunk * 2:
        return None  # too short — no parallelism win.

    # 2. Sanity-check word timestamp quality.  If every word shares the same
    #    (start, end) with its neighbor (the hallucination signal we saw in
    #    the ASR spike), chunking can't pick meaningful boundaries.
    positive_gaps = sum(
        1 for i in range(1, len(word_timestamps))
        if word_timestamps[i]["start"] > word_timestamps[i - 1]["end"]
    )
    if positive_gaps < 2:
        logger.info(
            "chunker: degenerate word timestamps (positive_gaps=%d), skipping",
            positive_gaps,
        )
        return None

    # 3. Candidate cut points: midpoint of each long-enough silence, rejected
    #    if a word straddles it (shouldn't happen if silencedetect + whisper
    #    agree, but faster-whisper's VAD and ffmpeg's -30 dB threshold don't
    #    always align, so guard explicitly).
    candidates: list[float] = []
    for sr in silence_ranges:
        try:
            start = float(sr["start"])
            end = float(sr["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end - start < min_silence:
            continue
        mid = (start + end) / 2.0
        if any(w["start"] < mid < w["end"] for w in word_timestamps):
            continue
        candidates.append(mid)
    candidates.sort()

    if not candidates:
        logger.info("chunker: no usable silence cuts, skipping")
        return None

    # 4. Greedy selection — cut when we've accumulated >= target OR when
    #    skipping this candidate would push the next chunk past max.
    chunks: list[tuple[float, float]] = []
    cur_start = 0.0
    for i, cand in enumerate(candidates):
        dur_here = cand - cur_start
        if dur_here < min_chunk:
            continue  # can't cut yet — next candidate.

        # Peek the next candidate (or end-of-audio as sentinel).
        next_cand = candidates[i + 1] if i + 1 < len(candidates) else audio_duration_sec
        dur_if_skip = next_cand - cur_start

        if dur_here >= target_chunk or dur_if_skip > max_chunk:
            chunks.append((cur_start, cand))
            cur_start = cand

    # Final tail.  If the tail is shorter than min_chunk, extend the last
    # chunk to the end of audio (absorb rather than split off a tiny chunk
    # with too few phones for MFA to align reliably).
    tail = audio_duration_sec - cur_start
    if tail >= min_chunk:
        chunks.append((cur_start, audio_duration_sec))
    elif chunks:
        prev_start, _ = chunks[-1]
        chunks[-1] = (prev_start, audio_duration_sec)
    # else: no chunks at all — falls through to the <2 check below.

    if len(chunks) < 2:
        return None

    # 5. Cap chunk count.  With max_chunks=8 this rarely triggers, but long
    #    / pause-heavy audio can produce 10+ candidate cuts.  Greedy merge
    #    the shortest chunk into its shorter neighbor until we're under cap.
    while len(chunks) > max_n:
        shortest = min(range(len(chunks)), key=lambda i: chunks[i][1] - chunks[i][0])
        if shortest == 0:
            merge_with = 1
        elif shortest == len(chunks) - 1:
            merge_with = shortest - 1
        else:
            left_dur = chunks[shortest - 1][1] - chunks[shortest - 1][0]
            right_dur = chunks[shortest + 1][1] - chunks[shortest + 1][0]
            merge_with = shortest - 1 if left_dur <= right_dur else shortest + 1
        lo, hi = sorted((shortest, merge_with))
        chunks[lo] = (chunks[lo][0], chunks[hi][1])
        del chunks[hi]

    # 6. Allocate words to chunks by word midpoint.  Using midpoint avoids
    #    boundary ambiguity (a word that starts in chunk N and ends in N+1
    #    goes to whichever side owns more of it).  Last chunk also claims
    #    any trailing word whose midpoint == end (closed interval on right).
    result: list[dict] = []
    last_idx = len(chunks) - 1
    for idx, (s, e) in enumerate(chunks):
        chunk_words: list[str] = []
        for w in word_timestamps:
            mid = (w["start"] + w["end"]) / 2.0
            in_range = s <= mid < e or (idx == last_idx and s <= mid <= e)
            if in_range:
                chunk_words.append(w["word"])
        if not chunk_words:
            # A zero-word chunk would feed MFA an empty transcript → abort
            # the whole plan.  Caller falls back to single-block.
            logger.warning(
                "chunker: chunk %d (%.2f-%.2fs) got no words, aborting plan",
                idx, s, e,
            )
            return None
        result.append({
            "index": idx,
            "start_sec": round(s, 3),
            "end_sec": round(e, 3),
            "transcript": " ".join(chunk_words),
            "word_count": len(chunk_words),
        })

    return result
