/**
 * resonance-panel.js — Right panel: phoneme-aligned resonance breakdown.
 *
 * Source: `summary.advice.resonance_panel` (built by advice_v2._resonance_panel).
 * Renders a Pitch-Range-style scale bar showing the panel-level median
 * resonance positioned within language-aware male / androgynous / female
 * zones, plus a per-phone list styled like the Distribution panel's
 * stat-cards (label + slim progress bar + percentage). Hidden when Engine C
 * is off, the panel is null (minimal tier), or zone is unknown.
 *
 * As of 2026-05-08 the per-phone list includes consonants (sonorants the
 * sidecar successfully scored — /m/, /n/, /j/, /w/, /l/, /ŋ/, …) so users
 * can see the full diagnostic distribution.  A toggle ("仅元音 / 包含辅音")
 * lets the user filter consonants out; default is "包含辅音".  The toggle
 * state also drives the median-bar recompute so the headline number stays
 * consistent with what's visible.  Backend keeps weakness coaching
 * vowel-only regardless of toggle (consonants aren't trainable targets).
 */

import { getIncludeConsonants, onIncludeConsonantsChange, setIncludeConsonants } from "./consonants-toggle.js";
import { setBlockHasContent } from "./dashboard.js";
import { getLang, t } from "./i18n.js";
import { RESONANCE_ZONES } from "./zones.js";

let _lastPanelData = null;
let _lastContext = null;

// When the toggle flips (from anywhere), re-render this panel.  main.js
// independently subscribes to drive the 共鸣 tab; both fire from the same
// source of truth.
onIncludeConsonantsChange(() => {
	if (_lastPanelData) renderResonancePanel(_lastPanelData, _lastContext || {});
});

// Two breakpoints split the 0–100% bar into three zones: cis-male (0..p25)
// covers `clearly_below_female` + `leans_male`; androgynous (p25..p75) is
// `mid_neutral`; cis-female (p75..1) covers `leans_female` + `at_ceiling`.
// Boundaries align with the panel's own `summary_text_key` so a
// "Leans cis-male" reading lands in the male band. Values from calibration_v1
// (commit 482d374, 2026-05-06) live in zones.js for shared use.
const _ZONE_THRESHOLDS = RESONANCE_ZONES;

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
	// ko-KR aliases fr-FR until calibration_v1 measures Korean — matches
	// backend `_ZONES_KO = _ZONES_FR` (resonance_calibration.py).  When the
	// backend unaliases, copy the new values here in the same commit.
	"ko-KR": [
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

function _renderMedianBar(median, visibleRows) {
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

	// Range span: min..max of currently-visible per-phone medians (toggle-
	// aware).  Matches the metaphor of .pitch-range-span (observed p5–p95
	// over zones).  Hidden if fewer than 2 rows are visible.
	const span = document.getElementById("resonance-range-span");
	if (span) {
		const vals = (visibleRows || []).map((v) => v.resonance_med).filter((v) => typeof v === "number");
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

// One row in the all-phones list — mirrors the Distribution panel's
// stat-card recipe: phone label | gradient progress bar | right-aligned %
// + (n=X) sample-count annotation.  Consonant rows (is_vowel=false) get
// `.is-consonant` so CSS can italicize + mute them.  rAF-deferred bar
// width set so the CSS transition kicks in on render.
function _buildVowelRow(row) {
	const el = document.createElement("div");
	el.className = "resonance-vowel-row";
	if (row.is_vowel === false) el.classList.add("is-consonant");
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

	const nEl = document.createElement("span");
	nEl.className = "resonance-vowel-n";
	nEl.textContent = row.n != null ? `(n=${row.n})` : "";

	el.append(vowelEl, barWrap, valueEl, nEl);
	requestAnimationFrame(() => {
		barFill.style.width = `${pct}%`;
	});
	return el;
}

function _syncToggleButtons() {
	const group = document.getElementById("resonance-consonants-toggle");
	if (!group) return;
	const includeConsonants = getIncludeConsonants();
	const buttons = group.querySelectorAll(".resonance-consonants-btn");
	buttons.forEach((btn) => {
		const wantsAll = btn.dataset.mode === "all";
		const active = wantsAll === includeConsonants;
		btn.classList.toggle("is-active", active);
		btn.setAttribute("aria-checked", active ? "true" : "false");
	});
}

function _filterByToggle(rows) {
	if (getIncludeConsonants()) return rows;
	return rows.filter((r) => r.is_vowel !== false);
}

export function renderResonancePanel(panelData, context = {}) {
	const generation = ++_renderGeneration;
	_lastPanelData = panelData;
	_lastContext = context;

	const root = document.getElementById("resonance-panel");
	if (!root) return;
	if (!panelData || !panelData.zone_key) {
		root.hidden = true;
		setBlockHasContent("resonance", false);
		return;
	}

	const allRows = panelData.per_vowel || [];
	const visibleRows = _filterByToggle(allRows);

	// Recompute panel-level median + zone client-side from currently-visible
	// per-phone medians. Toggle off → vowel-only median; toggle on → all-phone
	// median. Imported sessions (with cached pre-2026-05-08 median_resonance)
	// always recompute too, so old rows render with the new aggregation.
	const meds = visibleRows.map((v) => v.resonance_med).filter((v) => typeof v === "number");
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

	_renderMedianBar(median, visibleRows);

	const allSection = document.getElementById("resonance-all-vowels-section");
	const allList = document.getElementById("resonance-all-vowels-list");
	// "low" rows (resonance_med < _VOWEL_RES_WEAK) stay hidden — they add
	// noise without an actionable next step. "weak" and "good" stay.
	const displayRows = visibleRows.filter((row) => row.level_key !== "low");
	if (allSection && allList) {
		allList.replaceChildren();
		if (displayRows.length) {
			for (const row of displayRows) allList.appendChild(_buildVowelRow(row));
			allSection.hidden = false;
		} else {
			allSection.hidden = true;
		}
	}
	_syncToggleButtons();

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
	setBlockHasContent("resonance", true);
	wireResonanceConsonantsToggle();

	// History-compare async path retired 2026-05-04 — context arguments are
	// retained on the public API for future revival.
	void generation;
}

// Wire the toggle on first render. Idempotent — flag prevents duplicate
// listener registration if renderResonancePanel is called multiple times.
// State changes flow through consonants-toggle.js so subscribers (main.js
// for the 共鸣 tab) re-render in lockstep with this panel.
let _toggleWired = false;
export function wireResonanceConsonantsToggle() {
	if (_toggleWired) return;
	const group = document.getElementById("resonance-consonants-toggle");
	if (!group) return;
	group.addEventListener("click", (e) => {
		const btn = e.target.closest(".resonance-consonants-btn");
		if (!btn) return;
		const wantsAll = btn.dataset.mode === "all";
		setIncludeConsonants(wantsAll);
	});
	_toggleWired = true;
}

export function clearResonancePanel() {
	_renderGeneration++;
	const root = document.getElementById("resonance-panel");
	if (root) root.hidden = true;
	setBlockHasContent("resonance", false);
	_hide("resonance-summary");
	_hide("resonance-median-tag");
	_hide("resonance-median-block");
	_hide("resonance-history-header");
	_hide("resonance-divergence-advisory");
	_hide("resonance-all-vowels-section");
	_hide("resonance-caveat");
	const allList = document.getElementById("resonance-all-vowels-list");
	if (allList) allList.replaceChildren();
}
