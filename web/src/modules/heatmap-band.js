/**
 * heatmap-band.js — SVG resonance heatmap rendered beneath the waveform.
 *
 * One <rect> per phone, colored by Cividis interpolation of the resonance
 * value (0–1).  Null resonance → diagonal-stripe hatch pattern.
 *
 * Click any rect → bus.emit('seek', startTime).
 * Active phone is highlighted with an accent stroke.
 */

import { cividis } from "./cividis.js";

const NS = "http://www.w3.org/2000/svg";

export class HeatmapBand {
	/**
	 * @param {{ container: HTMLElement, phones: Array, duration: number, bus: object }} opts
	 */
	mount({ container, phones, duration, bus }) {
		this.bus = bus;
		this.duration = duration;
		this.phones = phones;
		this.rects = [];

		const svg = document.createElementNS(NS, "svg");
		svg.setAttribute("class", "vga-heatmap");
		svg.setAttribute("viewBox", `0 0 ${duration} 1`);
		svg.setAttribute("preserveAspectRatio", "none");
		svg.setAttribute("role", "group");
		svg.setAttribute("aria-label", "共鸣热力带，每格代表一个音素的共鸣值 0\u20131");

		// Hatch pattern for null-resonance phones
		const defs = document.createElementNS(NS, "defs");
		const pattern = document.createElementNS(NS, "pattern");
		pattern.setAttribute("id", "vga-hatch");
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
		svg.appendChild(defs);

		phones.forEach((p, i) => {
			const rect = document.createElementNS(NS, "rect");
			const x = p.start;
			const w = Math.max(0.001, p.end - p.start);
			rect.setAttribute("x", x);
			rect.setAttribute("width", w);
			rect.setAttribute("y", "0");
			rect.setAttribute("height", "1");

			const color = cividis(p.resonance);
			rect.setAttribute("fill", color ?? "url(#vga-hatch)");

			rect.dataset.phoneIdx = i;
			rect.setAttribute("tabindex", "0");
			rect.setAttribute("role", "img");

			const title = document.createElementNS(NS, "title");
			const charLabel = p.char || "\u2205";
			const resLabel = p.resonance != null ? p.resonance.toFixed(2) : "\u2014";
			title.textContent = `${charLabel} ${p.phone} \xb7 \u5171\u9e23 ${resLabel}`;
			rect.appendChild(title);

			rect.addEventListener("click", () => bus.emit("seek", p.start));
			rect.addEventListener("keydown", (e) => {
				if (e.key === "Enter" || e.key === " ") {
					e.preventDefault();
					bus.emit("seek", p.start);
				}
			});

			svg.appendChild(rect);
			this.rects.push(rect);
		});

		container.appendChild(svg);
		this.svg = svg;
		this._activeIdx = -1;

		// Listen for active phone changes to highlight the rect
		this._onActive = ({ nextIdx }) => {
			if (this._activeIdx >= 0 && this.rects[this._activeIdx]) {
				this.rects[this._activeIdx].classList.remove("active");
			}
			if (nextIdx >= 0 && this.rects[nextIdx]) {
				this.rects[nextIdx].classList.add("active");
			}
			this._activeIdx = nextIdx;
		};
		bus.on("activeCharChanged", this._onActive);
	}

	destroy() {
		if (this.bus && this._onActive) {
			this.bus.off("activeCharChanged", this._onActive);
		}
		this.svg?.remove();
		this.svg = null;
		this.rects = [];
	}
}
