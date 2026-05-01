import { t } from "./modules/i18n.js";

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
// `zh` 字段保留作兼容名，但实际返回当前语言下的显示文本（i18n 动态化）。
// 旧调用点直接读 `meta.zh` 也能拿到切换后的值。
const _LABEL_KEYS = {
	male: "label.male",
	female: "label.female",
	music: "label.music",
	noise: "label.noise",
	noEnergy: "label.silence",
};
const _LABEL_VARS = {
	male: "var(--male)",
	female: "var(--female)",
	music: "var(--music)",
	noise: "var(--noise)",
	noEnergy: "var(--noenergy)",
};
export const LABEL_META = new Proxy(_LABEL_KEYS, {
	get(_tgt, key) {
		if (!(key in _LABEL_KEYS)) return undefined;
		return {
			get zh() {
				return t(_LABEL_KEYS[key]);
			},
			cssVar: _LABEL_VARS[key],
		};
	},
	has(_tgt, key) {
		return key in _LABEL_KEYS;
	},
	ownKeys() {
		return Object.keys(_LABEL_KEYS);
	},
	getOwnPropertyDescriptor(_tgt, key) {
		if (!(key in _LABEL_KEYS)) return undefined;
		return { enumerable: true, configurable: true, value: this.get(null, key) };
	},
});

// ─── Resolve CSS custom property to hex/rgb string ───────────
export function resolveCSSVar(varName) {
	return getComputedStyle(document.documentElement)
		.getPropertyValue(varName.replace("var(", "").replace(")", "").trim())
		.trim();
}

// ─── Tier → color (5 discrete levels, 1=masculine → 5=feminine) ──
const _TIER_COLORS = [
	"rgba(37,99,235,0.9)", // 1: Deep Blue  — typical masculine
	"rgba(96,165,250,0.9)", // 2: Light Blue — masculine
	"rgba(139,92,246,0.9)", // 3: Purple     — neutral / androgynous
	"rgba(244,114,182,0.9)", // 4: Light Pink  — feminine
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

// ─── Certainty tag for a voiced segment ──────────────────────
// 5-tier tone tendency mapper. Two thresholds on the C1 margin (Engine A
// T=2.0 calibrated):
//   margin >= _toneThreshold (0.78)      → leans_*       (confident)
//   margin >= _weakToneThreshold (0.50)  → weakly_*      (directional but soft)
//   else                                  → not_clearly_leaning
// Both thresholds are owned by the backend (advice_v2.TONE_THRESHOLD,
// WEAK_TONE_THRESHOLD) and pushed in via /api/config; setters are wired from
// main.js after the config fetch. Defaults below are a fallback for the brief
// window before /api/config returns and for tests / offline use — they must
// mirror the backend constants.
// See docs/plans/v2_redesign_measurement.md §5.
let _toneThreshold = 0.78;
let _weakToneThreshold = 0.5;
export function setToneThreshold(v) {
	if (typeof v === "number" && v > 0 && v < 1) _toneThreshold = v;
}
export function setWeakToneThreshold(v) {
	if (typeof v === "number" && v > 0 && v < 1) _weakToneThreshold = v;
}
export function certaintTag(seg) {
	if (!seg || (seg.label !== "female" && seg.label !== "male")) return "";
	const margin = seg.confidence ?? 0;
	const fem = seg.label === "female";
	if (margin >= _toneThreshold)
		return t(fem ? "advice.tone.leans_feminine" : "advice.tone.leans_masculine");
	if (margin >= _weakToneThreshold)
		return t(fem ? "advice.tone.weakly_feminine" : "advice.tone.weakly_masculine");
	return t("advice.tone.not_clearly_leaning");
}
