/**
 * gender-legend.js — Shared color legend for the blue/pink diverging palette
 * used by both the heatmap rects and the trend chart lines.
 *
 * Pure static legend: gradient bar, "男声方向 / 中性 / 女声方向" labels, and a
 * "?" info button that opens a popover explaining the palette's scientific
 * anchors (resonance threshold, pitch boundaries).  No subscription to bus
 * events — earlier versions dimmed the bar to highlight the current sentence's
 * resonance range, but per design feedback the legend should *only* be a key,
 * not also a per-sentence gauge.
 */

import { DIVERGING_HEX, THRESHOLDS } from "./diverging.js";

export class GenderLegend {
	/**
	 * @param {{ container: HTMLElement }} opts
	 */
	mount({ container }) {
		const root = document.createElement("div");
		root.className = "vga-gender-legend";
		root.setAttribute("role", "complementary");
		root.setAttribute("aria-label", "\u5171\u9e23\u8272\u6761\u8bf4\u660e");

		const gradient = `linear-gradient(to right, ${DIVERGING_HEX.join(", ")})`;

		root.innerHTML =
			`<div class="vga-gender-legend__bar-wrap">` +
			`<div class="vga-gender-legend__bar" style="background: ${gradient}"></div>` +
			`</div>` +
			`<div class="vga-gender-legend__labels">` +
			`<span class="vga-gender-legend__label vga-gender-legend__label--left">` +
			`\u7537\u58f0\u65b9\u5411` +
			`</span>` +
			`<span class="vga-gender-legend__label vga-gender-legend__label--mid">` +
			`\u4e2d\u6027` +
			`</span>` +
			`<span class="vga-gender-legend__label vga-gender-legend__label--right">` +
			`\u5973\u58f0\u65b9\u5411` +
			`</span>` +
			`<button type="button" class="vga-gender-legend__info" ` +
			`aria-label="\u8272\u7cfb\u8bf4\u660e">?</button>` +
			`</div>` +
			`<div class="vga-gender-legend__popover" hidden role="dialog" ` +
			`aria-label="\u8272\u7cfb\u79d1\u5b66\u4f9d\u636e">` +
			`<p><strong>\u5171\u9e23\u8272\u6761</strong>\u7684\u4e2d\u6027\u70b9\u4e3a 0.5\uff08` +
			`\u53c2\u8003\u8bed\u6599\u5e93\u5747\u503c\uff09\uff0c\u5973\u58f0\u9608\u503c = ` +
			`<strong>${THRESHOLDS.resonance}</strong>\u3002</p>` +
			`<p>\u8be5\u9608\u503c\u57fa\u4e8e AISHELL-3 \u8bed\u6599\u5e93\uff08134 \u7537 + 134 \u5973\uff09` +
			`\u7684 10-fold \u4ea4\u53c9\u9a8c\u8bc1\uff0c\u7cbe\u5ea6 <strong>0.900</strong>\u3002</p>` +
			`<p><strong>\u97f3\u9ad8\u53c2\u8003</strong>\uff1a` +
			`${THRESHOLDS.pitchNeutralHz} Hz \u4e3a\u7537\u58f0\u4e0a\u9650 / \u5973\u58f0\u4e0b\u9650\u4ea4\u754c\uff0c` +
			`${THRESHOLDS.pitchFemHz} Hz \u4e3a\u58f0\u97f3\u8bad\u7ec3\u5e38\u7528\u7684\u5973\u58f0\u611f\u77e5\u9608\u503c\u3002</p>` +
			`<p class="vga-gender-legend__note">\u8272\u503c\u4ec5\u4f5c\u65b9\u5411\u53c2\u8003\uff0c` +
			`\u4e0d\u662f\u6027\u522b\u5224\u5b9a\u3002</p>` +
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
