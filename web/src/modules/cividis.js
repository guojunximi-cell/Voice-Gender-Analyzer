/**
 * cividis.js — Cividis colormap interpolator for resonance heatmap.
 *
 * Cividis is a perceptually-uniform, CVD-safe colormap with monotonically
 * increasing luminance (blue-to-yellow). Chosen because:
 *   - Safe for protan/deutan color vision deficiency
 *   - No pink/blue gender coding in data channels
 *   - Monotonic luminance = readable in greyscale print
 *
 * 9-stop palette from the plan's binding color spec.
 */

// [R, G, B] tuples, stops at t = 0, 0.125, 0.25, ... 1.0
const STOPS = [
	[0, 34, 78], // #00224E
	[19, 56, 108], // #13386C
	[59, 73, 108], // #3B496C
	[92, 93, 107], // #5C5D6B
	[124, 123, 120], // #7C7B78
	[155, 149, 122], // #9B957A
	[189, 177, 118], // #BDB176
	[223, 205, 90], // #DFCD5A
	[253, 231, 55], // #FDE737
];

/**
 * Map a 0–1 resonance value to a CSS rgb() color string.
 * Values outside [0,1] are clamped.  Returns the hatch-pattern sentinel
 * for null/undefined input.
 */
export function cividis(value) {
	if (value == null) return null;
	const t = Math.max(0, Math.min(1, value));
	const scaled = t * (STOPS.length - 1);
	const lo = Math.floor(scaled);
	const hi = Math.min(lo + 1, STOPS.length - 1);
	const frac = scaled - lo;
	const r = Math.round(STOPS[lo][0] + (STOPS[hi][0] - STOPS[lo][0]) * frac);
	const g = Math.round(STOPS[lo][1] + (STOPS[hi][1] - STOPS[lo][1]) * frac);
	const b = Math.round(STOPS[lo][2] + (STOPS[hi][2] - STOPS[lo][2]) * frac);
	return `rgb(${r},${g},${b})`;
}

/**
 * CSS custom properties for the 9 Cividis stops.
 * Used in tokens.css as fallback reference.
 */
export const CIVIDIS_HEX = [
	"#00224E",
	"#13386C",
	"#3B496C",
	"#5C5D6B",
	"#7C7B78",
	"#9B957A",
	"#BDB176",
	"#DFCD5A",
	"#FDE737",
];
