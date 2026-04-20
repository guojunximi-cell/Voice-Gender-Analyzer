/**
 * classify-mode.js — Global classification-source toggle.
 *
 * Three sources drive the male/female ratio views (声音占比, waveform overlay,
 * history scatter):
 *   - engineA   → inaSpeechSegmenter labels (default; always available)
 *   - pitch     → Engine C per-phone F0 thresholded at 165 Hz
 *   - resonance → Engine C per-phone resonance thresholded at 0.5
 *
 * The mode is a single module-level value with a pub/sub, persisted to
 * localStorage so the user's pick survives reloads.  Subscribers re-render
 * the three display sites on change.
 */

const STORAGE_KEY = "voiceya:classify-mode";
const VALID = new Set(["engineA", "pitch", "resonance"]);

let _mode = (() => {
	try {
		const v = localStorage.getItem(STORAGE_KEY);
		return VALID.has(v) ? v : "engineA";
	} catch (_) {
		return "engineA";
	}
})();

const _listeners = new Set();

export function getMode() {
	return _mode;
}

export function setMode(m) {
	if (!VALID.has(m) || m === _mode) return;
	_mode = m;
	try {
		localStorage.setItem(STORAGE_KEY, m);
	} catch (_) {}
	for (const cb of _listeners) {
		try {
			cb(m);
		} catch (_) {}
	}
}

export function onModeChange(cb) {
	_listeners.add(cb);
	return () => _listeners.delete(cb);
}
