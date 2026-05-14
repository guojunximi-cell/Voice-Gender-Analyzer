/**
 * heatmap-band.js — SVG heatmap band, rendered per current page.
 *
 * Two render modes (mount-time + setMode-able live):
 *   - "phone" (default) → one <rect> per phone, sub-char time-proportional.
 *                         Color via `colorFn(phone)` / title via `titleFn(phone)`.
 *   - "word"            → one <rect> per char (= word in en/fr, hanzi in zh),
 *                         colored from the char's duration-weighted aggregate.
 *                         Uses `wordColorFn(char)` / `wordTitleFn(char)`.
 * Null / non-finite color → hatch pattern fallback in either mode.
 *
 * Layout: weight-aligned, not time-proportional.  viewBox width = the page's
 * `totalWeight`; each char occupies `[cumWeight, cumWeight + weight]` — so a
 * single hanzi (weight 1) and an English "morning" (weight 7) share the row
 * at their honest visual ratio.  In "phone" mode the char's slot subdivides
 * by phone duration; in "word" mode the slot is rendered as one rect.  In
 * either mode TranscriptRow derives its button left/width from the same
 * weights so columns align pixel-for-pixel across the three rows.
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
		wordColorFn = (c) => divergingResonance(c.resonance),
		wordTitleFn = (c) => `${c.char || "\u2205"} \xb7 ${c.resonance != null ? c.resonance.toFixed(2) : "\u2014"}`,
		mode = "phone",
		ariaLabel = "\u5171\u9e23\u70ed\u529b\u5e26\uff0c\u6bcf\u683c\u4ee3\u8868\u4e00\u4e2a\u97f3\u7d20\u7684\u5171\u9e23\u503c 0\u20131",
		ariaDescription = "\u5f53\u524d\u53e5\u7684\u5171\u9e23\u70ed\u529b\u5e26",
	}) {
		this.bus = bus;
		this.phones = phones;
		this.sentences = sentences;
		this.colorFn = colorFn;
		this.titleFn = titleFn;
		this.wordColorFn = wordColorFn;
		this.wordTitleFn = wordTitleFn;
		this.mode = mode === "word" ? "word" : "phone";
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

	/** Live-switch between phone-detail and word-aggregate rendering. */
	setMode(mode) {
		const next = mode === "word" ? "word" : "phone";
		if (next === this.mode) return;
		this.mode = next;
		this._renderSentence(this.currentSentenceIdx);
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
		this._activeRect = null;

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
			if (this.mode === "word") {
				const color = this.wordColorFn(c);
				this._addRect({
					x: cum,
					w: Math.max(0.001, cw),
					color,
					title: this.wordTitleFn(c),
					seekTo: c.start,
					ref: c,
				});
			} else {
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
					this._addRect({
						x,
						w,
						color: this.colorFn(p),
						title: this.titleFn(p),
						seekTo: p.start,
						ref: p,
					});
				}
			}
			cum += cw;
		}

		this.svg.setAttribute("aria-description", this.ariaDescription);
	}

	_addRect({ x, w, color, title, seekTo, ref }) {
		const rect = document.createElementNS(NS, "rect");
		rect.setAttribute("x", x);
		rect.setAttribute("width", w);
		rect.setAttribute("y", "0");
		rect.setAttribute("height", "1");
		rect.setAttribute("fill", color ?? `url(#${this._hatchId})`);
		rect.setAttribute("tabindex", "0");
		rect.setAttribute("role", "img");

		const titleEl = document.createElementNS(NS, "title");
		titleEl.textContent = title;
		rect.appendChild(titleEl);

		rect.addEventListener("click", () => this.bus.emit("seek", seekTo));
		rect.addEventListener("keydown", (e) => {
			if (e.key === "Enter" || e.key === " ") {
				e.preventDefault();
				this.bus.emit("seek", seekTo);
			}
		});

		this.svg.appendChild(rect);
		this.rects.push(rect);
		this.phoneRefs.push(ref);
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
