/**
 * feature-flag.js — localStorage + URL param feature gates.
 *
 * vga.timeline: controls the phone-level interactive timeline UI.
 *   - Default: ON
 *   - Kill via URL: ?timeline=0
 *   - Kill via console: localStorage.setItem('vga.timeline', '0')
 *   - Force-enable via URL: ?timeline=1
 */

export function isTimelineEnabled() {
	const urlFlag = new URLSearchParams(location.search).get("timeline");
	if (urlFlag === "0") return false;
	if (urlFlag === "1") {
		localStorage.setItem("vga.timeline", "1");
		return true;
	}
	return localStorage.getItem("vga.timeline") !== "0";
}
