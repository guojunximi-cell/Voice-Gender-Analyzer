"""Standalone tests for multichunk.merge_parses.

Verifies that concatenating per-chunk phones.parse outputs produces a
merged dict indistinguishable (up to time offsets + word_index shifts)
from what the single-block pipeline would return for the same content.

Run: ``python tests/test_multichunk_merge.py``.  No pytest needed; no
ffmpeg/MFA/Praat needed (merge_parses is pure stdlib + phones.parse).
"""

from __future__ import annotations

import os
import sys
import traceback

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "voiceya", "sidecars", "wrapper"))
sys.path.insert(0, os.path.join(REPO, "voiceya", "sidecars", "visualizer-backend"))

# phones.parse reads cmudict.txt via bare relative path — chdir the same
# way uvicorn's CMD does in the sidecar (WORKDIR=/app in the Dockerfile).
os.chdir(os.path.join(REPO, "voiceya", "sidecars", "visualizer-backend"))

import multichunk  # noqa: E402


# Minimal Praat-output fragments in the exact format phones.parse expects.
# Format reminder (from phones.py:11-20):
#   "Words:\n" header, then lines "<time>\t<word>"
#   "Phonemes:\n" header, then lines "<time>\t<phoneme>\t<F0>\t<F1>\t<F2>\t<F3>"
# Phonemes must appear >= their owning word's time so the word_index
# walker (phones.py:60-66) advances correctly.

_CHUNK0_TSV = """Words:
0.000\tHELLO
0.500\tWORLD
Phonemes:
0.000\tHH\t120\t500\t1500\t2500
0.100\tAH\t125\t520\t1520\t2520
0.300\tL\t122\t510\t1510\t2510
0.500\tW\t130\t530\t1530\t2530
0.600\tER\t128\t525\t1525\t2525
0.800\tL\t126\t520\t1520\t2520
0.900\tD\t124\t515\t1515\t2515
"""

_CHUNK1_TSV = """Words:
0.000\tFOO
0.400\tBAR
Phonemes:
0.000\tF\t140\t540\t1540\t2540
0.200\tUW\t138\t535\t1535\t2535
0.400\tB\t136\t530\t1530\t2530
0.600\tAA\t134\t525\t1525\t2525
0.800\tR\t132\t520\t1520\t2520
"""


def test_basic_merge_offsets_and_shifts():
    chunks = [
        {"index": 0, "start_sec": 2.0, "end_sec": 3.5, "transcript": "hello world", "word_count": 2},
        {"index": 1, "start_sec": 5.0, "end_sec": 6.5, "transcript": "foo bar", "word_count": 2},
    ]
    tsvs = {0: _CHUNK0_TSV, 1: _CHUNK1_TSV}
    merged = multichunk.merge_parses(chunks, tsvs, lang="en")
    assert merged is not None

    # 2 + 2 = 4 words total, with times offset by each chunk's start
    words = merged["words"]
    assert len(words) == 4, words
    assert words[0]["word"] == "HELLO" and words[0]["time"] == 2.0
    assert words[1]["word"] == "WORLD" and words[1]["time"] == 2.5
    assert words[2]["word"] == "FOO" and words[2]["time"] == 5.0
    assert words[3]["word"] == "BAR" and words[3]["time"] == 5.4

    # 7 + 5 = 12 phones; chunk 1's phones must point at words[2:4]
    phonemes = merged["phones"]
    assert len(phonemes) == 12, len(phonemes)
    chunk0_phones = phonemes[:7]
    chunk1_phones = phonemes[7:]

    # Chunk 0: word_index 0/1 unchanged
    assert all(p["word_index"] in (0, 1) for p in chunk0_phones)
    # First phone is 'HH' at offset 0.0 → absolute 2.0
    assert chunk0_phones[0]["phoneme"] == "HH"
    assert chunk0_phones[0]["time"] == 2.0

    # Chunk 1: word_index must be shifted by 2 (chunk 0's word count)
    assert all(p["word_index"] in (2, 3) for p in chunk1_phones), [
        p["word_index"] for p in chunk1_phones
    ]
    # First phone in chunk 1 is 'F' at offset 0.0 → absolute 5.0
    assert chunk1_phones[0]["phoneme"] == "F"
    assert chunk1_phones[0]["time"] == 5.0
    assert chunk1_phones[0]["word_time"] == 5.0  # word 'FOO' is at local 0.0


def test_phone_formants_preserved():
    chunks = [
        {"index": 0, "start_sec": 0.0, "end_sec": 1.0, "transcript": "hello world", "word_count": 2},
    ]
    merged = multichunk.merge_parses(chunks, {0: _CHUNK0_TSV}, lang="en")
    assert merged is not None
    # The 'HH' phone's formants should round-trip untouched.
    assert merged["phones"][0]["F"] == [120.0, 500.0, 1500.0, 2500.0]


def test_empty_tsv_aborts():
    chunks = [
        {"index": 0, "start_sec": 0.0, "end_sec": 1.0, "transcript": "x", "word_count": 1},
        {"index": 1, "start_sec": 2.0, "end_sec": 3.0, "transcript": "y", "word_count": 1},
    ]
    # Second chunk has no Praat output → merge should abort
    assert multichunk.merge_parses(chunks, {0: _CHUNK0_TSV, 1: ""}, lang="en") is None


def test_missing_chunk_tsv_aborts():
    chunks = [
        {"index": 0, "start_sec": 0.0, "end_sec": 1.0, "transcript": "x", "word_count": 1},
        {"index": 1, "start_sec": 2.0, "end_sec": 3.0, "transcript": "y", "word_count": 1},
    ]
    assert multichunk.merge_parses(chunks, {0: _CHUNK0_TSV}, lang="en") is None


def test_zero_phone_chunk_aborts():
    """A chunk whose TSV has Words: but no Phonemes: lines is a failed
    alignment — merge should abort rather than return a degraded result."""
    bad_tsv = "Words:\n0.000\tHELLO\nPhonemes:\n"
    chunks = [
        {"index": 0, "start_sec": 0.0, "end_sec": 1.0, "transcript": "hello", "word_count": 1},
    ]
    assert multichunk.merge_parses(chunks, {0: bad_tsv}, lang="en") is None


def test_chunks_out_of_order_still_merged_in_time_order():
    """Chunker returns chunks in time order, but be defensive — merge_parses
    sorts by index so higher-index chunks come after lower ones in the
    output regardless of dict insertion order."""
    chunks = [
        {"index": 1, "start_sec": 5.0, "end_sec": 6.5, "transcript": "foo bar", "word_count": 2},
        {"index": 0, "start_sec": 2.0, "end_sec": 3.5, "transcript": "hello world", "word_count": 2},
    ]
    tsvs = {0: _CHUNK0_TSV, 1: _CHUNK1_TSV}
    merged = multichunk.merge_parses(chunks, tsvs, lang="en")
    assert merged is not None
    # HELLO first, FOO last, regardless of input chunks list order
    assert merged["words"][0]["word"] == "HELLO"
    assert merged["words"][-1]["word"] == "BAR"


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
