/**
 * resonance-panel.js — Right panel: phoneme-aligned resonance breakdown.
 *
 * Source: `summary.advice.resonance_panel` (built by advice_v2._resonance_panel).
 * Renders the summary line + median, a per-vowel level grid, top-3 weakness
 * cards with actionable F1/F2/F3 hints, and an optional caveat. Hidden when
 * Engine C is off, the panel is null (minimal tier), or zone is unknown.
 *
 * Same-script history compare runs async after the synchronous render: we
 * load past sessions from IndexedDB, find the most recent earlier attempt
 * with matching language + script identity, and decorate the current rows
 * with ▲/▼ delta arrows. A render generation token prevents stale async
 * writes from clobbering a fresher render.
 */

import { t } from "./i18n.js";

// History-compare imports retired 2026-05-04 — see _decorateWithHistory below
// for the commented body. Kept as `import { ... } from "./resonance-history.js"`
// in a previous revision; remove on next deletion pass if no revival happens.

let _renderGeneration = 0;

function _hide(id) {
	const el = document.getElementById(id);
	if (el) el.hidden = true;
}

function _vowelDisplay(vowel) {
	// Strip ARPABET stress digits (IY1 → IY) for display. zh phones already
	// have tone marks stripped by the backend aggregator. Keep the slash
	// notation /xx/ as the universal "this is a phoneme" cue.
	return vowel.replace(/[0-9]+$/, "");
}

// Resonance % rail spans [0, 100]. Drawn as a neutral ruler with quarter-point
// ticks — no gendered color cues — so the only signal is the indicator's
// position. Same scale as the panel-level "共振中位数 65%" so a user can read
// each per-vowel score against the same yardstick.
const _RAIL_PCT_TICKS = [0, 25, 50, 75, 100];

function _formatPctTickLabel(pct) {
	return `${pct}%`;
}

function _appendRailTicks(rail) {
	for (const p of _RAIL_PCT_TICKS) {
		const tick = document.createElement("span");
		tick.className = "rail-tick";
		tick.style.left = `${p}%`;
		const lbl = document.createElement("span");
		lbl.className = "rail-tick-label";
		lbl.textContent = _formatPctTickLabel(p);
		tick.appendChild(lbl);
		rail.appendChild(tick);
	}
}

function _appendIndicator(rail, pct, indicatorClass) {
	const clamped = Math.max(0, Math.min(100, pct));
	const indicator = document.createElement("span");
	indicator.className = indicatorClass;
	indicator.style.left = `${clamped}%`;
	rail.appendChild(indicator);
	return false; // pct is always in-range after clamp; signature kept for callers
}

// COMMENTED OUT 2026-05-04: z-axis rail (formant z-score [-3σ, +1σ]). Replaced
// by the percent rail above to keep one consistent unit across the panel.
// const _RAIL_MIN_Z = -3;
// const _RAIL_MAX_Z = 1;
// const _RAIL_TICKS = [-3, -2, -1, 0, 1];
// function _zToPct(z) { return ((z - _RAIL_MIN_Z) / (_RAIL_MAX_Z - _RAIL_MIN_Z)) * 100; }
// function _formatTickLabel(z) { ... }
// function _formatSignedZ(z) { ... }

function _buildWeaknessCard(w) {
	const card = document.createElement("div");
	card.className = "resonance-weakness-card";
	const vowelDisp = _vowelDisplay(w.vowel);
	const pct = Math.round((w.resonance_med ?? 0) * 100);
	const descriptor = t(w.text_key);

	const header = document.createElement("div");
	header.className = "resonance-weakness-header";
	const label = document.createElement("span");
	label.className = "resonance-weakness-label";
	label.textContent = `/${vowelDisp}/  ${descriptor}`;
	const valueEl = document.createElement("span");
	valueEl.className = "resonance-weakness-z";
	valueEl.textContent = `${pct}%`;
	header.append(label, valueEl);

	const rail = document.createElement("div");
	rail.className = "resonance-weakness-rail";
	_appendRailTicks(rail);
	_appendIndicator(rail, pct, "weakness-indicator");

	card.setAttribute("aria-label", `/${vowelDisp}/ ${descriptor} ${pct}%`);
	card.append(header, rail);
	return card;
}

// One row in the all-vowels list: vowel + level pill + resonance % + inline
// mini rail. The empty `delta` span is kept (hidden) for layout stability and
// to make the history-compare path easy to revive.
function _buildVowelRow(row) {
	const el = document.createElement("div");
	el.className = "resonance-vowel-row";
	el.dataset.vowel = row.vowel;

	const vowelEl = document.createElement("span");
	vowelEl.className = "resonance-vowel-label";
	vowelEl.textContent = `/${_vowelDisplay(row.vowel)}/`;

	const delta = document.createElement("span");
	delta.className = "resonance-delta";
	delta.dataset.role = "delta";
	delta.hidden = true;

	const pct = Math.round((row.resonance_med ?? 0) * 100);
	const valueEl = document.createElement("span");
	valueEl.className = "resonance-vowel-z";
	valueEl.textContent = `${pct}%`;

	const rail = document.createElement("div");
	rail.className = "resonance-vowel-rail";
	_appendRailTicks(rail);
	_appendIndicator(rail, pct, "vowel-indicator");

	el.append(vowelEl, delta, valueEl, rail);
	return el;
}

// COMMENTED OUT 2026-05-04: ▲/▼ delta annotations on per-vowel rows. The whole
// history-compare flow was retired because the panel-level "共振中位数 X%"
// already speaks in the same unit as per-vowel rows now, so the user can just
// remember the previous reading. Revive together with _decorateWithHistory.
// function _writeDelta(rowEl, change_key, delta) {
// 	const slot = rowEl.querySelector('[data-role="delta"]');
// 	if (!slot) return;
// 	if (change_key === "improved") {
// 		slot.dataset.change = "improved";
// 		slot.textContent = `▲ ${_formatSignedZ(delta)} σ`;
// 		slot.title = t("advice.resonance.history.improved");
// 		slot.hidden = false;
// 	} else if (change_key === "regressed") {
// 		slot.dataset.change = "regressed";
// 		slot.textContent = `▼ ${_formatSignedZ(delta)} σ`;
// 		slot.title = t("advice.resonance.history.regressed");
// 		slot.hidden = false;
// 	} else {
// 		slot.hidden = true;
// 		slot.textContent = "";
// 		delete slot.dataset.change;
// 	}
// }

// ─────────────────────────────────────────────────────────────────────────────
// COMMENTED OUT 2026-05-04: per-vowel history compare + pitch-compensation
// advisory. The per-vowel rows are now in resonance % (same unit as the panel
// median), so per-row ▲/▼ deltas duplicated the headline number. The function
// is kept verbatim so reviving it later is a single-uncomment job.
// ─────────────────────────────────────────────────────────────────────────────
// async function _decorateWithHistory({ summary, createdAt, generation }) {
// 	if (!extractSpokenText(summary)) return;
// 	const headerEl = document.getElementById("resonance-history-header");
// 	const listEl = document.getElementById("resonance-all-vowels-list");
// 	if (!headerEl || !listEl) return;
//
// 	const identity = await buildScriptIdentity(summary, getLang());
// 	if (generation !== _renderGeneration) return;
// 	if (!identity.spoken_text_tokens?.length) return;
//
// 	const sessions = await loadSessions();
// 	if (generation !== _renderGeneration) return;
//
// 	const prior = findPriorAttempt({
// 		sessions,
// 		language: identity.language,
// 		currentTokens: identity.spoken_text_tokens,
// 		currentScriptId: identity.script_id,
// 		before_created_at: createdAt ?? Date.now(),
// 	});
// 	if (!prior) return;
//
// 	const currentRows = summary?.advice?.resonance_panel?.per_vowel || [];
// 	const decorated = computePerVowelDeltas(currentRows, extractPerVowel(prior));
// 	if (generation !== _renderGeneration) return;
//
// 	for (const row of decorated) {
// 		const rowEl = listEl.querySelector(`.resonance-vowel-row[data-vowel="${CSS.escape(row.vowel)}"]`);
// 		if (rowEl) _writeDelta(rowEl, row.change_key, row.delta);
// 	}
//
// 	const when = formatRelativeTime(prior.createdAt, getLang()) || "";
// 	headerEl.textContent = t("advice.resonance.history.compare_with", { when });
// 	headerEl.hidden = false;
//
// 	const advisoryEl = document.getElementById("resonance-divergence-advisory");
// 	if (advisoryEl) {
// 		const advisoryKey = detectPitchCompensation(
// 			summary?.overall_gender_score,
// 			prior.summary?.overall_gender_score,
// 			decorated,
// 		);
// 		if (advisoryKey) {
// 			advisoryEl.textContent = t(`advice.resonance.history.${advisoryKey}`);
// 			advisoryEl.hidden = false;
// 		} else {
// 			advisoryEl.hidden = true;
// 			advisoryEl.textContent = "";
// 		}
// 	}
// }

export function renderResonancePanel(panelData, context = {}) {
	const generation = ++_renderGeneration;

	const root = document.getElementById("resonance-panel");
	if (!root) return;
	if (!panelData || !panelData.zone_key) {
		root.hidden = true;
		return;
	}

	const summaryEl = document.getElementById("resonance-summary");
	if (summaryEl && panelData.summary_text_key) {
		summaryEl.textContent = t(panelData.summary_text_key);
		summaryEl.hidden = false;
	} else if (summaryEl) {
		summaryEl.hidden = true;
	}

	const medianEl = document.getElementById("resonance-median");
	if (medianEl) {
		if (panelData.median_resonance != null) {
			const pct = Math.round(panelData.median_resonance * 100);
			medianEl.textContent = `${t("advice.resonance.median_label")}: ${pct}%`;
			medianEl.hidden = false;
		} else {
			medianEl.hidden = true;
		}
	}

	// All-vowels list (level pills + inline rail). Rendered synchronously so
	// the panel snaps in immediately; history-compare deltas decorate later.
	const allSection = document.getElementById("resonance-all-vowels-section");
	const allList = document.getElementById("resonance-all-vowels-list");
	// "low" rows are intentionally hidden from the all-vowels list — they add
	// noise without an actionable next step. "weak" still shows here (and gets
	// its own weakness card below) and "good" stays as positive confirmation.
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

	// History header + divergence advisory are hidden by default;
	// _decorateWithHistory shows them only when a matching prior is found
	// (and the advisory only when the divergence pattern triggers).
	const historyHeader = document.getElementById("resonance-history-header");
	if (historyHeader) historyHeader.hidden = true;
	const divergenceAdvisory = document.getElementById("resonance-divergence-advisory");
	if (divergenceAdvisory) {
		divergenceAdvisory.hidden = true;
		divergenceAdvisory.textContent = "";
	}

	const section = document.getElementById("resonance-weakness-section");
	const list = document.getElementById("resonance-weakness-list");
	const weaknesses = panelData.weakness_vowels || [];
	if (section && list) {
		list.replaceChildren();
		const titleEl = document.getElementById("resonance-weakness-title");
		if (titleEl) titleEl.textContent = t("advice.resonance.weakness_section_title");
		if (weaknesses.length) {
			for (const w of weaknesses) list.appendChild(_buildWeaknessCard(w));
			section.hidden = false;
		} else {
			// Show "no weakness" line instead of hiding entirely — gives the
			// user a positive confirmation that nothing crossed the -0.8 line.
			const empty = document.createElement("div");
			empty.className = "resonance-weakness-empty";
			empty.textContent = t("advice.resonance.no_weakness");
			list.appendChild(empty);
			section.hidden = false;
		}
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

	// History-compare async path commented out 2026-05-04 (see _decorateWithHistory
	// block above). `context.summary` and `context.createdAt` arguments are
	// retained on the public API for future revival.
	void context;
	void generation;
}

export function clearResonancePanel() {
	_renderGeneration++;
	const root = document.getElementById("resonance-panel");
	if (root) root.hidden = true;
	_hide("resonance-summary");
	_hide("resonance-median");
	_hide("resonance-history-header");
	_hide("resonance-divergence-advisory");
	_hide("resonance-all-vowels-section");
	_hide("resonance-weakness-section");
	_hide("resonance-caveat");
	const list = document.getElementById("resonance-weakness-list");
	if (list) list.replaceChildren();
	const allList = document.getElementById("resonance-all-vowels-list");
	if (allList) allList.replaceChildren();
}
