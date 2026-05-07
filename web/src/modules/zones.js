/**
 * zones.js — Single source of truth for the three-zone classification thresholds
 * shared by Distribution (classify.js), Pitch Range bar (CSS widths in main.css),
 * and Resonance scale bar (resonance-panel.js).
 *
 * Pitch zones (Hz):  male < 145 ≤ neutral ≤ 185 < female
 * Resonance zones:   male < p25 ≤ neutral ≤ p75 < female  (p25/p75 per-language)
 *
 * Phones at the edges (== boundary) are placed in the neutral zone — keeps
 * `<` and `>` on the male/female sides so the closed neutral interval matches
 * the inclusive Hz labels in i18n ("145–185 Hz", "p25–p75").
 *
 * Confidence: linear ramp inside each zone, hitting 1.0 at the zone center
 * (or far-edge for male/female open intervals) and 0.0 at the boundary.
 * This keeps the M↔neutral and neutral↔F transitions continuous.
 */

const PITCH_BAND_LO_HZ = 80; // bar's lower visual bound — confidence saturates here for male
const PITCH_BAND_HI_HZ = 250; // upper visual bound — confidence saturates here for female

export const PITCH_ZONES_HZ = { male: 145, female: 185 };

const PITCH_NEUTRAL_CENTER = (PITCH_ZONES_HZ.male + PITCH_ZONES_HZ.female) / 2; // 165
const PITCH_NEUTRAL_HALF = (PITCH_ZONES_HZ.female - PITCH_ZONES_HZ.male) / 2; // 20

// Mirror voiceya/services/audio_analyser/resonance_calibration.py classify_zone:
//   0..p25 = cis-male, p25..p75 = androgynous (mid_neutral), p75..1 = cis-female.
export const RESONANCE_ZONES = {
	"zh-CN": { p25: 0.612, p75: 0.842 },
	"en-US": { p25: 0.458, p75: 0.682 },
	"fr-FR": { p25: 0.547, p75: 0.752 },
};

export function pitchZone(hz) {
	if (hz == null || !Number.isFinite(hz) || hz <= 0) return null;
	if (hz < PITCH_ZONES_HZ.male) return "male";
	if (hz > PITCH_ZONES_HZ.female) return "female";
	return "neutral";
}

export function pitchConfidence(hz, label) {
	if (hz == null || !Number.isFinite(hz)) return 0;
	if (label === "male") {
		// Saturates to 1 at PITCH_BAND_LO_HZ; 0 at the male/neutral boundary.
		const span = PITCH_ZONES_HZ.male - PITCH_BAND_LO_HZ;
		return span > 0 ? Math.min(1, Math.max(0, (PITCH_ZONES_HZ.male - hz) / span)) : 0;
	}
	if (label === "female") {
		const span = PITCH_BAND_HI_HZ - PITCH_ZONES_HZ.female;
		return span > 0 ? Math.min(1, Math.max(0, (hz - PITCH_ZONES_HZ.female) / span)) : 0;
	}
	if (label === "neutral") {
		return Math.max(0, 1 - Math.abs(hz - PITCH_NEUTRAL_CENTER) / PITCH_NEUTRAL_HALF);
	}
	return 0;
}

function _zonesFor(lang) {
	return RESONANCE_ZONES[lang] || RESONANCE_ZONES["zh-CN"];
}

export function resonanceZone(value, lang) {
	if (value == null || !Number.isFinite(value)) return null;
	const { p25, p75 } = _zonesFor(lang);
	if (value < p25) return "male";
	if (value > p75) return "female";
	return "neutral";
}

export function resonanceConfidence(value, label, lang) {
	if (value == null || !Number.isFinite(value)) return 0;
	const { p25, p75 } = _zonesFor(lang);
	if (label === "male") {
		// Saturates to 1 at value=0; 0 at p25.
		return p25 > 0 ? Math.min(1, Math.max(0, (p25 - value) / p25)) : 0;
	}
	if (label === "female") {
		const span = 1 - p75;
		return span > 0 ? Math.min(1, Math.max(0, (value - p75) / span)) : 0;
	}
	if (label === "neutral") {
		const center = (p25 + p75) / 2;
		const half = (p75 - p25) / 2;
		return half > 0 ? Math.max(0, 1 - Math.abs(value - center) / half) : 0;
	}
	return 0;
}
