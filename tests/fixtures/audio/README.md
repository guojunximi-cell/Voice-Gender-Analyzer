# Test Fixture Audio Files

These files are required by `scripts/validate_docker.py --fixtures tests/fixtures/audio`.

All WAV files should be Mandarin Chinese speech, 16 kHz mono PCM (or any format
supported by ffmpeg — the app transcodes internally).

## Required files

### Tasks 5 — Engine C resonance range check
| File | Duration | Speaker |
|------|----------|---------|
| `zh_10s.wav`  | ~10 s | any Mandarin speaker |
| `zh_30s.wav`  | ~30 s | any Mandarin speaker |
| `zh_60s.wav`  | ~60 s | any Mandarin speaker |

### Tasks 7 — 5m/5f median regression
| File | Speaker |
|------|---------|
| `male_1.wav` … `male_5.wav`     | five different **male** Mandarin speakers |
| `female_1.wav` … `female_5.wav` | five different **female** Mandarin speakers |

Each regression file should be 15–60 s of continuous speech.

### Task 8 uses any one of the above (prefers zh_30s.wav).

## Generating from Common Voice / AISHELL

```bash
# Example: trim an AISHELL-3 recording to 30 s
ffmpeg -i /path/to/aishell_speaker.wav -t 30 -ar 16000 -ac 1 tests/fixtures/audio/zh_30s.wav
```

## Why these are not committed

Speech recordings may carry speaker identity data.  Only commit fixtures with
explicit permission from speakers or that are clearly public-domain.
