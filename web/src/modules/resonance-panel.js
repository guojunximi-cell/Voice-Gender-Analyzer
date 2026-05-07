/**
 * resonance-panel.js — Right panel: phoneme-aligned resonance breakdown.
 *
 * Source: `summary.advice.resonance_panel` (built by advice_v2._resonance_panel).
 * Renders a Pitch-Range-style scale bar showing the panel-level median
 * resonance positioned within language-aware male / androgynous / female
 * zones, plus a per-vowel list styled like the Distribution panel's
 * stat-cards (label + slim progress bar + percentage). Hidden when Engine C
 * is off, the panel is null (minimal tier), or zone is unknown.
 */

import { getLang, t } from "./i18n.js";

// Language-keyed zone thresholds — mirror voiceya/services/audio_analyser/
// resonance_calibration.py. Two breakpoints split the 0–100% bar into three
// zones: cis-male (0..p25) covers `clearly_below_female` + `leans_male`;
// androgynous (p25..p75) is `mid_neutral`; cis-female (p75..1) covers
// `leans_female` + `at_ceiling`. Boundaries align with the panel's own
// `summary_text_key` so a "Leans cis-male" reading lands in the male band.
// Values from calibration_v1 (commit 482d374, 2026-05-06).
const _ZONE_THRESHOLDS = {
	"zh-CN": { p25: 0.612, p75: 0.842 },
	"en-US": { p25: 0.458, p75: 0.682 },
	"fr-FR": { p25: 0.547, p75: 0.752 },
};

// Five-tier classifier mirroring resonance_calibration.py:classify_zone.
// We recompute median + zone_key client-side from per_vowel so imported
// (pre-fix) sessions reflect the median-of-per-vowel-medians algorithm
// without needing a backend reanalysis. Each entry: [zone_key, upper_bound).
const _ZONE_TIERS = {
	"zh-CN": [
		["clearly_below_female", 0.49],
		["leans_male", 0.612],
		["mid_neutral", 0.842],
		["leans_female", 0.98],
		["at_ceiling", null],
	],
	"en-US": [
		["clearly_below_female", 0.351],
		["leans_male", 0.458],
		["mid_neutral", 0.682],
		["leans_female", 0.98],
		["at_ceiling", null],
	],
	"fr-FR": [
		["clearly_below_female", 0.43],
		["leans_male", 0.547],
		["mid_neutral", 0.752],
		["leans_female", 0.96],
		["at_ceiling", null],
	],
};

function _zonesFor(lang) {
	return _ZONE_THRESHOLDS[lang] || _ZONE_THRESHOLDS["zh-CN"];
}

function _classifyZone(median, lang) {
	if (median == null || !Number.isFinite(median)) return null;
	const tiers = _ZONE_TIERS[lang] || _ZONE_TIERS["zh-CN"];
	for (const [key, upper] of tiers) {
		if (upper == null || median < upper) return key;
	}
	return tiers[tiers.length - 1][0];
}

function _medianOf(arr) {
	if (!arr.length) return null;
	const s = [...arr].sort((a, b) => a - b);
	const m = s.length >> 1;
	return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

let _renderGeneration = 0;

function _hide(id) {
	const el = document.getElementById(id);
	if (el) el.hidden = true;
}

function _setStyle(id, prop, value) {
	const el = document.getElementById(id);
	if (el) el.style[prop] = value;
}

function _vowelDisplay(vowel) {
	// Strip ARPABET stress digits (IY1 → IY) for display. zh phones already
	// have tone marks stripped by the backend aggregator. Keep the slash
	// notation /xx/ as the universal "this is a phoneme" cue.
	return vowel.replace(/[0-9]+$/, "");
}

function _renderMedianBar(median, perVowel, empiricalBands) {
	const block = document.getElementById("resonance-median-block");
	if (!block) return;

	const tag = document.getElementById("resonance-median-tag");
	if (tag) {
		if (median != null) {
			tag.textContent = `${Math.round(median * 100)}%`;
			tag.hidden = false;
		} else {
			tag.hidden = true;
		}
	}

	if (median == null) {
		block.hidden = true;
		return;
	}

	const { p25, p75 } = _zonesFor(getLang());
	const malePct = p25 * 100;
	const overlapPct = (p75 - p25) * 100;
	const femalePct = (1 - p75) * 100;
	_setStyle("resonance-zone-male", "width", `${malePct}%`);
	_setStyle("resonance-zone-neutral", "width", `${overlapPct}%`);
	_setStyle("resonance-zone-female", "width", `${femalePct}%`);

	const indicatorPct = Math.max(0, Math.min(100, median * 100));
	_setStyle("resonance-indicator", "left", `${indicatorPct}%`);

	// Typical-range whiskers: cis-M / cis-F IQR from calibration_v1, served
	// by the backend in panelData.empirical_bands. Mark "active" the band
	// the user's median falls inside — that's the framing payoff: a typical
	// cis-male reading no longer reads as "stuck low", it reads as "in the
	// typical cis-male range".
	const whiskersWrap = document.getElementById("resonance-whiskers");
	if (whiskersWrap) {
		const m = empiricalBands?.m;
		const f = empiricalBands?.f;
		if (m && f) {
			const positionWhisker = (id, band, value) => {
				const el = document.getElementById(id);
				if (!el) return;
				const left = band.p25 * 100;
				const width = (band.p75 - band.p25) * 100;
				el.style.left = `${left}%`;
				el.style.width = `${width}%`;
				const inside = value >= band.p25 && value <= band.p75;
				el.classList.toggle("is-active", inside);
			};
			positionWhisker("resonance-whisker-male", m, median);
			positionWhisker("resonance-whisker-female", f, median);
			whiskersWrap.hidden = false;
		} else {
			whiskersWrap.hidden = true;
		}
	}

	// Range span: min..max of per-vowel medians. Matches the metaphor of
	// .pitch-range-span (observed p5–p95 over zones). Hidden if no usable
	// per-vowel data — minimal tier already short-circuits the panel.
	const span = document.getElementById("resonance-range-span");
	if (span) {
		const vals = (perVowel || [])
			.map((v) => v.resonance_med)
			.filter((v) => typeof v === "number");
		if (vals.length >= 2) {
			const lo = Math.max(0, Math.min(...vals));
			const hi = Math.min(1, Math.max(...vals));
			span.style.left = `${lo * 100}%`;
			span.style.width = `${Math.max(0, hi - lo) * 100}%`;
			span.hidden = false;
		} else {
			span.hidden = true;
		}
	}

	block.hidden = false;
}

// One row in the all-vowels list — mirrors the Distribution panel's
// stat-card recipe: vowel label | gradient progress bar | right-aligned %.
// rAF-deferred bar width set so the CSS transition kicks in on render.
function _buildVowelRow(row) {
	const el = document.createElement("div");
	el.className = "resonance-vowel-row";
	el.dataset.vowel = row.vowel;

	const vowelEl = document.createElement("span");
	vowelEl.className = "resonance-vowel-label";
	vowelEl.textContent = `/${_vowelDisplay(row.vowel)}/`;

	const barWrap = document.createElement("div");
	barWrap.className = "resonance-vowel-bar-wrap";
	const barFill = document.createElement("div");
	barFill.className = "resonance-vowel-bar-fill";
	barWrap.appendChild(barFill);

	const pct = Math.max(0, Math.min(100, Math.round((row.resonance_med ?? 0) * 100)));
	const valueEl = document.createElement("span");
	valueEl.className = "resonance-vowel-pct";
	valueEl.textContent = `${pct}%`;

	el.append(vowelEl, barWrap, valueEl);
	requestAnimationFrame(() => {
		barFill.style.width = `${pct}%`;
	});
	return el;
}

export function renderResonancePanel(panelData, context = {}) {
	const generation = ++_renderGeneration;

	const root = document.getElementById("resonance-panel");
	if (!root) return;
	if (!panelData || !panelData.zone_key) {
		root.hidden = true;
		return;
	}

	// Recompute panel-level median + zone client-side from per_vowel medians
	// so imported sessions (whose cached median_resonance / zone_key were
	// computed by the pre-fix flat-list algorithm) display the new robust
	// median. New analyses already ship the correct value from advice_v2.py;
	// this client recompute is idempotent in that case.
	const meds = (panelData.per_vowel || [])
		.map((v) => v.resonance_med)
		.filter((v) => typeof v === "number");
	let median = panelData.median_resonance;
	let zoneKey = panelData.zone_key;
	if (meds.length) {
		const m = _medianOf(meds);
		if (m != null) {
			median = m;
			zoneKey = _classifyZone(m, getLang()) || zoneKey;
		}
	}

	const summaryEl = document.getElementById("resonance-summary");
	if (summaryEl && zoneKey) {
		summaryEl.textContent = t(`advice.resonance.summary.${zoneKey}`);
		summaryEl.hidden = false;
	} else if (summaryEl) {
		summaryEl.hidden = true;
	}

	_renderMedianBar(median, panelData.per_vowel, panelData.empirical_bands);

	const allSection = document.getElementById("resonance-all-vowels-section");
	const allList = document.getElementById("resonance-all-vowels-list");
	// "low" rows (resonance_med < _VOWEL_RES_WEAK) stay hidden — they add
	// noise without an actionable next step. "weak" and "good" stay.
	const perVowel = (panelData.per_vowel || []).filter((row) => row.level_key !== "low");
	if (allSection && allList) {
		allList.replaceChildren();
		if (perVowel.length) {
			for (const row of perVowel) allList.appendChild(_buildVowelRow(row));
			allSection.hidden = false;
		} else {
			allSection.hidden = true;
		}
	}

	const historyHeader = document.getElementById("resonance-history-header");
	if (historyHeader) historyHeader.hidden = true;
	const divergenceAdvisory = document.getElementById("resonance-divergence-advisory");
	if (divergenceAdvisory) {
		divergenceAdvisory.hidden = true;
		divergenceAdvisory.textContent = "";
	}

	const caveatEl = document.getElementById("resonance-caveat");
	if (caveatEl) {
		if (panelData.caveat_key) {
			caveatEl.textContent = t(panelData.caveat_key);
			caveatEl.hidden = false;
		} else {
			caveatEl.hidden = true;
		}
	}

	root.hidden = false;

	// History-compare async path retired 2026-05-04 — context arguments are
	// retained on the public API for future revival.
	void context;
	void generation;
}

export function clearResonancePanel() {
	_renderGeneration++;
	const root = document.getElementById("resonance-panel");
	if (root) root.hidden = true;
	_hide("resonance-summary");
	_hide("resonance-median-tag");
	_hide("resonance-median-block");
	_hide("resonance-whiskers");
	_hide("resonance-history-header");
	_hide("resonance-divergence-advisory");
	_hide("resonance-all-vowels-section");
	_hide("resonance-caveat");
	const allList = document.getElementById("resonance-all-vowels-list");
	if (allList) allList.replaceChildren();
}
