"""
Engine B: Acoustic analysis of a single audio segment.
Computes F0, Formants (F1/F2/F3 via LPC), Spectral Tilt, VTL/Resonance,
and a composite gender score (0=male, 100=female).

Usage:
    import librosa
    from acoustic_analyzer import analyze_segment
    y, sr = librosa.load("sample.wav", sr=22050, mono=True)
    result = analyze_segment(y, sr)
"""

import numpy as np
import librosa
from scipy.signal import butter, sosfilt
from scipy.linalg import solve_toeplitz


def _lpc(frame: np.ndarray, order: int) -> np.ndarray:
    """Autocorrelation-method LPC (replaces scipy.signal.lpc removed in 1.16+)."""
    n = len(frame)
    r = np.correlate(frame, frame, mode='full')[n - 1 : n + order]
    a = solve_toeplitz(r[:order], -r[1 : order + 1])
    return np.concatenate([[1.0], a])


# ─── Constants ────────────────────────────────────────────────
SPEED_OF_SOUND_CM_S = 35000.0   # cm/s at ~37°C (vocal tract temperature)
MIN_SEGMENT_SAMPLES = 2048      # ~0.09s at 22050 Hz — absolute minimum for pyin


# ─── Utility ─────────────────────────────────────────────────
def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + np.exp(-float(x)))


# ─── F0 Extraction ───────────────────────────────────────────
def _extract_f0(y: np.ndarray, sr: int) -> tuple[float | None, float | None, int]:
    """
    Returns (f0_median_hz, f0_std_hz, voiced_frame_count).
    Uses librosa.pyin for robust pitch tracking.
    """
    if len(y) < MIN_SEGMENT_SAMPLES:
        return None, None, 0

    frame_length = min(2048, len(y))
    hop_length   = frame_length // 4

    try:
        f0, voiced_flag, _ = librosa.pyin(
            y,
            fmin=librosa.note_to_hz('C2'),   # 65 Hz — well below male floor
            fmax=librosa.note_to_hz('C6'),   # 1047 Hz — well above female ceiling
            sr=sr,
            frame_length=frame_length,
            hop_length=hop_length,
        )
    except Exception:
        return None, None, 0

    # Keep only voiced frames in the plausible vocal range
    voiced_f0 = f0[voiced_flag & (f0 > 60) & (f0 < 500)]
    if len(voiced_f0) < 3:
        return None, None, 0

    return (
        float(round(float(np.median(voiced_f0)))),
        float(round(float(np.std(voiced_f0)))),
        int(len(voiced_f0)),
    )


# ─── Formant Extraction via LPC ──────────────────────────────
def _extract_formants(y: np.ndarray, sr: int) -> tuple[int | None, int | None, int | None]:
    """
    Returns (F1, F2, F3) in Hz by multi-frame LPC analysis.
    Downsamples to 11025 Hz to limit analysis to ~5500 Hz ceiling.
    """
    TARGET_SR = 11025
    FRAME_MS  = 25   # ms per analysis window
    HOP_MS    = 10   # ms hop
    LPC_ORDER = int(TARGET_SR / 1000) + 2   # 13

    frame_len = int(FRAME_MS * TARGET_SR / 1000)
    hop_len   = int(HOP_MS   * TARGET_SR / 1000)

    # Resample
    try:
        y_down = librosa.resample(y, orig_sr=sr, target_sr=TARGET_SR)
    except Exception:
        return None, None, None

    if len(y_down) < frame_len:
        return None, None, None

    # High-pass filter at 80 Hz (remove DC & low-freq rumble)
    sos = butter(4, 80.0 / (TARGET_SR / 2.0), btype='high', output='sos')
    y_hp = sosfilt(sos, y_down).astype(np.float32)

    # Pre-emphasis
    y_pe = np.append(y_hp[0], y_hp[1:] - 0.97 * y_hp[:-1])

    window = np.hamming(frame_len)
    frames_f1, frames_f2, frames_f3 = [], [], []

    for start in range(0, len(y_pe) - frame_len, hop_len):
        frame = y_pe[start : start + frame_len] * window

        # Skip silent frames
        if np.max(np.abs(frame)) < 1e-5:
            continue

        try:
            a = _lpc(frame, LPC_ORDER)
        except Exception:
            continue

        # Roots of the LPC polynomial → formant frequencies
        roots = np.roots(a)
        roots = roots[np.imag(roots) >= 0]           # upper half-plane only
        angles = np.angle(roots)
        freqs  = np.sort(angles * TARGET_SR / (2.0 * np.pi))
        freqs  = freqs[(freqs > 50)]                 # discard sub-50 Hz

        # Find F1 / F2 / F3 in their canonical ranges
        f1 = next((f for f in freqs if 200 < f < 1000), None)
        f2 = next((f for f in freqs if 700  < f < 3000
                   and (f1 is None or f > f1 + 150)), None)
        f3 = next((f for f in freqs if 1500 < f < 4000
                   and (f2 is None or f > f2 + 150)), None)

        if f1: frames_f1.append(f1)
        if f2: frames_f2.append(f2)
        if f3: frames_f3.append(f3)

    f1 = int(round(float(np.median(frames_f1)))) if len(frames_f1) >= 3 else None
    f2 = int(round(float(np.median(frames_f2)))) if len(frames_f2) >= 3 else None
    f3 = int(round(float(np.median(frames_f3)))) if len(frames_f3) >= 3 else None

    return f1, f2, f3


# ─── Spectral Tilt ───────────────────────────────────────────
def _compute_spectral_tilt(y: np.ndarray, sr: int) -> float | None:
    """
    Spectral tilt = slope of log-power spectrum vs. log-frequency (dB/octave).
    Negative = more low-frequency energy (masculine); less negative = more feminine.
    """
    n_fft = min(2048, len(y) // 2 * 2)
    if n_fft < 128:
        return None

    try:
        S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=n_fft // 4)) ** 2
    except Exception:
        return None

    S_mean = np.mean(S, axis=1)
    freqs  = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

    mask = (freqs > 100) & (freqs < 8000)
    log_freq  = np.log2(freqs[mask])
    log_power = 10.0 * np.log10(S_mean[mask] + 1e-12)

    if len(log_freq) < 5:
        return None

    slope = float(np.polyfit(log_freq, log_power, 1)[0])
    return round(slope, 2)


# ─── VTL / Resonance ─────────────────────────────────────────
def _compute_resonance(f3_hz: int | None, f0_median: float | None) -> float:
    """
    Estimates vocal tract length from F3 (quarter-wave formula) and maps
    it to a 0–100% resonance score (100 = most feminine).
    Falls back to F0-based estimate if F3 is unavailable.
    """
    f0 = f0_median or 150.0

    if f3_hz and f3_hz > 200:
        # F3 = 5c / (4L)  →  L = 5c / (4 * F3)
        vtl_cm = (5.0 * SPEED_OF_SOUND_CM_S) / (4.0 * f3_hz)
        # Typical VTL: female ~13–15 cm, male ~17–19 cm
        vtl_score = 1.0 - (vtl_cm - 13.0) / (19.0 - 13.0)
        vtl_score = max(0.0, min(1.0, vtl_score))
    else:
        vtl_score = None

    # F0-based prior
    pitch_prior = max(0.0, min(1.0, (f0 - 85.0) / (255.0 - 85.0)))

    if vtl_score is not None:
        blended = 0.65 * vtl_score + 0.35 * pitch_prior
    else:
        blended = pitch_prior

    return round(blended * 100.0, 1)


# ─── Individual Scores ───────────────────────────────────────
def _score_pitch(f0_hz: float) -> float:
    """Sigmoid centered at 165 Hz (transition zone between male/female ranges)."""
    return round(_sigmoid((f0_hz - 165.0) / 35.0) * 100.0, 1)


def _score_formants(f2_hz: int | None, f3_hz: int | None) -> float:
    """
    F2 is the primary femininity indicator (higher = more feminine).
    Blend with F3 when available.
    """
    if f2_hz is None:
        return 50.0
    f2_score = _sigmoid((f2_hz - 1400.0) / 150.0) * 100.0
    if f3_hz:
        f3_score = _sigmoid((f3_hz - 2600.0) / 200.0) * 100.0
        return round(0.6 * f2_score + 0.4 * f3_score, 1)
    return round(f2_score, 1)


def _score_spectral_tilt(tilt: float | None) -> float:
    """
    Maps dB/octave slope to 0–100 score.
    -2 dB/oct → ~85 (feminine), -4 → ~50 (neutral), -7 → ~15 (masculine).
    """
    if tilt is None:
        return 50.0
    return round(_sigmoid((tilt + 4.0) / 1.2) * 100.0, 1)


def _composite_score(
    pitch_score:    float,
    formant_score:  float,
    resonance_score: float,
    tilt_score:     float,
) -> float:
    """
    Weighted composite with dynamic rebalancing when pitch and formant disagree.
    Default weights: pitch 45%, formant 30%, resonance 15%, tilt 10%.
    """
    w_p, w_f, w_r, w_t = 0.45, 0.30, 0.15, 0.10

    # Dynamic rebalancing: if pitch and formant strongly disagree, equalise them
    if abs(pitch_score - formant_score) > 30:
        w_p, w_f, w_r, w_t = 0.35, 0.35, 0.20, 0.10

    score = w_p * pitch_score + w_f * formant_score + w_r * resonance_score + w_t * tilt_score
    return round(score, 1)


# ─── Public API ──────────────────────────────────────────────
def analyze_segment(y: np.ndarray, sr: int) -> dict | None:
    """
    Full acoustic analysis of a single audio clip.

    Parameters
    ----------
    y  : float32 numpy array, mono, any sample rate
    sr : sample rate of y

    Returns
    -------
    dict with all acoustic fields, or None if the clip is too short / silent.
    """
    if y is None or len(y) < MIN_SEGMENT_SAMPLES:
        return None

    # Normalise amplitude
    peak = np.max(np.abs(y))
    if peak < 1e-6:
        return None   # completely silent
    y = y / peak

    # ── F0 ──────────────────────────────────────────────────
    f0_median, f0_std, voiced_frames = _extract_f0(y, sr)
    if f0_median is None:
        return None   # no voiced frames → not speech

    # ── Formants ────────────────────────────────────────────
    f1, f2, f3 = _extract_formants(y, sr)

    # ── Spectral Tilt ────────────────────────────────────────
    tilt = _compute_spectral_tilt(y, sr)

    # ── Resonance ────────────────────────────────────────────
    resonance = _compute_resonance(f3, f0_median)

    # ── Scores ───────────────────────────────────────────────
    pitch_score    = _score_pitch(f0_median)
    formant_score  = _score_formants(f2, f3)
    tilt_score     = _score_spectral_tilt(tilt)
    resonance_score = resonance   # already 0–100

    gender_score = _composite_score(
        pitch_score, formant_score, resonance_score, tilt_score
    )

    return {
        "f0_median_hz":       f0_median,
        "f0_std_hz":          f0_std,
        "f1_hz":              f1,
        "f2_hz":              f2,
        "f3_hz":              f3,
        "spectral_tilt_db_oct": tilt,
        "resonance_pct":      resonance,
        "gender_score":       gender_score,
        "pitch_score":        pitch_score,
        "formant_score":      formant_score,
        "resonance_score":    resonance_score,
        "tilt_score":         tilt_score,
        "voiced_frames":      voiced_frames,
    }
