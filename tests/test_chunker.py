"""Standalone tests for voiceya/sidecars/wrapper/chunker.py.

Run: ``python tests/test_chunker.py`` from the repo root (no pytest needed).
Exit code 0 = all pass; any AssertionError propagates with the test name.
"""

from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "voiceya", "sidecars", "wrapper"))

import chunker  # noqa: E402


def _words(pairs: list[tuple[str, float, float]]) -> list[dict]:
    """Convenience: build word_timestamps from (word, start, end) triples."""
    return [{"word": w, "start": s, "end": e} for w, s, e in pairs]


def _silences(pairs: list[tuple[float, float]]) -> list[dict]:
    return [{"start": s, "end": e} for s, e in pairs]


# ── Tests ────────────────────────────────────────────────────────────

def test_happy_path_two_chunks():
    """20 s audio, candidates at 7.5 and 16.0 → balanced picks 7.5.

    With target=10 → desired_n = max(2, 20 // 10) = 2.  Ideal single cut
    is at audio/2 = 10.0.  Nearest candidate: 7.5 (dist 2.5) beats 16.0
    (dist 6.0).  Resulting chunks: (0-7.5, 7.5-20.0), both within
    [min=3.0, max=20.0].  This is what we *want* — balanced chunks for
    MFA parallelism, even though 7.5 s isn't "full-target" sized.
    """
    words = _words([
        ("hello", 0.5, 1.0), ("world", 1.2, 1.8), ("this", 2.0, 2.3),
        ("is", 2.5, 2.6), ("sentence", 2.8, 3.5), ("one", 3.7, 4.0),
        ("second", 11.0, 11.6), ("sentence", 11.8, 12.5), ("starts", 12.8, 13.4),
        ("here", 13.6, 14.0), ("ends", 18.0, 18.6), ("now", 19.0, 19.5),
    ])
    silences = _silences([(4.2, 10.8), (14.2, 17.8)])  # midpoints 7.5 and 16.0
    chunks = chunker.plan_chunks(20.0, words, silences,
        target_chunk_sec=10.0, max_chunk_sec=20.0, min_chunk_sec=3.0)
    assert chunks is not None, "expected chunks"
    assert len(chunks) == 2, f"expected 2 chunks, got {len(chunks)}"
    assert chunks[0]["start_sec"] == 0.0
    assert chunks[0]["end_sec"] == 7.5, chunks[0]
    assert chunks[1]["end_sec"] == 20.0
    # Words 0-5 have mid < 7.5 ("hello" 0.75 ... "one" 3.85); rest go to chunk 1.
    assert chunks[0]["word_count"] == 6, chunks[0]
    assert chunks[1]["word_count"] == 6, chunks[1]


def test_reject_too_short():
    words = _words([("a", 0.1, 0.3), ("b", 0.4, 0.6)])
    silences = _silences([(0.7, 1.5)])
    assert chunker.plan_chunks(2.0, words, silences, min_chunk_sec=3.0) is None


def test_reject_no_words():
    assert chunker.plan_chunks(30.0, [], []) is None
    assert chunker.plan_chunks(30.0, [{"word": "x", "start": 0, "end": 1}], []) is None


def test_reject_no_silences():
    """Long audio but no silence ranges → can't pick safe cuts."""
    words = _words([("a", 0.1, 1.0), ("b", 2.0, 3.0), ("c", 5.0, 6.0)])
    assert chunker.plan_chunks(30.0, words, []) is None


def test_reject_degenerate_timestamps():
    """All words collapsed to same timestamp → no alignment signal."""
    words = _words([
        ("a", 0.0, 0.0), ("b", 0.0, 0.0), ("c", 0.0, 0.0),
        ("d", 0.0, 0.0), ("e", 0.0, 0.0),
    ])
    silences = _silences([(5.0, 10.0)])
    assert chunker.plan_chunks(30.0, words, silences) is None


def test_reject_short_silence():
    """Silence shorter than min_silence_sec → rejected as cut point."""
    words = _words([("a", 0.5, 1.0), ("b", 8.0, 8.5), ("c", 15.0, 15.5)])
    silences = _silences([(1.2, 1.4)])  # 0.2 s gap, too short
    assert chunker.plan_chunks(20.0, words, silences, min_silence_sec=0.5) is None


def test_reject_silence_straddling_word():
    """Silence midpoint falls inside a word — reject that silence."""
    # Silence range is 5.0-6.0 but a word covers 5.0-5.8.  Midpoint 5.5 is
    # inside the word, so this silence is not a safe cut.
    words = _words([
        ("before", 0.5, 1.0),
        ("weird", 5.0, 5.8),  # overlaps the silence
        ("after", 9.0, 9.5), ("last", 14.0, 14.5),
    ])
    silences = _silences([(5.0, 6.0)])
    result = chunker.plan_chunks(18.0, words, silences)
    assert result is None, f"expected None, got {result}"


def test_bails_when_no_candidate_keeps_all_chunks_under_max():
    """If no combination of available cuts produces chunks <= max_chunk_sec,
    return None rather than force a bad split.  Balanced selection won't
    emit a chunk that violates max — falling back to single-block is the
    honest answer."""
    words = _words([("a", 0.5, 1.0), ("b", 4.0, 4.5), ("c", 15.0, 15.5)])
    # Only candidate is at 3.1 → splits would be (0-3.1, 3.1-18) or no
    # split.  The 14.9 s right chunk exceeds max=8 in either case.
    silences = _silences([(2.5, 3.7)])
    result = chunker.plan_chunks(18.0, words, silences,
        min_chunk_sec=3.0, target_chunk_sec=8.0, max_chunk_sec=8.0)
    assert result is None, f"expected None (no valid split), got {result}"


def test_tail_absorbed_when_too_short():
    """Trailing chunk shorter than min_chunk_sec → merge into previous."""
    words = _words([("a", 0.5, 1.0), ("b", 5.0, 5.5), ("tail", 11.5, 11.8)])
    silences = _silences([(2.5, 4.0), (10.8, 11.3)])  # cuts at 3.25 and 11.05
    chunks = chunker.plan_chunks(12.0, words, silences,
        min_chunk_sec=3.0, target_chunk_sec=3.5, max_chunk_sec=10.0)
    assert chunks is not None, "expected chunks"
    # Final tail would be 12.0 - 11.05 = 0.95 s < 3.0 min, so it's merged.
    assert chunks[-1]["end_sec"] == 12.0
    assert not any(c["end_sec"] - c["start_sec"] < 3.0 for c in chunks), chunks


def test_max_chunks_enforced():
    """More candidate cuts than max_chunks → merge shortest neighbors down."""
    # 60 s audio, silences every 5 s.  With max_chunks=3 we should end up
    # with 3 chunks regardless of candidates.
    words = _words([(f"w{i}", i * 2.0 + 0.1, i * 2.0 + 0.9) for i in range(30)])
    silences = _silences([(i * 10.0 + 4.5, i * 10.0 + 5.5) for i in range(5)])
    chunks = chunker.plan_chunks(60.0, words, silences,
        min_chunk_sec=3.0, target_chunk_sec=5.0, max_chunk_sec=30.0,
        max_chunks=3)
    assert chunks is not None
    assert len(chunks) <= 3, f"expected <=3 chunks, got {len(chunks)}"
    # Words must still all be allocated.
    total_words = sum(c["word_count"] for c in chunks)
    assert total_words == 30, f"lost words: {total_words}/30"


def test_1to1_alignment_preserved():
    """Every word in the input shows up in exactly one chunk's transcript."""
    words = _words([
        ("the", 0.1, 0.3), ("quick", 0.4, 0.7), ("brown", 0.8, 1.1),
        ("fox", 1.2, 1.5), ("jumps", 3.5, 3.9), ("over", 4.0, 4.3),
        ("the", 4.4, 4.5), ("lazy", 4.6, 4.9), ("dog", 5.0, 5.3),
    ])
    silences = _silences([(1.7, 3.3)])  # one silence at midpoint 2.5
    chunks = chunker.plan_chunks(6.0, words, silences,
        target_chunk_sec=3.0, max_chunk_sec=5.0, min_chunk_sec=2.0)
    assert chunks is not None, "expected chunks"
    recombined = " ".join(c["transcript"] for c in chunks).split()
    original = [w["word"] for w in words]
    assert recombined == original, (
        f"word alignment broken:\noriginal={original}\nrecombined={recombined}"
    )


def test_chunks_are_contiguous_and_cover_audio():
    words = _words([
        ("a", 0.5, 1.0), ("b", 1.5, 2.0), ("c", 10.0, 10.5),
        ("d", 11.0, 11.5), ("e", 19.0, 19.5),
    ])
    silences = _silences([(3.0, 9.0), (12.5, 18.0)])
    chunks = chunker.plan_chunks(22.0, words, silences)
    assert chunks is not None
    assert chunks[0]["start_sec"] == 0.0
    assert chunks[-1]["end_sec"] == 22.0
    for i in range(len(chunks) - 1):
        assert chunks[i]["end_sec"] == chunks[i + 1]["start_sec"], \
            f"gap between chunk {i} and {i+1}: {chunks[i]}, {chunks[i+1]}"


# ── Runner ───────────────────────────────────────────────────────────

def _run_all():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_all())
