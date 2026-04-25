/**
 * diverging.js — Soft pink/blue diverging palette for gender-direction visuals.
 *
 * Design rationale (docs/COLOR_SCHEME.md):
 *   - The app's other UI (Engine A male/female tiles) already uses pink/blue.
 *     A neutral palette (Cividis, RdBu) broke visual consistency.
 *   - Saturation is kept muted to avoid "gender-toy" connotation.
 *   - Neutral midpoint is warm off-white (not pure white) so the color band
 *     reads as a continuous ribbon rather than bleaching out in the middle.
 *
 * CVD safety: verified by `_verifyCVD()` — every adjacent pair has
 * ΔE₇₆ > 3 under Viénot-Brettel-Mollon protanopia and deuteranopia
 * projections.  See docs/COLOR_SCHEME.md for the full matrix.
 *
 * Scientific anchors:
 *   - Resonance neutral   = 0.5   (construction: reference-corpus mean)
 *   - Resonance threshold = 0.587 (10-fold CV on AISHELL-3, acc=0.900)
 *   - Pitch neutral       = 165 Hz (male upper / female lower boundary)
 *   - Pitch saturation    = [100, 230] Hz
 */

// 9 stops.  Hand-tuned: each adjacent pair was checked against Viénot CVD
// projections and iterated until the minimum cross-CVD ΔE₇₆ passes > 3.
// Anchors (#5B8FB0, #7BA7C9, #EDE8E4, #E8A5BD) are from the design brief;
// intermediate stops were picked to balance perceived lightness progression.
const STOPS = [
	[58, 107, 141], // #3A6B8D  deep cool-blue     (strong masc direction)
	[91, 143, 176], // #5B8FB0  anchor
	[139, 176, 201], // #8BB0C9  mid blue
	[189, 211, 224], // #BDD3E0  pale blue
	[237, 232, 228], // #EDE8E4  warm neutral       (construction center)
	[230, 200, 210], // #E6C8D2  pale pink
	[217, 161, 182], // #D9A1B6  mid pink
	[188, 115, 143], // #BC738F  deep dusty rose
	[150, 75, 105], // #964B69  deep cool-pink    (strong fem direction)
];

function _interp(t) {
	const x = Math.max(0, Math.min(1, t));
	const scaled = x * (STOPS.length - 1);
	const lo = Math.floor(scaled);
	const hi = Math.min(lo + 1, STOPS.length - 1);
	const frac = scaled - lo;
	const r = Math.round(STOPS[lo][0] + (STOPS[hi][0] - STOPS[lo][0]) * frac);
	const g = Math.round(STOPS[lo][1] + (STOPS[hi][1] - STOPS[lo][1]) * frac);
	const b = Math.round(STOPS[lo][2] + (STOPS[hi][2] - STOPS[lo][2]) * frac);
	return `rgb(${r},${g},${b})`;
}

/**
 * Push t away from the bleached neutral midpoint via a smooth, monotonic
 * power curve that passes through (0,0), (0.5,0.5), (1,1).  Slope is steep
 * near the center (so values just off neutral land deep into the saturated
 * blue/pink stops instead of the warm-white midpoint) and gentle near the
 * extremes (so subtle differences at high pitch / resonance still resolve).
 *
 * Power 0.4 was picked empirically: at t=0.55 the output is ~0.66 (clearly
 * pink), at t=0.45 it's ~0.34 (clearly blue), but exact t=0.5 still maps
 * through 0.5 so the function stays continuous (no hard jump like the old
 * piecewise-linear "skip the middle" version).  Heatmap fills don't pass
 * `stretch:true` so they keep the literal palette mapping for honest
 * per-phone resonance reading; only line strokes use this curve.
 */
function _stretchT(t) {
	const x = Math.max(0, Math.min(1, t));
	const d = (x - 0.5) * 2; // signed distance from neutral, in [-1, 1]
	const stretched = Math.sign(d) * Math.pow(Math.abs(d), 0.4);
	return 0.5 + stretched * 0.5;
}

/**
 * Map a resonance value (0-1) to a CSS color.  Neutral = 0.5.
 * Null / non-finite → null (caller should use the hatch fallback).
 *
 * `stretch: true` skips the palette midpoint stops so the returned color is
 * always a saturated blue or pink — useful for line strokes on light
 * backgrounds where the warm-white mid is invisible.  Heatmap fills should
 * leave it off so the full palette range is used.
 */
export function divergingResonance(value, { stretch = false } = {}) {
	if (value == null || !Number.isFinite(value)) return null;
	let t = Math.max(0, Math.min(1, value));
	if (stretch) t = _stretchT(t);
	return _interp(t);
}

/**
 * Map a pitch (Hz) to a CSS color.
 * Neutral = 165 Hz, saturates at 100 Hz (deep blue) and 230 Hz (deep pink).
 * See `divergingResonance` for the `stretch` option.
 */
export function divergingPitch(hz, { neutral = 165, min = 100, max = 230, stretch = false } = {}) {
	if (hz == null || !Number.isFinite(hz) || hz <= 0) return null;
	let t;
	if (hz <= neutral) {
		t = 0.5 * Math.max(0, (hz - min) / (neutral - min));
	} else {
		t = 0.5 + 0.5 * Math.min(1, (hz - neutral) / (max - neutral));
	}
	if (stretch) t = _stretchT(t);
	return _interp(t);
}

/** Raw hex stops for CSS gradient backgrounds (e.g. legend bar). */
export const DIVERGING_HEX = STOPS.map(
	([r, g, b]) =>
		"#" +
		[r, g, b]
			.map((v) => v.toString(16).padStart(2, "0"))
			.join("")
			.toUpperCase(),
);

/** Empirically-derived thresholds from upstream training (AISHELL-3, zh). */
export const THRESHOLDS = {
	resonance: 0.587, // 10-fold CV threshold, accuracy 0.900
	pitchNeutralHz: 165, // male upper / female lower boundary
	pitchFemHz: 180, // voice training target (Gelfer & Mikos 2005)
};

// ─── CVD verification (math, no browser) ──────────────────────────
// Viénot-Brettel-Mollon 1999 dichromat simulation + CIE76 ΔE.

function _srgbToLinear(c) {
	const u = c / 255;
	return u <= 0.04045 ? u / 12.92 : Math.pow((u + 0.055) / 1.055, 2.4);
}

function _rgbToLms([r, g, b]) {
	// Hunt-Pointer-Estévez matrix (Viénot 1999)
	return [
		17.8824 * r + 43.5161 * g + 4.11935 * b,
		3.45565 * r + 27.1554 * g + 3.86714 * b,
		0.0299566 * r + 0.184309 * g + 1.46709 * b,
	];
}

function _lmsToLinearRgb([L, M, S]) {
	return [
		0.0809444479 * L - 0.130504409 * M + 0.116721066 * S,
		-0.0102485335 * L + 0.0540193266 * M - 0.113614708 * S,
		-0.000365296938 * L - 0.00412161469 * M + 0.693511405 * S,
	];
}

function _simulateLinearRgb(linRgb, kind) {
	if (kind === "normal") return linRgb;
	const [L, M, S] = _rgbToLms(linRgb);
	let Lp = L,
		Mp = M,
		Sp = S;
	if (kind === "prot") Lp = 2.02344 * M - 2.52581 * S;
	if (kind === "deut") Mp = 0.494207 * L + 1.24827 * S;
	return _lmsToLinearRgb([Lp, Mp, Sp]).map((v) => Math.max(0, Math.min(1, v)));
}

function _linearRgbToLab([r, g, b]) {
	// Linear RGB → XYZ (sRGB matrix, D65)
	const X = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b;
	const Y = 0.2126729 * r + 0.7151522 * g + 0.072175 * b;
	const Z = 0.0193339 * r + 0.119192 * g + 0.9503041 * b;
	// XYZ → Lab
	const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
	const fx = f(X / 0.95047);
	const fy = f(Y / 1.0);
	const fz = f(Z / 1.08883);
	return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

function _deltaE76(a, b) {
	const dL = a[0] - b[0],
		da = a[1] - b[1],
		db = a[2] - b[2];
	return Math.sqrt(dL * dL + da * da + db * db);
}

/**
 * Verify CVD safety of the palette.
 * Returns { rows, minCvd, pass } — rows has adjacent ΔE under normal /
 * deuteranopia / protanopia projections.  Pass iff every adjacent cross-CVD
 * ΔE > 3 (well above the ~2.3 JND for trained observers).
 */
export function _verifyCVD() {
	const linearRgbs = STOPS.map(([r, g, b]) => [_srgbToLinear(r), _srgbToLinear(g), _srgbToLinear(b)]);
	const kinds = ["normal", "deut", "prot"];
	const labs = {};
	for (const k of kinds) {
		labs[k] = linearRgbs.map((rgb) => _linearRgbToLab(_simulateLinearRgb(rgb, k)));
	}
	const rows = [];
	for (let i = 0; i < STOPS.length - 1; i++) {
		rows.push({
			pair: `${DIVERGING_HEX[i]} → ${DIVERGING_HEX[i + 1]}`,
			normal: _deltaE76(labs.normal[i], labs.normal[i + 1]),
			deut: _deltaE76(labs.deut[i], labs.deut[i + 1]),
			prot: _deltaE76(labs.prot[i], labs.prot[i + 1]),
		});
	}
	const cvdValues = rows.flatMap((r) => [r.deut, r.prot]);
	const minCvd = Math.min(...cvdValues);
	// End-to-end (stop 0 vs stop 8) — sanity: palette must be very distinguishable overall.
	const endToEnd = {
		normal: _deltaE76(labs.normal[0], labs.normal[STOPS.length - 1]),
		deut: _deltaE76(labs.deut[0], labs.deut[STOPS.length - 1]),
		prot: _deltaE76(labs.prot[0], labs.prot[STOPS.length - 1]),
	};
	return { rows, minCvd, endToEnd, pass: minCvd > 3 };
}
