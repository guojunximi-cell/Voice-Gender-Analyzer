/**
 * heatmap-band.js — SVG heatmap band, rendered per current page.
 *
 * Each visible <rect> is one phone, colored through a caller-supplied
 * `colorFn(phone)`.  Two bands live in the timeline: one keyed on pitch,
 * one on resonance.  Null / non-finite color → hatch pattern fallback.
 *
 * Layout: weight-aligned, not time-proportional.  viewBox width = the page's
 * `totalWeight`; each char occupies `[cumWeight, cumWeight + weight]` — so a
 * single hanzi (weight 1) and an English "morning" (weight 7) share the row
 * at their honest visual ratio.  Inside a char's slot, its phones subdivide
 * by their relative durations within the char, so sub-char timing is
 * preserved while macro columns (pitch cell / hanzi / resonance cell at
 * char i) stay rigidly aligned across the three rows at any viewport width
 * because TranscriptRow derives its left/width from the same weights.
 * Silence phones between chars are skipped — the page has exactly N slots
 * for N real hanzi.
 */

import { divergingResonance } from "./diverging.js";

const NS = "http://www.w3.org/2000/svg";
// Each band's hatch pattern needs a unique id so two bands on the same page
// don't share (and thus steal) a single <pattern> from the first <defs>.
let _hatchSeq = 0;

const DEFAULT_TITLE_FN = (p) => {
	const charLabel = p.char || "\u2205";
	const resLabel = p.resonance != null ? p.resonance.toFixed(2) : "\u2014";
	return `${charLabel} ${p.phone} \xb7 \u5171\u9e23 ${resLabel}`;
};

export class HeatmapBand {
	/**
	 * @param {{
	 *   container: HTMLElement,
	 *   phones: Array,
	 *   sentences: Array,
	 *   bus: object,
	 *   colorFn?: (phone) => string|null,
	 *   titleFn?: (phone) => string,
	 *   ariaLabel?: string,
	 *   ariaDescription?: string,
	 * }} opts
	 */
	mount({
		container,
		phones,
		sentences,
		bus,
		colorFn = (p) => divergingResonance(p.resonance),
		titleFn = DEFAULT_TITLE_FN,
		ariaLabel = "\u5171\u9e23\u70ed\u529b\u5e26\uff0c\u6bcf\u683c\u4ee3\u8868\u4e00\u4e2a\u97f3\u7d20\u7684\u5171\u9e23\u503c 0\u20131",
		ariaDescription = "\u5f53\u524d\u53e5\u7684\u5171\u9e23\u70ed\u529b\u5e26",
	}) {
		this.bus = bus;
		this.phones = phones;
		this.sentences = sentences;
		this.colorFn = colorFn;
		this.titleFn = titleFn;
		this.ariaDescription = ariaDescription;
		this.currentSentenceIdx = 0;

		this._hatchId = `vga-hatch-${++_hatchSeq}`;

		this.svg = document.createElementNS(NS, "svg");
		this.svg.setAttribute("class", "vga-heatmap");
		this.svg.setAttribute("preserveAspectRatio", "none");
		this.svg.setAttribute("role", "group");
		this.svg.setAttribute("aria-label", ariaLabel);

		// Hatch pattern (null color fallback)
		const defs = document.createElementNS(NS, "defs");
		const pattern = document.createElementNS(NS, "pattern");
		pattern.setAttribute("id", this._hatchId);
		pattern.setAttribute("width", "4");
		pattern.setAttribute("height", "4");
		pattern.setAttribute("patternUnits", "userSpaceOnUse");
		pattern.setAttribute("patternTransform", "rotate(45)");
		const bg = document.createElementNS(NS, "rect");
		bg.setAttribute("width", "4");
		bg.setAttribute("height", "4");
		bg.setAttribute("fill", "var(--bg-secondary)");
		const line = document.createElementNS(NS, "line");
		line.setAttribute("x1", "0");
		line.setAttribute("y1", "0");
		line.setAttribute("x2", "0");
		line.setAttribute("y2", "4");
		line.setAttribute("stroke", "var(--text-muted)");
		line.setAttribute("stroke-width", "1");
		pattern.appendChild(bg);
		pattern.appendChild(line);
		defs.appendChild(pattern);
		this.svg.appendChild(defs);

		container.appendChild(this.svg);

		this._renderSentence(0);

		this._onActiveSentence = ({ nextIdx }) => {
			if (nextIdx !== this.currentSentenceIdx) this._renderSentence(nextIdx);
		};
		bus.on("activeSentenceChanged", this._onActiveSentence);

		// Highlight active phone via currentTime (sentence-scoped)
		this._activeRect = null;
		this._onTime = (t) => this._highlightAt(t);
		bus.on("currentTimeChanged", this._onTime);
	}

	_highlightAt(t) {
		if (!this.rects?.length) return;
		const page = this.sentences[this.currentSentenceIdx];
		if (!page || t < page.start || t > page.end) {
			if (this._activeRect) {
				this._activeRect.classList.remove("active");
				this._activeRect = null;
			}
			return;
		}
		// Linear find — phones per page are small (typically <60)
		let hit = null;
		for (let j = 0; j < this.rects.length; j++) {
			const p = this.phoneRefs[j];
			if (t >= p.start && t < p.end) {
				hit = this.rects[j];
				break;
			}
		}
		if (hit !== this._activeRect) {
			this._activeRect?.classList.remove("active");
			hit?.classList.add("active");
			this._activeRect = hit;
		}
	}

	_renderSentence(idx) {
		if (!this.sentences.length) return;
		const clamped = Math.max(0, Math.min(this.sentences.length - 1, idx));
		this.currentSentenceIdx = clamped;
		const page = this.sentences[clamped];
		const N = page.chars.length;

		// Clear previous rects (keep <defs>)
		while (this.svg.children.length > 1) {
			this.svg.removeChild(this.svg.lastChild);
		}
		this.rects = [];
		this.phoneRefs = [];

		if (!N) {
			this.svg.setAttribute("aria-description", this.ariaDescription);
			return;
		}

		// viewBox unit = one weight unit (= one CJK hanzi or one English letter
		// after clamping).  preserveAspectRatio=none stretches the totalWeight-
		// wide slot row to fill the container; char i occupies [cumW, cumW +
		// weight_i], and TranscriptRow derives its button's left/width from
		// the same weights — so columns align pixel-for-pixel.  For legacy
		// pages without a weight (e.g. a test fixture), fall back to 1.
		const W = page.totalWeight ?? N;
		this.svg.setAttribute("viewBox", `0 0 ${W} 1`);

		let cum = 0;
		for (let i = 0; i < N; i++) {
			const c = page.chars[i];
			const cw = c.weight ?? 1;
			const cDur = Math.max(0.001, c.end - c.start);
			const phones = c.phones || [];
			for (const p of phones) {
				const localStart = Math.max(0, p.start - c.start);
				const localEnd = Math.min(cDur, p.end - c.start);
				if (localEnd <= localStart) continue;
				// x/w in viewBox (weight) units: char owns `cw` units, phone
				// subdivides by time within that span.
				const x = cum + (localStart / cDur) * cw;
				const w = Math.max(0.001, ((localEnd - localStart) / cDur) * cw);

				const rect = document.createElementNS(NS, "rect");
				rect.setAttribute("x", x);
				rect.setAttribute("width", w);
				rect.setAttribute("y", "0");
				rect.setAttribute("height", "1");

				const color = this.colorFn(p);
				rect.setAttribute("fill", color ?? `url(#${this._hatchId})`);
				rect.setAttribute("tabindex", "0");
				rect.setAttribute("role", "img");

				const title = document.createElementNS(NS, "title");
				title.textContent = this.titleFn(p);
				rect.appendChild(title);

				rect.addEventListener("click", () => this.bus.emit("seek", p.start));
				rect.addEventListener("keydown", (e) => {
					if (e.key === "Enter" || e.key === " ") {
						e.preventDefault();
						this.bus.emit("seek", p.start);
					}
				});

				this.svg.appendChild(rect);
				this.rects.push(rect);
				this.phoneRefs.push(p);
			}
			cum += cw;
		}

		this.svg.setAttribute("aria-description", this.ariaDescription);
	}

	destroy() {
		if (this.bus) {
			if (this._onActiveSentence) this.bus.off("activeSentenceChanged", this._onActiveSentence);
			if (this._onTime) this.bus.off("currentTimeChanged", this._onTime);
		}
		this.svg?.remove();
		this.svg = null;
		this.rects = [];
		this.phoneRefs = [];
	}
}
