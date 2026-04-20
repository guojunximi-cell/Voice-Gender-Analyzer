/**
 * bus.js — Tiny pub/sub for cross-component communication.
 *
 * Used by PhoneTimeline and its children (HeatmapBand, TranscriptRow,
 * PlaybackSync) to share state without tight coupling.
 */

export function createBus() {
	const listeners = new Map();
	return {
		on(ev, fn) {
			if (!listeners.has(ev)) listeners.set(ev, new Set());
			listeners.get(ev).add(fn);
		},
		off(ev, fn) {
			listeners.get(ev)?.delete(fn);
		},
		emit(ev, payload) {
			listeners.get(ev)?.forEach((fn) => fn(payload));
		},
		destroy() {
			listeners.clear();
		},
	};
}
