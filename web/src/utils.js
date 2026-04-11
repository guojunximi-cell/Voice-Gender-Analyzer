// ─── Time formatting ─────────────────────────────────────────
export function fmt(sec) {
	if (sec == null || isNaN(sec)) return "—";
	const m = Math.floor(sec / 60);
	const s = Math.floor(sec % 60);
	return `${m}:${s.toString().padStart(2, "0")}`;
}

// ─── Sigmoid rescale (0–100 → 0–100, stretches middle) ───────
// Used to convert raw gender_score to display X-axis position on scatter plot.
// Score of 50 maps to 50; extremes are compressed; middle region stretched.
export function sigmaRescale(x) {
	const t = (x / 100 - 0.5) * 5.5;
	return (1 / (1 + Math.exp(-t))) * 100;
}

// ─── Session color palette ────────────────────────────────────
const PALETTE = ["#5b8def", "#e07aaa", "#d4b86a", "#7ec8a4", "#c98ef0", "#ef8f5b", "#5bbfef", "#ef5b88"];
let _colorIdx = 0;
export function nextSessionColor() {
	return PALETTE[_colorIdx++ % PALETTE.length];
}

// ─── Label meta ──────────────────────────────────────────────
export const LABEL_META = {
	male: { zh: "男声", cssVar: "var(--male)" },
	female: { zh: "女声", cssVar: "var(--female)" },
	music: { zh: "音乐", cssVar: "var(--music)" },
	noise: { zh: "噪音", cssVar: "var(--noise)" },
	noEnergy: { zh: "静音", cssVar: "var(--noenergy)" },
};

// ─── Resolve CSS custom property to hex/rgb string ───────────
export function resolveCSSVar(varName) {
	return getComputedStyle(document.documentElement)
		.getPropertyValue(varName.replace("var(", "").replace(")", "").trim())
		.trim();
}

// ─── Tier → color (5 discrete levels, 1=masculine → 5=feminine) ──
const _TIER_COLORS = [
	"rgba(37,99,235,0.9)", // 1: Deep Blue  — typical masculine
	"rgba(96,165,250,0.9)", // 2: Light Blue — masculine-leaning
	"rgba(139,92,246,0.9)", // 3: Purple     — neutral / androgynous
	"rgba(244,114,182,0.9)", // 4: Light Pink  — feminine-leaning
	"rgba(219,39,119,0.9)", // 5: Deep Pink   — typical feminine
];
export function tierToColor(tier) {
	return _TIER_COLORS[Math.max(1, Math.min(5, tier || 3)) - 1];
}

// ─── Score → color (Blue→Violet→Rose gradient, score 0–100) ──
export function scoreToColor(score) {
	const t = Math.max(0, Math.min(score, 100)) / 100;
	if (t <= 0.5) {
		const s = t * 2;
		return `rgba(${Math.round(59 + s * 80)},${Math.round(130 - s * 38)},246,0.85)`;
	}
	const s = (t - 0.5) * 2;
	return `rgba(${Math.round(139 + s * 105)},${Math.round(92 - s * 29)},${Math.round(246 - s * 152)},0.85)`;
}

// ─── Certainty tag (Chinese) for a voiced segment ────────────
// Uses only Engine A (inaSpeechSegmenter) confidence + label.
export function certaintTag(seg) {
	if (!seg || (seg.label !== "female" && seg.label !== "male")) return "";
	const c = seg.confidence ?? 0.5;
	const composite = seg.label === "female" ? 50 + c * 50 : 50 - c * 50;

	if (c < 0.4) return "低置信度";
	if (composite >= 42 && composite <= 58) return "临界区间";
	if (c > 0.8) {
		if (seg.label === "female") return composite > 82 ? "明确女声" : "较明显女声";
		return composite < 18 ? "明确男声" : "较明显男声";
	}
	if (seg.label === "female") return composite > 70 ? "偏女性化" : "女性化";
	return composite < 30 ? "偏男性化" : "男性化";
}
