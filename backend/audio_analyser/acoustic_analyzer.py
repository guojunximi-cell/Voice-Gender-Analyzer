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

import librosa
import numpy as np
from scipy.linalg import solve_toeplitz
from scipy.signal import butter, sosfilt


def _lpc(frame: np.ndarray, order: int) -> np.ndarray:
    """Autocorrelation-method LPC (replaces scipy.signal.lpc removed in 1.16+)."""
    n = len(frame)
    r = np.correlate(frame, frame, mode="full")[n - 1 : n + order]
    a = solve_toeplitz(r[:order], -r[1 : order + 1])
    return np.concatenate([[1.0], a])


# ─── Constants ────────────────────────────────────────────────
SPEED_OF_SOUND_CM_S = 35000.0  # cm/s at ~37°C (vocal tract temperature)
MIN_SEGMENT_SAMPLES = 2048  # ~0.09s at 22050 Hz — absolute minimum for pyin


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
    hop_length = frame_length // 4

    try:
        f0, voiced_flag, _ = librosa.pyin(
            y,
            fmin=librosa.note_to_hz("C2"),  # 65 Hz — well below male floor # type: ignore
            fmax=librosa.note_to_hz("C6"),  # 1047 Hz — well above female ceiling # type: ignore
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
    FRAME_MS = 25  # ms per analysis window
    HOP_MS = 10  # ms hop
    LPC_ORDER = int(TARGET_SR / 1000) + 2  # 13

    frame_len = int(FRAME_MS * TARGET_SR / 1000)
    hop_len = int(HOP_MS * TARGET_SR / 1000)

    # Resample
    try:
        y_down = librosa.resample(y, orig_sr=sr, target_sr=TARGET_SR)
    except Exception:
        return None, None, None

    if len(y_down) < frame_len:
        return None, None, None

    # High-pass filter at 80 Hz (remove DC & low-freq rumble)
    sos = butter(4, 80.0 / (TARGET_SR / 2.0), btype="high", output="sos")
    y_hp = sosfilt(sos, y_down).astype(np.float32) # type: ignore

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
        roots = roots[np.imag(roots) >= 0]  # upper half-plane only
        angles = np.angle(roots)
        freqs = np.sort(angles * TARGET_SR / (2.0 * np.pi))
        freqs = freqs[(freqs > 50)]  # discard sub-50 Hz

        # Find F1 / F2 / F3 in their canonical ranges
        f1 = next((f for f in freqs if 200 < f < 1000), None)
        f2 = next((f for f in freqs if 700 < f < 3000 and (f1 is None or f > f1 + 150)), None)
        f3 = next((f for f in freqs if 1500 < f < 4000 and (f2 is None or f > f2 + 150)), None)

        if f1:
            frames_f1.append(f1)
        if f2:
            frames_f2.append(f2)
        if f3:
            frames_f3.append(f3)

    f1 = int(round(float(np.median(frames_f1)))) if len(frames_f1) >= 3 else None
    f2 = int(round(float(np.median(frames_f2)))) if len(frames_f2) >= 3 else None
    f3 = int(round(float(np.median(frames_f3)))) if len(frames_f3) >= 2 else None

    return f1, f2, f3


# ─── Spectral Tilt (dB/octave) ───────────────────────────────
def _compute_spectral_tilt(y: np.ndarray, sr: int) -> float | None:
    """
    Spectral tilt = slope of log-power spectrum vs. log-frequency (dB/octave).
    Kept for backward compatibility; not used in tier scoring.
    """
    n_fft = min(2048, len(y) // 2 * 2)
    if n_fft < 128:
        return None

    try:
        S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=n_fft // 4)) ** 2
    except Exception:
        return None

    S_mean = np.mean(S, axis=1)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

    mask = (freqs > 100) & (freqs < 8000)
    log_freq = np.log2(freqs[mask])
    log_power = 10.0 * np.log10(S_mean[mask] + 1e-12)

    if len(log_freq) < 5:
        return None

    slope = float(np.polyfit(log_freq, log_power, 1)[0])
    return round(slope, 2)


# ─── H1–H2 Harmonic Difference ───────────────────────────────
def _compute_h1_h2(y: np.ndarray, sr: int, f0_hz: float) -> float | None:
    """
    H1–H2: amplitude difference (dB) between the first and second harmonics.
    Higher values → more breathiness / feminine vocal quality.
    Uses peak search within ±15 Hz of each harmonic target.
    """
    n_fft = 4096  # fixed size for consistent frequency resolution (~5.4 Hz/bin at 22050 Hz)

    try:
        spectrum = np.abs(np.fft.rfft(y, n=n_fft)) ** 2
        freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)

        window_hz = max(20.0, f0_hz * 0.25)  # proportional to F0; at least 20 Hz

        def _peak_amp(target_hz: float) -> float | None:
            mask = np.abs(freqs - target_hz) < window_hz
            if not np.any(mask):
                return None
            return float(np.sqrt(np.max(spectrum[mask])))

        h1 = _peak_amp(f0_hz)
        h2 = _peak_amp(2.0 * f0_hz)

        if h1 is None or h2 is None or h1 < 1e-10 or h2 < 1e-10:
            return None

        return round(20.0 * np.log10(h1 / h2), 2)
    except Exception:
        return None


# ─── VTL / Resonance ─────────────────────────────────────────
def _compute_vtl_cm(f3_hz: int | None, f2_hz: int | None = None) -> float | None:
    """
    Estimates vocal tract length via quarter-wave formula.
    Primary:  F3-based  L = 5c / (4·F3)   (most accurate)
    Fallback: F2-based  L = 3c / (4·F2)   (when F3 unavailable)
    Typical range: female ~13–15 cm, male ~17–19 cm.
    """
    if f3_hz and f3_hz > 200:
        return round((5.0 * SPEED_OF_SOUND_CM_S) / (4.0 * f3_hz), 2)
    if f2_hz and f2_hz > 200:
        vtl = (3.0 * SPEED_OF_SOUND_CM_S) / (4.0 * f2_hz)
        return round(vtl, 2) if 10.0 < vtl < 25.0 else None
    return None


def _compute_resonance(f3_hz: int | None, f0_median: float | None) -> float:
    """
    Maps VTL (from F3) to a 0–100% resonance score (100 = most feminine).
    Falls back to F0-based estimate if F3 is unavailable.
    """
    f0 = f0_median or 150.0
    vtl_cm = _compute_vtl_cm(f3_hz)

    if vtl_cm is not None:
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


# ─── Individual Scores (0–100, used for composite gender_score) ──
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


def _score_spectral_tilt(h1_h2_db: float | None) -> float:
    """
    Maps H1–H2 difference (dB) to 0–100 score.
    Center at ~5.5 dB (neutral); <1 dB → masculine, >11 dB → feminine.
    """
    if h1_h2_db is None:
        return 50.0
    return round(_sigmoid((h1_h2_db - 5.5) / 3.0) * 100.0, 1)


# ─── 5-Tier Color Classification (1=masculine → 5=feminine) ──
def _tier_pitch(f0_hz: float) -> int:
    """Map F0 (Hz) to 5-tier gender color class."""
    if f0_hz < 120:
        return 1
    if f0_hz < 155:
        return 2
    if f0_hz < 185:
        return 3
    if f0_hz < 225:
        return 4
    return 5


def _tier_formants(f1: int | None, f2: int | None, f3: int | None) -> int:
    """
    Weighted formant tier: F2 primary (0.5), F1 and F3 secondary (0.25 each).
    Based on v2.0 ranges: F2 boundaries at 1400/1600/1900/2200 Hz.
    """

    def _f1t(v: int) -> int:
        if v < 550:
            return 1
        if v < 620:
            return 2
        if v < 670:
            return 3
        if v < 750:
            return 4
        return 5

    def _f2t(v: int) -> int:
        if v < 1400:
            return 1
        if v < 1600:
            return 2
        if v < 1900:
            return 3
        if v < 2200:
            return 4
        return 5

    def _f3t(v: int) -> int:
        if v < 2500:
            return 1
        if v < 2700:
            return 2
        if v < 2950:
            return 3
        if v < 3200:
            return 4
        return 5

    total, weight = 0.0, 0.0
    if f2 is not None:
        total += _f2t(f2) * 0.50
        weight += 0.50
    if f1 is not None:
        total += _f1t(f1) * 0.25
        weight += 0.25
    if f3 is not None:
        total += _f3t(f3) * 0.25
        weight += 0.25
    if weight == 0.0:
        return 3
    return max(1, min(5, round(total / weight)))


def _tier_vtl(vtl_cm: float) -> int:
    """Map VTL (cm) to 5-tier gender color class."""
    if vtl_cm > 17.5:
        return 1
    if vtl_cm > 16.5:
        return 2
    if vtl_cm > 15.5:
        return 3
    if vtl_cm > 14.5:
        return 4
    return 5


def _tier_h1_h2(h1_h2_db: float) -> int:
    """Map H1–H2 difference (dB) to 5-tier gender color class."""
    if h1_h2_db < 1:
        return 1
    if h1_h2_db < 4:
        return 2
    if h1_h2_db < 7:
        return 3
    if h1_h2_db < 11:
        return 4
    return 5


def _composite_score(
    pitch_score: float,
    formant_score: float,
    resonance_score: float,
    tilt_score: float,
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
        return None  # completely silent
    y = y / peak

    # ── F0 ──────────────────────────────────────────────────
    f0_median, f0_std, voiced_frames = _extract_f0(y, sr)
    if f0_median is None:
        return None  # no voiced frames → not speech

    # ── Formants ────────────────────────────────────────────
    f1, f2, f3 = _extract_formants(y, sr)

    # ── Spectral Tilt (dB/oct, kept for reference) ───────────
    tilt = _compute_spectral_tilt(y, sr)

    # ── H1–H2 Harmonic Difference ────────────────────────────
    h1_h2 = _compute_h1_h2(y, sr, f0_median)

    # ── Resonance / VTL ──────────────────────────────────────
    vtl_cm = _compute_vtl_cm(f3, f2)
    resonance = _compute_resonance(f3, f0_median)

    # ── Scores (0–100, used for composite gender_score) ──────
    pitch_score = _score_pitch(f0_median)
    formant_score = _score_formants(f2, f3)
    tilt_score = _score_spectral_tilt(h1_h2)  # now H1–H2 based
    resonance_score = resonance  # already 0–100

    gender_score = _composite_score(pitch_score, formant_score, resonance_score, tilt_score)

    # ── 5-Tier Color Classes ──────────────────────────────────
    pitch_tier = _tier_pitch(f0_median)
    formant_tier = _tier_formants(f1, f2, f3)
    vtl_tier = _tier_vtl(vtl_cm) if vtl_cm is not None else 3
    tilt_tier = _tier_h1_h2(h1_h2) if h1_h2 is not None else 3

    return {
        "f0_median_hz": f0_median,
        "f0_std_hz": f0_std,
        "f1_hz": f1,
        "f2_hz": f2,
        "f3_hz": f3,
        "spectral_tilt_db_oct": tilt,
        "h1_h2_db": h1_h2,
        "vtl_cm": vtl_cm,
        "resonance_pct": resonance,
        "gender_score": gender_score,
        "pitch_score": pitch_score,
        "formant_score": formant_score,
        "resonance_score": resonance_score,
        "tilt_score": tilt_score,
        "pitch_tier": pitch_tier,
        "formant_tier": formant_tier,
        "vtl_tier": vtl_tier,
        "tilt_tier": tilt_tier,
        "voiced_frames": voiced_frames,
    }
