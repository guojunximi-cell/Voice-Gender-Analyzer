/**
 * scatter-mode.js — History panel layout-axis toggle.
 *
 *   - score → Y=性别分数（current strip chart）
 *   - time  → Y=createdAt（newest top, hybrid-compressed）, X=性别分数 (dots)
 *
 * Mirrors classify-mode.js: single module-level value with pub/sub, persisted
 * to localStorage so the user's pick survives reloads.
 */

const STORAGE_KEY = "voiceya:scatter-mode";
const VALID = new Set(["score", "time"]);

let _mode = (() => {
	try {
		const v = localStorage.getItem(STORAGE_KEY);
		return VALID.has(v) ? v : "score";
	} catch (_) {
		return "score";
	}
})();

const _listeners = new Set();

export function getScatterMode() {
	return _mode;
}

export function setScatterMode(m) {
	if (!VALID.has(m) || m === _mode) return;
	const prev = _mode;
	_mode = m;
	try {
		localStorage.setItem(STORAGE_KEY, m);
	} catch (_) {}
	for (const cb of _listeners) {
		try {
			cb(m, prev);
		} catch (_) {}
	}
}

export function onScatterModeChange(cb) {
	_listeners.add(cb);
	return () => _listeners.delete(cb);
}
