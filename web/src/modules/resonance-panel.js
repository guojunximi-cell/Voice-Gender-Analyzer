/**
 * resonance-panel.js — Right panel: phoneme-aligned resonance breakdown.
 *
 * Source: `summary.advice.resonance_panel` (built by advice_v2._resonance_panel).
 * Renders the zone classification + median, top-3 weakness vowels with
 * actionable F1/F2/F3 hints, and an optional caveat. Hidden entirely when
 * Engine C is off, the panel is null (minimal tier), or zone is unknown.
 */

import { t } from "./i18n.js";

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

function _buildWeaknessCard(w) {
	const card = document.createElement("div");
	card.className = "resonance-weakness-card";
	const text = t(w.text_key, {
		vowel: _vowelDisplay(w.vowel),
		z: w.z.toFixed(2),
		hz: w.F_med_hz != null ? w.F_med_hz : "—",
	});
	card.textContent = text;
	return card;
}

export function renderResonancePanel(panelData) {
	const root = document.getElementById("resonance-panel");
	if (!root) return;
	if (!panelData || !panelData.zone_key) {
		root.hidden = true;
		return;
	}

	const zoneTag = document.getElementById("resonance-zone-tag");
	if (zoneTag) {
		zoneTag.textContent = t(`advice.resonance.zone.${panelData.zone_key}`);
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
}

export function clearResonancePanel() {
	const root = document.getElementById("resonance-panel");
	if (root) root.hidden = true;
	_hide("resonance-summary");
	_hide("resonance-median");
	_hide("resonance-weakness-section");
	_hide("resonance-caveat");
	const list = document.getElementById("resonance-weakness-list");
	if (list) list.replaceChildren();
}
