# Calibration corpus v1

Build an empirical resonance% distribution per (language × gender) so we can
recalibrate the advice / How-to-use copy that today implies 50% means
"neutral" — when the formula
`resonance = clamp(0, 1, w_F2·z_F2 + w_F3·z_F3 + w_F4·z_F4 + 0.5)`
defines 0.5 as the **female reference distribution mean**, not a male/female
midline.

## Buckets

Six buckets, each targeting **100 stitched ~60 s sessions / ≥100 minutes**:

| Lang   | Sex | Source                              | Notes                                 |
|--------|-----|-------------------------------------|---------------------------------------|
| zh-CN  | F   | AISHELL-3 train+test                | 175 F speakers available; 1 / spk     |
| zh-CN  | M   | AISHELL-3 train+test                | only 42 M speakers — multi-session (3 disjoint clip windows) per spk |
| en-US  | F   | LibriSpeech train-clean-100         | 125 F speakers; 1 / spk               |
| en-US  | M   | LibriSpeech train-clean-100         | 126 M speakers; 1 / spk               |
| fr-FR  | F   | Common Voice fr (validated.tsv)     | gender = `female_feminine`            |
| fr-FR  | M   | Common Voice fr (validated.tsv)     | gender = `male_masculine`             |

All clips are concatenated to one ~60 s wav per session, sent to the Engine C
sidecar in **script** mode (transcripts known) so we strip ASR error from the
chain.  The sidecar's response is reshaped into the worker's
`summary.engine_c` form via the imported helpers in
`voiceya.services.audio_analyser.engine_c`, then wrapped into voiceduck's
existing v1 `.vga.json` export schema (`web/src/modules/export-import.js`).

## Layout

Default `--out` is `/mnt/d/project_vocieduck/calibration_v1/`:

```
<lang>/
  manifest.jsonl                              # session metadata (one per line)
  stitched/{F,M}/<session_id>.wav             # ~60s stitched audio (kept on disk)
  raw/<session_id>.json                       # sidecar /engine_c/analyze cache
  sessions/{F,M}/session_<session_id>.vga.json   # v1 export bundle
```

Only `tests/reports/calibration_v1/` (aggregate.csv + per-vowel CSVs +
histograms.png + README.md) is committed to git — speech recordings carry
speaker identity and stay on the local disk.

## Usage

```bash
# stage all 6 buckets (≈ 10 min total)
uv run python -m scripts.calibration_v1.build_corpus stage \
    --lang zh-CN --lang en-US --lang fr-FR

# analyze (POST each stitched wav to sidecar) — ≈ 30 min, idempotent
uv run python -m scripts.calibration_v1.build_corpus analyze \
    --lang zh-CN --lang en-US --lang fr-FR

# pack raw JSON + manifest → vga.json bundles (fast, < 1 min)
uv run python -m scripts.calibration_v1.build_corpus pack \
    --lang zh-CN --lang en-US --lang fr-FR

# aggregate → tests/reports/calibration_v1/{aggregate.csv, *.png, README.md}
uv run python -m scripts.calibration_v1.aggregate
```

For smoke-testing with a tiny bucket (2 speakers per gender):

```bash
uv run python -m scripts.calibration_v1.build_corpus stage --limit 2 \
    --out /tmp/calibration_smoke
```

## Prerequisites

- Engine C sidecar reachable at `--sidecar` (default `http://localhost:8001`)
  with `zh`, `en`, `fr` advertised in `/healthz`.
- `ENGINE_C_TOKEN` env var set if the sidecar runs with auth (else empty).
- ffmpeg + ffprobe on PATH.
- Source corpora staged per the table above.

## Speaker-disjointness from existing stats

| Lang | Stats source                                | Calibration source             | Disjoint?           |
|------|--------------------------------------------|--------------------------------|---------------------|
| zh   | AISHELL-3 train (92 speakers, Phase B)     | AISHELL-3 full (217 speakers)  | partial (50 F + 42 M known overlap; reusing those is fine since we measure distribution, not validate the model) |
| en   | cmudict + upstream (gender-voice-visualization) | LibriSpeech train-clean-100  | yes (cmudict has no LibriSpeech speakers) |
| fr   | Common Voice fr v17 train (per CHANGELOG)   | Common Voice fr (any client_id) | partial (overlap by client_id possible — flagged in README; large enough sample that a few overlapping speakers don't shift bucket P50 meaningfully) |

This corpus measures **the distribution of resonance%** that real speakers
produce; it doesn't validate the resonance model itself.  Speaker overlap
with the stats training set is therefore tolerable.

## Why script mode?

Free mode (ASR via faster-whisper for en/fr, FunASR for zh) introduces a
language- and speaker-dependent ASR error rate in the upstream of the MFA
alignment.  We want the resonance distribution to depend on the **acoustics**
only, so we feed the known transcripts directly.  Source corpora come with
canonical transcripts (AISHELL `content.txt`, LibriSpeech `*.trans.txt`,
Common Voice `validated.tsv:sentence`).
