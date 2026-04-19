/**
 * trend-chart.js — Dual-axis pitch + resonance trend chart using uPlot.
 *
 * Two view modes (toggled via segmented control top-right):
 *   • global  — bucketize all character cells into ~2 s windows, x-axis spans
 *               the full audio duration.  Macro overview.  Default.
 *   • detail  — one data point per character in the *current* sentence;
 *               x-axis = the sentence's time window.  High-resolution view
 *               that re-renders on `activeSentenceChanged` so it stays in
 *               sync with the heatmap, transcript, and playback cursor.
 *
 * Left Y-axis: pitch (Hz, auto-scale).  Right Y-axis: resonance (0–1).
 * Both line strokes use a vertical CanvasGradient mapping the y-pixel's data
 * value through the diverging palette (top = pink/femme, bottom = blue/masc).
 *
 * Hidden accessible <table> sibling for screen readers (rebuilt on mode/data
 * change so it always reflects what's plotted).
 */

import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

import { resolveCSSVar } from "../utils.js";
import { divergingPitch, divergingResonance } from "./diverging.js";

const BUCKET_SEC = 2.0;
// Number of color stops sampled along each line's vertical extent when building
// the y-value→color CanvasGradient.  24 is dense enough for a smooth ribbon at
// chart heights up to ~400 px without measurable cost.
const GRADIENT_STOPS = 24;

/**
 * Build a uPlot `stroke` function that paints the series with a vertical
 * CanvasGradient mapping each y-pixel's data value through `mapFn`.
 * Top of the plot box = scale max → bottom = scale min (so a high pitch /
 * resonance reads as the warm/femme end of the diverging palette and a low
 * value reads as the cool/masc end, matching the heatmap and legend).
 *
 * Falls back to `fallback` if the scale has no resolved range yet
 * (e.g. before first draw, or when uPlot calls without a bbox).
 */
function makeValueGradientStroke(scaleKey, mapFn, fallback) {
	return (u) => {
		const sc = u?.scales?.[scaleKey];
		if (!u?.ctx || !u?.bbox || sc?.min == null || sc?.max == null) return fallback;
		const top = u.bbox.top;
		const bot = u.bbox.top + u.bbox.height;
		const grad = u.ctx.createLinearGradient(0, top, 0, bot);
		for (let i = 0; i <= GRADIENT_STOPS; i++) {
			const frac = i / GRADIENT_STOPS;
			// frac=0 at top → use scale max; frac=1 at bottom → use scale min
			const v = sc.max - (sc.max - sc.min) * frac;
			grad.addColorStop(frac, mapFn(v) || fallback);
		}
		return grad;
	};
}

export class TrendChart {
	/**
	 * @param {{
	 *   container: HTMLElement,
	 *   chars: Array,
	 *   duration: number,
	 *   sentences: Array,
	 *   bus: object,
	 * }} opts
	 */
	mount({ container, chars, duration, sentences, bus }) {
		this.bus = bus;
		this.duration = duration;
		this.sentences = sentences || [];
		this.chars = chars;
		this._mode = "global";
		this._currentSentence = this.sentences[0] || null;

		const pitchColor = resolveCSSVar("--pitch") || "#E69F00";
		const resColor = resolveCSSVar("--active") || "#0072B2";
		const textColor = resolveCSSVar("--text-secondary") || "#6b6b63";
		// Chart height is viewport-aware (re-queried in the ResizeObserver below
		// too, so a rotation / window resize re-fits).  Mobile gets 240 because
		// portrait viewports have plenty of vertical room and the previous 160
		// left the plot area uncomfortably squat next to two y-axes worth of
		// label / tick reservations.
		const isMobile = matchMedia("(max-width:767px)").matches;
		const chartH = isMobile ? 240 : 200;
		const axisFont = isMobile
			? '10px "PingFang SC", system-ui, sans-serif'
			: '11px "PingFang SC", system-ui, sans-serif';

		const opts = {
			width: container.clientWidth || 300,
			height: chartH,
			scales: {
				x: { time: false },
				hz: { auto: true },
				res: { range: [0, 1] },
			},
			axes: [
				{
					stroke: textColor,
					font: axisFont,
					// Adapt precision to the visible range so detail mode (narrow
					// per-sentence windows) doesn't repeat the same "1s 1s 1s 2s 2s"
					// label across multiple ticks.
					values: (_u, vals) => {
						const span = vals.length > 1 ? vals[vals.length - 1] - vals[0] : 0;
						const decimals = span < 5 ? 1 : 0;
						return vals.map((v) => `${v.toFixed(decimals)}s`);
					},
				},
				{
					// Y-axis label is rendered as a horizontal title above the chart
					// (see `.vga-trend-axis-titles` HTML below) instead of uPlot's
					// rotated vertical text, which wasted horizontal space and was
					// hard to read on mobile.  Tick numbers stay here.
					scale: "hz",
					stroke: pitchColor,
					font: axisFont,
				},
				{
					scale: "res",
					side: 1,
					stroke: resColor,
					font: axisFont,
					values: (_u, vals) => vals.map((v) => v.toFixed(2)),
				},
			],
			series: [
				{},
				{
					label: "音高",
					// Diverging gradient along the line's y-extent: low pitch (cool blue)
					// at the bottom, high pitch (warm pink) at the top — matches heatmap
					// and gender-legend semantics.  `stretch:true` keeps the line color
					// in the saturated halves of the palette (skips the bleached warm-
					// white midpoint), so it stays visible on the white chart background
					// while every color drawn is still a palette stop.
					stroke: makeValueGradientStroke("hz", (v) => divergingPitch(v, { stretch: true }), pitchColor),
					scale: "hz",
					width: 3,
					spanGaps: false,
				},
				{
					label: "共鸣",
					stroke: makeValueGradientStroke("res", (v) => divergingResonance(v, { stretch: true }), resColor),
					scale: "res",
					width: 3,
					dash: [4, 4],
					spanGaps: false,
				},
			],
			// Disable uPlot's built-in legend: the swatch element expects a CSS color
			// string and can't render a CanvasGradient stroke.  The axis-side labels
			// (音高/共鸣) plus the dash pattern already disambiguate the two lines.
			legend: { show: false },
			cursor: { drag: { x: false, y: false }, y: false },
		};

		const wrap = document.createElement("div");
		wrap.className = "vga-trend-wrap";
		container.appendChild(wrap);
		this._wrap = wrap;
		this._chartH = chartH;

		// Axis titles row — horizontal labels at the top corners (`音高 (Hz)`
		// left, `共鸣` right), replacing uPlot's rotated vertical labels which
		// wasted horizontal space.  Colors match the original axis stroke
		// tokens so users still associate "this title → this y-axis".
		const titles = document.createElement("div");
		titles.className = "vga-trend-axis-titles";
		titles.setAttribute("aria-hidden", "true");
		titles.innerHTML =
			`<span class="vga-trend-axis-title vga-trend-axis-title--left" style="color:${pitchColor}">音高 (Hz)</span>` +
			`<span class="vga-trend-axis-title vga-trend-axis-title--right" style="color:${resColor}">共鸣</span>`;
		wrap.appendChild(titles);

		// Inner area scopes the canvas + sentence-band overlay so the band
		// doesn't extend up over the title row.
		const chartArea = document.createElement("div");
		chartArea.className = "vga-trend-chart-area";
		wrap.appendChild(chartArea);
		this._chartArea = chartArea;

		// Mode toggle is built here but NOT appended — the parent (PhoneTimeline)
		// places it in the shared timeline footer next to the legend so it
		// doesn't overlap the plot area.  Use `getModeToggle()` to retrieve it.
		this._modeToggle = this._buildModeToggle();

		// Current-sentence highlight overlay (absolute within chartArea).  Only
		// visible in global mode — in detail mode the entire chart IS the
		// sentence, so the band would just cover everything.
		this._sentenceBand = document.createElement("div");
		this._sentenceBand.className = "vga-trend-sentence-band";
		this._sentenceBand.setAttribute("aria-hidden", "true");
		chartArea.appendChild(this._sentenceBand);

		const initialData = this._computeGlobalData();
		this.chart = new uPlot(opts, initialData, chartArea);

		// Click-to-seek: same affordance as heatmap-band rects.  Click anywhere
		// in the plot area → convert pixel x to time via uPlot's posToVal (which
		// respects whatever scale is currently active, so this works in both
		// global and detail modes without special-casing) → emit "seek" on the
		// bus.  PlaybackSync handles the rest (waveform seek + activeChar /
		// activeSentence updates).  Bound to `chart.over` (uPlot's interaction
		// overlay) rather than the wrap so axis/label clicks don't trigger.
		this._onChartClick = (e) => {
			if (!this.chart?.over) return;
			const rect = this.chart.over.getBoundingClientRect();
			const x = e.clientX - rect.left;
			const t = this.chart.posToVal(x, "x");
			if (t == null || !Number.isFinite(t)) return;
			this.bus.emit("seek", t);
		};
		this.chart.over.addEventListener("click", this._onChartClick);
		this.chart.over.style.cursor = "pointer";

		// Accessible label
		wrap.setAttribute("role", "img");
		wrap.setAttribute("aria-label", "音高和共鸣随时间变化");

		// Hidden accessible data table (rebuilt by _refreshA11yTable on mode/data
		// change so screen readers always read what's plotted).
		this._a11yTable = document.createElement("table");
		this._a11yTable.className = "vga-sr-only";
		wrap.appendChild(this._a11yTable);
		this._refreshA11yTable(initialData);

		// Sync cursor with playback (works in both modes — currentTime maps to
		// chart x via valToPos, which respects whatever scale the chart has).
		this._onTime = (t) => {
			if (!this.chart) return;
			const left = this.chart.valToPos(t, "x");
			if (left != null && isFinite(left)) {
				this.chart.setCursor({ left, top: 0 }, false);
			}
		};
		bus.on("currentTimeChanged", this._onTime);

		// Sentence change → either reposition band (global) or rebuild data (detail).
		this._onSentence = ({ sentence }) => {
			this._currentSentence = sentence;
			if (this._mode === "global") {
				this._positionSentenceBand(sentence);
			} else {
				this._refreshDetailData();
			}
		};
		bus.on("activeSentenceChanged", this._onSentence);

		// Default: show first sentence's band without requiring a playback tick
		if (this._currentSentence) {
			requestAnimationFrame(() => {
				if (this._mode === "global") this._positionSentenceBand(this._currentSentence);
			});
		}

		// Responsive resize — height is re-queried from matchMedia on every
		// resize so portrait↔landscape transitions update both axes.
		this._ro = new ResizeObserver(([entry]) => {
			if (this.chart && entry.contentRect.width > 0) {
				const isMobileNow = matchMedia("(max-width:767px)").matches;
				this._chartH = isMobileNow ? 240 : 200;
				this.chart.setSize({ width: entry.contentRect.width, height: this._chartH });
				if (this._mode === "global" && this._currentSentence) {
					this._positionSentenceBand(this._currentSentence);
				}
			}
		});
		this._ro.observe(wrap);
	}

	/** Public: returns the mode-toggle root element so a parent can place it. */
	getModeToggle() {
		return this._modeToggle?.root || null;
	}

	// ── Mode toggle UI ───────────────────────────────────────────
	_buildModeToggle() {
		const root = document.createElement("div");
		root.className = "vga-trend-mode-toggle";
		root.setAttribute("role", "group");
		root.setAttribute("aria-label", "折线图视图模式");

		const mkBtn = (mode, label, title) => {
			const b = document.createElement("button");
			b.type = "button";
			b.className = "vga-trend-mode-btn" + (mode === this._mode ? " active" : "");
			b.dataset.mode = mode;
			b.textContent = label;
			b.title = title;
			b.setAttribute("aria-pressed", mode === this._mode ? "true" : "false");
			b.addEventListener("click", () => this._setMode(mode));
			return b;
		};

		const globalBtn = mkBtn("global", "整体", "整段音频概览（每 2 秒一个聚合点）");
		const detailBtn = mkBtn("detail", "片段", "当前句逐字数据（高分辨率）");
		root.append(globalBtn, detailBtn);

		return {
			root,
			update(mode) {
				for (const b of [globalBtn, detailBtn]) {
					const active = b.dataset.mode === mode;
					b.classList.toggle("active", active);
					b.setAttribute("aria-pressed", active ? "true" : "false");
				}
			},
		};
	}

	_setMode(mode) {
		if (mode === this._mode || !this.chart) return;
		this._mode = mode;
		this._modeToggle.update(mode);

		if (mode === "global") {
			const data = this._computeGlobalData();
			this.chart.setData(data);
			this._refreshA11yTable(data);
			this._sentenceBand.style.display = "block";
			if (this._currentSentence) {
				requestAnimationFrame(() => this._positionSentenceBand(this._currentSentence));
			}
		} else {
			this._sentenceBand.style.display = "none";
			this._refreshDetailData();
		}
	}

	_refreshDetailData() {
		const s = this._currentSentence;
		if (!s || !this.chart) return;
		const data = this._computeDetailData(s);
		this.chart.setData(data);
		this._refreshA11yTable(data);
	}

	// ── Data builders ────────────────────────────────────────────
	/** Global: ~2 s buckets across the full audio duration. */
	_computeGlobalData() {
		const n = Math.max(1, Math.ceil(this.duration / BUCKET_SEC));
		const buckets = Array.from({ length: n }, (_, i) => ({
			tMid: (i + 0.5) * BUCKET_SEC,
			pitchVals: [],
			resVals: [],
		}));

		for (const c of this.chars) {
			if (!c.char) continue;
			const idx = Math.min(n - 1, Math.floor(c.start / BUCKET_SEC));
			if (c.pitch > 0) buckets[idx].pitchVals.push(c.pitch);
			if (c.resonance != null) buckets[idx].resVals.push(c.resonance);
		}

		return [
			buckets.map((b) => b.tMid),
			buckets.map((b) => (b.pitchVals.length ? _mean(b.pitchVals) : null)),
			buckets.map((b) => (b.resVals.length ? _mean(b.resVals) : null)),
		];
	}

	/** Detail: one data point per character in the current sentence. */
	_computeDetailData(sentence) {
		const sChars = sentence.chars;
		return [
			sChars.map((c) => (c.start + c.end) / 2),
			sChars.map((c) => (c.pitch > 0 ? c.pitch : null)),
			sChars.map((c) => c.resonance),
		];
	}

	// ── Sentence band overlay (global mode only) ─────────────────
	_positionSentenceBand(sentence) {
		if (!this.chart || !sentence || this._mode !== "global") return;
		const xStart = this.chart.valToPos(sentence.start, "x", true);
		const xEnd = this.chart.valToPos(sentence.end, "x", true);
		if (!isFinite(xStart) || !isFinite(xEnd)) return;
		const left = Math.min(xStart, xEnd);
		const width = Math.max(1, Math.abs(xEnd - xStart));
		this._sentenceBand.style.left = `${left}px`;
		this._sentenceBand.style.width = `${width}px`;
		this._sentenceBand.style.display = "block";
	}

	// ── Accessible data table ────────────────────────────────────
	_refreshA11yTable(data) {
		const xs = data[0];
		const pitches = data[1];
		const reses = data[2];
		this._a11yTable.innerHTML =
			`<caption>音高与共鸣数据（${this._mode === "global" ? "整体视图" : "片段视图"}）</caption>` +
			`<thead><tr><th>时间 (秒)</th><th>音高 (Hz)</th><th>共鸣 (0\u20131)</th></tr></thead>` +
			`<tbody>${xs
				.map(
					(_, i) =>
						`<tr><td>${xs[i].toFixed(1)}</td>` +
						`<td>${pitches[i] != null ? pitches[i].toFixed(0) : "\u2014"}</td>` +
						`<td>${reses[i] != null ? reses[i].toFixed(2) : "\u2014"}</td></tr>`,
				)
				.join("")}</tbody>`;
	}

	destroy() {
		this._ro?.disconnect();
		if (this.bus) {
			if (this._onTime) this.bus.off("currentTimeChanged", this._onTime);
			if (this._onSentence) this.bus.off("activeSentenceChanged", this._onSentence);
		}
		if (this._onChartClick && this.chart?.over) {
			this.chart.over.removeEventListener("click", this._onChartClick);
		}
		this.chart?.destroy();
		this.chart = null;
		this._wrap?.remove();
	}
}

function _mean(arr) {
	return arr.reduce((a, b) => a + b, 0) / arr.length;
}
