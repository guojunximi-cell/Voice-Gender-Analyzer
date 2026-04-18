/**
 * trend-chart.js — Dual-axis pitch + resonance trend chart using uPlot.
 *
 * Bucketizes character cells into ~2 s windows.  Left Y-axis: pitch (Hz).
 * Right Y-axis: resonance (0–1).  Cursor syncs with playback.
 *
 * Hidden accessible <table> sibling for screen readers.
 */

import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

import { resolveCSSVar } from "../utils.js";

const BUCKET_SEC = 2.0;

export class TrendChart {
	/**
	 * @param {{ container: HTMLElement, chars: Array, duration: number, bus: object }} opts
	 */
	mount({ container, chars, duration, bus }) {
		this.bus = bus;

		const n = Math.max(1, Math.ceil(duration / BUCKET_SEC));
		const buckets = Array.from({ length: n }, (_, i) => ({
			tMid: (i + 0.5) * BUCKET_SEC,
			pitchVals: [],
			resVals: [],
		}));

		for (const c of chars) {
			if (!c.char) continue;
			const idx = Math.min(n - 1, Math.floor(c.start / BUCKET_SEC));
			if (c.pitch > 0) buckets[idx].pitchVals.push(c.pitch);
			if (c.resonance != null) buckets[idx].resVals.push(c.resonance);
		}

		const data = [
			buckets.map((b) => b.tMid),
			buckets.map((b) => (b.pitchVals.length ? _mean(b.pitchVals) : null)),
			buckets.map((b) => (b.resVals.length ? _mean(b.resVals) : null)),
		];

		const pitchColor = resolveCSSVar("--pitch") || "#E69F00";
		const resColor = resolveCSSVar("--active") || "#0072B2";
		const textColor = resolveCSSVar("--text-secondary") || "#6b6b63";
		const isMobile = matchMedia("(max-width:767px)").matches;
		const chartH = isMobile ? 160 : 200;

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
					font: '11px "PingFang SC", system-ui, sans-serif',
					values: (_u, vals) => vals.map((v) => `${v.toFixed(0)}s`),
				},
				{
					scale: "hz",
					stroke: pitchColor,
					label: "音高 (Hz)",
					font: '11px "PingFang SC", system-ui, sans-serif',
					labelFont: '11px "PingFang SC", system-ui, sans-serif',
				},
				{
					scale: "res",
					side: 1,
					stroke: resColor,
					label: "共鸣",
					font: '11px "PingFang SC", system-ui, sans-serif',
					labelFont: '11px "PingFang SC", system-ui, sans-serif',
					values: (_u, vals) => vals.map((v) => v.toFixed(2)),
				},
			],
			series: [
				{},
				{
					label: "音高",
					stroke: pitchColor,
					scale: "hz",
					width: 2.5,
					spanGaps: false,
				},
				{
					label: "共鸣",
					stroke: resColor,
					scale: "res",
					width: 2.5,
					dash: [4, 4],
					spanGaps: false,
				},
			],
			cursor: { drag: { x: false, y: false }, y: false },
		};

		const wrap = document.createElement("div");
		wrap.className = "vga-trend-wrap";
		container.appendChild(wrap);

		this.chart = new uPlot(opts, data, wrap);

		// Accessible label
		wrap.setAttribute("role", "img");
		wrap.setAttribute("aria-label", `音高和共鸣随时间变化，共 ${n} 个时间段`);

		// Hidden accessible data table
		const table = document.createElement("table");
		table.className = "vga-sr-only";
		table.innerHTML =
			`<caption>音高与共鸣数据</caption>` +
			`<thead><tr><th>时间 (秒)</th><th>音高 (Hz)</th><th>共鸣 (0\u20131)</th></tr></thead>` +
			`<tbody>${buckets
				.map(
					(_, i) =>
						`<tr><td>${data[0][i].toFixed(1)}</td>` +
						`<td>${data[1][i]?.toFixed(0) ?? "\u2014"}</td>` +
						`<td>${data[2][i]?.toFixed(2) ?? "\u2014"}</td></tr>`,
				)
				.join("")}</tbody>`;
		wrap.appendChild(table);

		// Sync cursor with playback
		this._onTime = (t) => {
			if (!this.chart) return;
			const left = this.chart.valToPos(t, "x");
			if (left != null && isFinite(left)) {
				this.chart.setCursor({ left, top: 0 }, false);
			}
		};
		bus.on("currentTimeChanged", this._onTime);

		// Responsive resize
		this._wrap = wrap;
		this._chartH = chartH;
		this._ro = new ResizeObserver(([entry]) => {
			if (this.chart && entry.contentRect.width > 0) {
				this.chart.setSize({ width: entry.contentRect.width, height: this._chartH });
			}
		});
		this._ro.observe(wrap);
	}

	destroy() {
		this._ro?.disconnect();
		if (this.bus && this._onTime) this.bus.off("currentTimeChanged", this._onTime);
		this.chart?.destroy();
		this.chart = null;
		this._wrap?.remove();
	}
}

function _mean(arr) {
	return arr.reduce((a, b) => a + b, 0) / arr.length;
}
