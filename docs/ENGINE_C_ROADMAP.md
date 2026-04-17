# Robustness Roadmap: Adversarial & Edge-Case Hardening

> Single source of truth for post-launch hardening.
> Generated 2026-04-17 from adversarial threat modeling session.

---

## How to read this document

Each item has:
- **ID** for cross-referencing (e.g. `ATK-2`, `EDGE-C`)
- **Priority tier**: P0 (immediate) / P1 (mid-term) / P2 (defer)
- **Affected engine(s)**: A / B / C / API
- **Impact**: what happens today
- **Fix sketch**: concrete direction, not a full design

---

## Part 1: Adversarial Attack Vectors

_Assumption: attacker can only upload audio through the public API. No infra/DDoS._

### P0 -- Fix Immediately

#### ATK-1 Duration metadata spoofing (API + all engines)

| | |
|---|---|
| **Vector** | Craft a WebM/Matroska where Segment Info Duration = 30 s but actual audio blocks contain ~20 min of Opus. File stays under `MAX_FILE_SIZE_MB` (10 MB at ~6 kbps Opus). |
| **Code path** | `api.py:88` trusts `get_duraton_sec()` which reads container metadata. `normalize_to_pcm()` at `audio_tools.py:57` iterates `s.decode(i_stm)` over **all actual frames**, not the declared duration. |
| **Impact** | Worker decodes 20 min into ~84 MB PCM; librosa loads another copy as float32. Single worker blocked for minutes. With `MAX_CONCURRENT=2`, two such requests stall the entire system. |
| **Fix sketch** | Add a **frame-count guard** inside `normalize_to_pcm`: track cumulative decoded duration; abort once it exceeds `MAX_AUDIO_DURATION_SEC + margin`. Example: `if total_samples / 16000 > CFG.max_audio_duration_sec * 1.1: raise HTTPException(413, ...)`. This makes the decode loop authoritative, not the metadata. |

#### ATK-2 Synthetic pure-tone → gender_score silently collapses to ~50 (Engine B)

| | |
|---|---|
| **Vector** | Upload a single-frequency sine wave at 165 Hz (the exact center of `_score_pitch`'s sigmoid). No real speech needed -- a 10-line Python script generates the WAV. |
| **Code path** | `acoustic_analyzer.py:62` -- pyin detects F0=165 → `pitch_score` ≈ 50. Pure tone has no natural formant structure → LPC roots scatter → `_extract_formants` returns `(None, None, None)` → `_score_formants` falls back to 50. `_compute_resonance` walks the pitch-prior-only path. Final `gender_score` ≈ 50 -- a meaningless neutral value. |
| **Impact** | Attacker can produce any desired gender_score by choosing the sine frequency. No crash, no error, just silently wrong data that looks legitimate. |
| **Fix sketch** | Add a **speech quality gate** before Engine B scoring. Candidates: (a) check `voiced_frames / total_frames` ratio -- pure tones have nearly 100% voicing with zero F0 variance; (b) require F0 std > threshold (natural speech has jitter, pure tones don't); (c) require at least 2 of 3 formants to be present (F1+F2 minimum). If the gate fails, set `acoustics = None` with a flag like `"skip_reason": "non_speech_signal"` instead of returning a fake score. |

---

### P1 -- Mid-Term

#### ATK-3 Pitch-shifted audio → Engine A/B verdict contradiction (Engine A + B)

| | |
|---|---|
| **Vector** | TTS-generate a female voice, then pitch-shift F0 down to ~120 Hz while preserving the spectral envelope (PSOLA/WORLD vocoder). Or vice versa: male voice pitch-shifted up. |
| **Code path** | Engine A's CNN classifies on mel-spectrogram shape (spectral envelope) → labels segments as original gender. Engine B's F0/formant analysis sees the shifted pitch → scores toward the opposite gender. |
| **Impact** | `female_ratio` (from A) and `gender_score` (from B) point in opposite directions. The report is self-contradictory. Not a crash, but trust in the system drops. |
| **Fix sketch** | Add a **consistency check** in `do_statics()`: if Engine A's dominant label disagrees strongly with Engine B's composite score (e.g. A says 80% female but B's score < 30), flag the result with `"warning": "pitch_envelope_mismatch"`. Don't suppress either engine's output -- surface the discrepancy to the user. Longer term, consider F0-normalized gender scoring that separates pitch contribution from resonance contribution. |

#### ATK-4 F0 pushed outside [60, 500] Hz → Engine B goes silent (Engine B)

| | |
|---|---|
| **Vector** | Pitch-shift speech so F0 lands at 50-59 Hz or 501-520 Hz. Still audible as speech to humans. |
| **Code path** | `acoustic_analyzer.py:62`: `voiced_f0 = f0[voiced_flag & (f0 > 60) & (f0 < 500)]`. All frames filtered → `len(voiced_f0) < 3` → `analyze_segment` returns `None`. |
| **Impact** | Engine B produces no output for segments that Engine A still labels as speech. User sees duration/label but zero acoustic metrics. |
| **Fix sketch** | Widen the hard bounds to [40, 600] Hz (still well within pyin's [C2, C6] range). Add a soft quality flag when median F0 is in the extreme tails (< 75 or > 400) rather than discarding all data. |

#### ATK-5 Triple memory copy when Engine C is on (Engine C + B)

| | |
|---|---|
| **Vector** | Upload a max-duration (180 s) file with Engine C enabled. |
| **Code path** | Full audio is loaded three times: (1) `seg_analyser.py:39` librosa for Engine B, (2) `__init__.py:43` `sample.read()` for Engine C, (3) `engine_c_asr.py:59` librosa again inside `_transcribe_sync`. Peak: ~35 MB for 180 s, higher with spectrograms. |
| **Impact** | Not a crash on its own, but compounds with ATK-1 and limits headroom for concurrent requests. |
| **Fix sketch** | Refactor `do_analyse` to read `sample.read()` once into `audio_bytes`, pass it to both Engine B (via `BytesIO(audio_bytes)`) and Engine C directly. Eliminates one copy. For Engine C ASR, accept the raw bytes directly instead of re-decoding from BytesIO -- the audio is already 16 kHz mono PCM at that point, so `np.frombuffer(audio_bytes[44:], dtype=np.int16).astype(np.float32) / 32768` replaces the second librosa call entirely. |

---

### P2 -- Defer

#### ATK-6 Background music → formant confusion (Engine A + B)

| | |
|---|---|
| **Vector** | Upload speech mixed with instrumental music. |
| **Code path** | Engine A may classify music segments as "male" (low-frequency energy). Engine B's pyin tracks the melody pitch instead of vocal F0; LPC extracts instrument harmonics as formants. |
| **Impact** | Scores reflect the music, not the speaker. Misleading but does not crash. |
| **Fix sketch** | Not worth a custom solution. If needed later, add a source-separation preprocessor (e.g. Demucs) to isolate vocals before analysis. Heavy dependency -- defer until user demand justifies it. |

#### ATK-7 Engine C: ASR hallucination → long transcript → MFA timeout (Engine C)

| | |
|---|---|
| **Vector** | Upload noise/music that triggers FunASR's hallucination mode (known ASR failure mode), producing a very long garbage transcript. |
| **Code path** | `engine_c.py:79` sends the full transcript to sidecar. MFA attempts forced alignment of hundreds of garbage characters against 180 s audio → CPU-bound for up to `engine_c_sidecar_timeout_sec` (60 s). |
| **Impact** | Worker blocked for 60 s waiting on sidecar timeout. Engine C returns `None`, main result unaffected. |
| **Fix sketch** | Cap transcript length before sending to sidecar: `transcript = transcript[:500]`. A 180 s audio at normal speaking rate produces ~500 Chinese characters. Anything beyond that is almost certainly hallucination. |

#### ATK-8 Magic bytes bypass → HTTP 500 (API)

| | |
|---|---|
| **Vector** | Craft a file whose first 12 bytes are a valid RIFF/WAVE header, rest is random garbage. |
| **Code path** | `is_valid_audio_file` passes. `av.open` fails during decode. Exception caught → HTTP 500. |
| **Impact** | Minimal -- error handling works correctly. User sees a 500 error, nothing leaks. |
| **Fix sketch** | No code change needed. Optionally downgrade the 500 to a 422 ("unprocessable audio") for cleaner UX, but not a priority. |

---

## Part 2: Transgender User Edge Cases

_These are not attacks. They are real scenarios from the target user base that the current system handles poorly or uninformatively._

### P0 -- Fix Immediately

#### EDGE-C High pitch + untrained resonance → score suppression

| | |
|---|---|
| **Scenario** | Trans woman has trained pitch to ~220 Hz (solidly feminine range) but vocal tract resonance is unchanged (VTL ≈ 17 cm, typical male). |
| **What happens** | `pitch_score` ≈ 94. But `_compute_resonance` gives VTL 65% weight vs pitch 35% → `resonance_pct` ≈ 49. `_composite_score` weights: pitch 45% + formant 30% + resonance 15% + tilt 10%. With male-pattern formants, final `gender_score` ≈ 60-65. |
| **User experience** | "I've been training pitch for months and it's clearly in female range, but the app still says 63?" This is the single most likely cause of user frustration and distrust. |
| **Fix sketch** | Two changes: (1) Break out `pitch_score` and `resonance_score` as **separately displayed metrics** in the UI, not just merged into one composite number. A user who sees "Pitch: 94, Resonance: 49" understands where to focus training. (2) Consider adding a "training progress" view that tracks pitch and resonance independently over time, since they improve on different timescales. The composite `gender_score` can remain as a summary but should not be the only number the user sees. |

#### EDGE-B Vocal fry (F0 < 60 Hz) → "no speech detected"

| | |
|---|---|
| **Scenario** | Early voice training often produces vocal fry (creaky voice) with F0 below 60 Hz. Common and expected. |
| **What happens** | `acoustic_analyzer.py:62` hard-filters F0 < 60 Hz. If the entire segment is fry, `analyze_segment` returns `None`. User sees a segment labeled "female" or "male" by Engine A but with no acoustic data. |
| **User experience** | "The app says I'm speaking but gives me no scores. Is it broken?" |
| **Fix sketch** | Same as ATK-4: widen the hard F0 bound to 40 Hz. Add a `"quality_note"` field when median F0 < 75 Hz: `"vocal_fry_detected"`. This tells the user their voice is being analyzed but the fry register limits accuracy. |

---

### P1 -- Mid-Term

#### EDGE-A Mixed register in one recording → averaged-out score

| | |
|---|---|
| **Scenario** | User records 3 minutes: first half in chest voice (for comparison), second half in trained head voice. |
| **What happens** | `do_statics` computes duration-weighted averages across all segments. Chest voice pulls F0/score down, head voice pulls up. Result: `gender_score ≈ 50`, `female_ratio ≈ 0.5`. |
| **User experience** | "I wanted to see how my head voice compares to my chest voice, but I just get one blurry average." |
| **Fix sketch** | The per-segment data is already computed and returned in `result["analysis"]`. The fix is **frontend-only**: display a timeline/chart of per-segment `gender_score` and `f0_median_hz` so users can see the contrast. The backend already provides everything needed. |

#### EDGE-D Whisper recording → no results

| | |
|---|---|
| **Scenario** | User records in a quiet voice (dormitory at night, shared space). Whisper has no stable glottal vibration. |
| **What happens** | pyin finds no voiced frames → `analyze_segment` returns `None` for all segments. Engine A may classify as "noEnergy". |
| **User experience** | "I uploaded a 2-minute recording and got nothing back." |
| **Fix sketch** | Add a **minimum voiced ratio check** after Engine A: if `total_voiced_duration / total_duration < 0.1`, return early with a user-facing message: `"录音中有效语音过少，请在安静环境下用正常音量重新录制"`. Better than silent empty results. |

#### EDGE-F Recording device variance → inconsistent scores

| | |
|---|---|
| **Scenario** | Same person records on phone (AGC + noise reduction) vs laptop mic vs USB condenser. |
| **What happens** | Phone AGC compresses dynamic range, reducing H1-H2 breathiness cues. Phone noise reduction alters formant structure. `tilt_score` and `formant_score` shift by 5-15 points across devices. |
| **User experience** | "I got 72 on my phone yesterday and 58 on my laptop today. Am I getting worse?" |
| **Fix sketch** | Add a disclaimer in the UI: "scores may vary by ±10 points across recording devices". Longer term, consider a **device normalization** step (detect AGC artifacts by checking amplitude histogram flatness, adjust H1-H2 weight accordingly). This is research-grade work -- defer the algorithm, ship the disclaimer now. |

---

### P2 -- Defer

#### EDGE-E Non-Mandarin Chinese dialect → Engine C degradation

| | |
|---|---|
| **Scenario** | Cantonese, Hokkien, or Wu dialect speaker uploads audio. |
| **What happens** | Engines A/B unaffected (pure acoustics). Engine C: Paraformer-zh produces garbled Mandarin transcript → MFA alignment mostly OOV → phone-level analysis unreliable. Engine C returns data but with very few matched phones. |
| **User experience** | Engine C results are present but inaccurate. If displayed, they mislead. |
| **Fix sketch** | Check `engine_c_summary["phone_count"]` relative to audio duration. If `phone_count / duration_sec < 1` (normal speech is ~4-6 phones/sec), demote Engine C results to `null` with a note. Proper dialect support requires dialect-specific ASR + MFA models -- out of scope for now. |

#### EDGE-G Singing / humming → wrong feature extraction

| | |
|---|---|
| **Scenario** | User uploads singing to check their singing voice gender perception. |
| **What happens** | pyin tracks melody pitch (not speaking F0). Formants reflect singing resonance (deliberately altered). `gender_score` reflects singing technique, not natural voice. |
| **User experience** | Scores don't match their speaking voice at all, confusing. |
| **Fix sketch** | Detect singing by checking F0 variance pattern (singing has stepwise pitch changes, speech has gradual contours). If detected, add a warning. Low priority -- singing analysis is a different product. |

---

## Implementation Tracker

| ID | Priority | Engine | Category | Status |
|----|----------|--------|----------|--------|
| ATK-1 | P0 | API | Duration spoof | TODO |
| ATK-2 | P0 | B | Synthetic audio | TODO |
| EDGE-C | P0 | B/UI | Score suppression | TODO |
| EDGE-B | P0 | B | Vocal fry cutoff | TODO |
| ATK-3 | P1 | A+B | A/B contradiction | TODO |
| ATK-4 | P1 | B | F0 hard bounds | TODO |
| ATK-5 | P1 | C+B | Memory copies | TODO |
| EDGE-A | P1 | UI | Per-segment display | TODO |
| EDGE-D | P1 | API | Whisper detection | TODO |
| EDGE-F | P1 | UI | Device variance | TODO |
| ATK-6 | P2 | A+B | Music confusion | TODO |
| ATK-7 | P2 | C | ASR hallucination | TODO |
| ATK-8 | P2 | API | Magic bytes | TODO |
| EDGE-E | P2 | C | Dialect support | TODO |
| EDGE-G | P2 | A+B | Singing detection | TODO |
