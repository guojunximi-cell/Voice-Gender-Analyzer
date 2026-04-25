/**
 * engine-c-fallback.js — Empty-state / failure / low-data UI for Engine C.
 *
 * Shows contextual copy (zh/en via i18n) when the phone-level timeline
 * cannot render:
 *   - Engine C failed entirely (sidecar error, MFA failed, etc.)
 *   - Empty transcript (no speech detected)
 *   - Too few phones for meaningful analysis (<8)
 */

import { t } from "./i18n.js";

function _esc(s) {
	const d = document.createElement("span");
	d.textContent = s;
	return d.innerHTML;
}

/**
 * Render the full failure block into the given container.
 */
export function renderFallback(container) {
	container.innerHTML = `
		<section class="vga-fallback" role="alert">
			<h3>${_esc(t("fallback.noTimelineTitle"))}</h3>
			<p>${_esc(t("fallback.noTimelineLead"))}</p>
			<h4>${_esc(t("fallback.commonReasons"))}</h4>
			<ul>
				<li>${_esc(t("fallback.reasonTooShort"))}</li>
				<li>${_esc(t("fallback.reasonWrongLang"))}</li>
				<li>${_esc(t("fallback.reasonNoise"))}</li>
				<li>${_esc(t("fallback.reasonNoSpeech"))}</li>
			</ul>
			<h4>${_esc(t("fallback.tips"))}</h4>
			<ol>
				<li>${_esc(t("fallback.tipQuiet"))}</li>
				<li>${_esc(t("fallback.tipRead"))}</li>
				<li>${_esc(t("fallback.tipMicDist"))}</li>
			</ol>
			<p>${_esc(t("fallback.stillVisible"))}</p>
		</section>`;
}

/**
 * Render the "too few phones" warning banner above the timeline.
 * @param {HTMLElement} container
 * @param {number} count
 */
export function renderLowPhoneBanner(container, count) {
	const banner = document.createElement("div");
	banner.className = "vga-low-phone-banner";
	banner.textContent = t("fallback.lowPhone", { n: count });
	container.prepend(banner);
}

/**
 * Render the "no speech" empty state.
 */
export function renderNoSpeech(container) {
	container.innerHTML = `
		<section class="vga-fallback">
			<h3>${_esc(t("fallback.noSpeechTitle"))}</h3>
			<p>${_esc(t("fallback.noSpeechLead"))}</p>
			<p>${_esc(t("fallback.noSpeechHint"))}</p>
		</section>`;
}
