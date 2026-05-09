/**
 * consonants-toggle.js — Global "include consonants" toggle.
 *
 * Shared state for the resonance views that filter on phoneme class.
 * Consumers:
 *   - resonance-panel.js (per-phone list + median)
 *   - classify.js (声音占比 共鸣 tab — when in resonance mode, drops
 *     non-vowel phones if toggle is OFF so the top tab and bottom panel
 *     stay aligned)
 *
 * Mirrors classify-mode.js's pub/sub + localStorage shape so subscribers
 * can re-render on change.  Default ON ("包含辅音") because consonants
 * carry real vocal-tract resonance signal — hiding them by default would
 * understate what the tool actually measured.
 */

const STORAGE_KEY = "resonance_panel_include_consonants";

let _includeConsonants = (() => {
	try {
		const v = localStorage.getItem(STORAGE_KEY);
		if (v === null) return true; // default ON
		return v === "true";
	} catch (_) {
		return true;
	}
})();

const _listeners = new Set();

export function getIncludeConsonants() {
	return _includeConsonants;
}

export function setIncludeConsonants(value) {
	const next = !!value;
	if (next === _includeConsonants) return;
	_includeConsonants = next;
	try {
		localStorage.setItem(STORAGE_KEY, next ? "true" : "false");
	} catch (_) {}
	for (const cb of _listeners) {
		try {
			cb(next);
		} catch (_) {}
	}
}

export function onIncludeConsonantsChange(cb) {
	_listeners.add(cb);
	return () => _listeners.delete(cb);
}
