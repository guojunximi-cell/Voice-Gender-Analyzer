/**
 * gender-legend.js — Shared color legend for the blue/pink diverging palette
 * used by both the heatmap rects and the trend chart lines.
 *
 * Pure static legend: gradient bar, direction labels, and a "?" info button
 * that opens a popover explaining the palette's scientific anchors (resonance
 * threshold, pitch boundaries).  No subscription to bus events — earlier
 * versions dimmed the bar to highlight the current sentence's resonance range,
 * but per design feedback the legend should *only* be a key, not also a per-
 * sentence gauge.
 */

import { DIVERGING_HEX, THRESHOLDS } from "./diverging.js";
import { t } from "./i18n.js";

export class GenderLegend {
	/**
	 * @param {{ container: HTMLElement }} opts
	 */
	mount({ container }) {
		const root = document.createElement("div");
		root.className = "vga-gender-legend";
		root.setAttribute("role", "complementary");
		root.setAttribute("aria-label", t("legend.azimuthAria"));

		const gradient = `linear-gradient(to right, ${DIVERGING_HEX.join(", ")})`;

		root.innerHTML =
			`<div class="vga-gender-legend__bar-wrap">` +
			`<div class="vga-gender-legend__bar" style="background: ${gradient}"></div>` +
			`</div>` +
			`<div class="vga-gender-legend__labels">` +
			`<span class="vga-gender-legend__label vga-gender-legend__label--left">` +
			`${t("legend.male")}` +
			`</span>` +
			`<span class="vga-gender-legend__label vga-gender-legend__label--mid">` +
			`${t("legend.neutral")}` +
			`</span>` +
			`<span class="vga-gender-legend__label vga-gender-legend__label--right">` +
			`${t("legend.female")}` +
			`</span>` +
			`<button type="button" class="vga-gender-legend__info" ` +
			`aria-label="${t("legend.infoAria")}">?</button>` +
			`</div>` +
			`<div class="vga-gender-legend__popover" hidden role="dialog" ` +
			`aria-label="${t("legend.scienceAria")}">` +
			`<p>${t("legend.sci1", { res: THRESHOLDS.resonance })}</p>` +
			`<p>${t("legend.sci2")}</p>` +
			`<p>${t("legend.sci3", { neutral: THRESHOLDS.pitchNeutralHz, fem: THRESHOLDS.pitchFemHz })}</p>` +
			`<p class="vga-gender-legend__note">${t("legend.sciNote")}</p>` +
			`</div>`;

		const info = root.querySelector(".vga-gender-legend__info");
		const pop = root.querySelector(".vga-gender-legend__popover");
		info.addEventListener("click", (e) => {
			e.stopPropagation();
			const open = !pop.hidden;
			pop.hidden = open;
			info.setAttribute("aria-expanded", String(!open));
		});
		document.addEventListener(
			"click",
			(this._closeHandler = (e) => {
				if (!root.contains(e.target)) pop.hidden = true;
			}),
		);

		container.appendChild(root);
		this.root = root;
	}

	destroy() {
		if (this._closeHandler) document.removeEventListener("click", this._closeHandler);
		this.root?.remove();
	}
}
