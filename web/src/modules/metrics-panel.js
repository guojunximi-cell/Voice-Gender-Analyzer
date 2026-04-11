/**
 * metrics-panel.js — Right panel: acoustic features of a selected segment.
 * Called whenever a segment is clicked (waveform overlay or list item).
 */

import { certaintTag, LABEL_META, scoreToColor, sigmaRescale, tierToColor } from "../utils.js";

// ─── Animated number counter ──────────────────────────────────
function animNum(el, target, suffix = "", duration = 600) {
	if (!el) return;
	const start = performance.now();
	const from = parseFloat(el.dataset.current || 0) || 0;
	el.dataset.current = target;
	function tick(now) {
		const p = Math.min((now - start) / duration, 1);
		const ease = 1 - Math.pow(1 - p, 3);
		el.textContent = Math.round(from + (target - from) * ease) + suffix;
		if (p < 1) requestAnimationFrame(tick);
	}
	requestAnimationFrame(tick);
}

function animBar(el, pct, delay = 0) {
	if (!el) return;
	setTimeout(() => {
		el.style.width = `${Math.max(0, Math.min(100, pct))}%`;
	}, delay);
}

// ─── Sub-score row builder ────────────────────────────────────
// Each entry defines physical measurement display for a slider track.
// rawKey: actual measured value from acoustics (Hz / cm / dB)
// tierKey: 1–5 tier returned by backend for color
// range: [min, max] of the physical scale shown on the track
// logScale: use log2 mapping for position (pitch)
// reversed: higher raw value = left (masculine) side (VTL)
// ticks: tier boundary values for tick mark positions
const SUB_SCORE_DEFS = [
	{
		label: "音高",
		rawKey: "f0_median_hz",
		tierKey: "pitch_tier",
		unit: "Hz",
		range: [80, 280],
		logScale: true,
		reversed: false,
		ticks: [120, 155, 185, 225],
		fmt: (v) => `${Math.round(v)} Hz`,
	},
	{
		label: "共振峰",
		rawKey: "f2_hz",
		tierKey: "formant_tier",
		unit: "Hz",
		range: [1000, 2500],
		logScale: false,
		reversed: false,
		ticks: [1400, 1600, 1900, 2200],
		fmt: (v) => `${Math.round(v)} Hz`,
	},
	{
		label: "共鸣",
		rawKey: "vtl_cm",
		tierKey: "vtl_tier",
		unit: "cm",
		range: [12, 20],
		logScale: false,
		reversed: true,
		ticks: [17.5, 16.5, 15.5, 14.5],
		fmt: (v) => `${v.toFixed(1)} cm`,
	},
	{
		label: "倾斜",
		rawKey: "h1_h2_db",
		tierKey: "tilt_tier",
		unit: "dB",
		range: [-2, 15],
		logScale: false,
		reversed: false,
		ticks: [1, 4, 7, 11],
		fmt: (v) => `${v.toFixed(1)} dB`,
	},
];

function _physicalToPercent(def, rawVal) {
	if (rawVal == null) return 50;
	const [lo, hi] = def.range;
	let pct;
	if (def.logScale) {
		const logMin = Math.log2(lo),
			logMax = Math.log2(hi);
		const logVal = Math.log2(Math.max(lo, Math.min(hi, rawVal)));
		pct = ((logVal - logMin) / (logMax - logMin)) * 100;
	} else {
		pct = ((Math.max(lo, Math.min(hi, rawVal)) - lo) / (hi - lo)) * 100;
	}
	return def.reversed ? 100 - pct : pct;
}

function renderSubScores(a) {
	const el = document.getElementById("mc-subscores");
	if (!el) return;
	el.innerHTML = "";

	for (const def of SUB_SCORE_DEFS) {
		const rawVal = a[def.rawKey] ?? null;
		const tier = a[def.tierKey] ?? null;
		const color = tierToColor(tier);
		const pct = _physicalToPercent(def, rawVal);
		const valStr = rawVal != null ? def.fmt(rawVal) : `— ${def.unit}`;

		// Build tick mark HTML at tier boundary positions
		const ticksHtml = def.ticks
			.map((t) => {
				const tp = _physicalToPercent(def, t);
				return `<div class="src-tick" style="left:${tp.toFixed(1)}%"></div>`;
			})
			.join("");

		const row = document.createElement("div");
		row.className = "src-row";
		row.innerHTML = `
      <div class="src-header">
        <span class="src-label">${def.label}</span>
        <span class="src-val">${valStr}</span>
      </div>
      <div class="src-track-wrap">
        <div class="src-track">
          ${ticksHtml}
          <div class="src-marker" style="left:50%;background:${color}"></div>
        </div>
      </div>
    `;
		el.appendChild(row);

		if (rawVal != null) {
			requestAnimationFrame(() => {
				const marker = row.querySelector(".src-marker");
				if (marker) marker.style.left = `${Math.max(0, Math.min(100, pct))}%`;
			});
		}
	}

	const legend = document.createElement("div");
	legend.className = "src-zone-legend";
	legend.innerHTML = `
    <span class="src-legend-male">♂ 男性化</span>
    <span class="src-legend-female">♀ 女性化</span>
  `;
	el.appendChild(legend);
}

// ─── Gender spectrum bar ──────────────────────────────────────
// confidence: 0–1 from Engine A; label: 'female'|'male'
function renderGenderBar(confidence, label) {
	const thumb = document.getElementById("mc-gender-thumb");
	const scoreEl = document.getElementById("mc-gender-score");
	if (!thumb || !scoreEl) return;

	const scaledConf = Math.min(confidence, 1);
	const pct = label === "female" ? 50 + scaledConf * 50 : 50 - scaledConf * 50;

	requestAnimationFrame(() => {
		thumb.style.left = `${pct}%`;
	});
	thumb.dataset.gender = label;

	const pctDisplay = Math.min(Math.round(confidence * 100), 100);
	const symbol = label === "female" ? "♀" : "♂";
	scoreEl.textContent = `${pctDisplay}% ${symbol}`;
}

// ─── Public: render metrics for a segment ────────────────────
export function renderMetricsPanel(segment) {
	const empty = document.getElementById("metrics-empty");
	const content = document.getElementById("metrics-content");
	if (!empty || !content) return;

	// Segments without acoustic data (music, noise, noEnergy, or too-short voiced)
	if (!segment?.acoustics) {
		const name = (LABEL_META[segment?.label] || {}).zh || segment?.label || "该片段";
		const isVoiced = segment?.label === "male" || segment?.label === "female";
		const msg = isVoiced ? `${name} — 片段过短，无法分析` : `${name} — 无声学特征数据`;
		empty.innerHTML = `<svg width="32" height="32" viewBox="0 0 32 32" fill="none" opacity="0.3" aria-hidden="true"><circle cx="16" cy="16" r="14" stroke="currentColor" stroke-width="1.5"/><path d="M10 16 Q13 10 16 16 Q19 22 22 16" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg><span>${msg}</span>`;
		empty.hidden = false;
		content.hidden = true;
		return;
	}

	empty.hidden = true;
	content.hidden = false;

	const a = segment.acoustics;

	// ── F0 card ──────────────────────────────────────────────
	animNum(document.getElementById("mc-f0-median"), a.f0_median_hz, " Hz");
	const stdEl = document.getElementById("mc-f0-std");
	if (stdEl) stdEl.textContent = `±${a.f0_std_hz ?? "—"} Hz`;

	// ── Resonance card ───────────────────────────────────────
	animNum(document.getElementById("mc-res-val"), Math.round(a.resonance_pct), "%");
	animBar(document.getElementById("mc-res-bar"), a.resonance_pct, 80);

	// ── Formants ─────────────────────────────────────────────
	const setFormant = (id, val) => {
		const el = document.getElementById(id);
		if (el) el.textContent = val ? `${val} Hz` : "—";
	};
	setFormant("mc-f1", a.f1_hz);
	setFormant("mc-f2", a.f2_hz);
	setFormant("mc-f3", a.f3_hz);

	// ── Spectral Tilt (H1–H2) ───────────────────────────────
	const tiltEl = document.getElementById("mc-tilt-val");
	if (tiltEl) {
		tiltEl.textContent = a.h1_h2_db != null ? `${a.h1_h2_db.toFixed(1)} dB` : "—";
	}

	// ── Pitch range reference bar ────────────────────────────
	const pitchIndicator = document.getElementById("mc-pitch-indicator");
	if (pitchIndicator && a.f0_median_hz) {
		// Map 80–320 Hz log scale to 0–100%
		const logMin = Math.log2(80),
			logMax = Math.log2(320);
		const logVal = Math.log2(Math.max(80, Math.min(320, a.f0_median_hz)));
		const pct = ((logVal - logMin) / (logMax - logMin)) * 100;
		requestAnimationFrame(() => {
			pitchIndicator.style.left = `${pct}%`;
		});
	}

	// ── Gender score bar (Engine A confidence as primary) ────
	const conf = segment.confidence != null ? segment.confidence : a.gender_score / 100;
	renderGenderBar(conf, segment.label);

	// ── Sub-scores ───────────────────────────────────────────
	renderSubScores(a);

	// ── Segment label in header ──────────────────────────────
	const headerLabel = document.getElementById("mc-segment-label");
	if (headerLabel) {
		const meta = LABEL_META[segment.label] || { zh: segment.label };
		headerLabel.textContent = `${meta.zh}  ${_fmtTime(segment.start_time)}~${_fmtTime(segment.end_time)}`;
	}

	// ── Certainty tag badge ───────────────────────────────────
	const tagEl = document.getElementById("mc-certainty-tag");
	if (tagEl) {
		const tag = certaintTag(segment);
		tagEl.textContent = tag;
		tagEl.hidden = !tag;
	}
}

// ─── Confidence timeline (per-frame within a segment) ────────
export function renderConfidenceDistribution(segment) {
	const section = document.getElementById("mc-dist-section");
	const canvas = document.getElementById("mc-dist-canvas");
	if (!canvas) {
		if (section) section.hidden = true;
		return;
	}

	const frames = segment?.confidence_frames;
	if (!frames || !frames.length) {
		if (section) section.hidden = true;
		return;
	}
	section.hidden = false;

	const label = segment.label; // 'female' | 'male'
	const FRAME_DUR = 0.02; // 20 ms per frame

	// Defer draw if canvas is inside closed <details> (width = 0)
	const body = canvas.parentElement;
	if (!body || body.clientWidth < 4) {
		section.addEventListener("toggle", () => renderConfidenceDistribution(segment), { once: true });
		return;
	}

	const PAD_L = 28,
		PAD_R = 4,
		PAD_T = 10,
		PAD_B = 14;
	const dpr = window.devicePixelRatio || 1;
	const W = body.clientWidth;
	const H = 64;
	canvas.width = W * dpr;
	canvas.height = H * dpr;
	canvas.style.width = W + "px";
	canvas.style.height = H + "px";
	const ctx = canvas.getContext("2d");
	ctx.scale(dpr, dpr);

	const plotL = PAD_L,
		plotR = W - PAD_R;
	const plotT = PAD_T,
		plotB = H - PAD_B;
	const plotW = plotR - plotL,
		plotH = plotB - plotT;

	// Background
	ctx.fillStyle = "rgba(128,128,128,0.04)";
	ctx.fillRect(plotL, plotT, plotW, plotH);

	// Horizontal guide lines at 50% and mean
	const mean = frames.reduce((a, b) => a + b, 0) / frames.length;
	const halfY = plotB - 0.5 * plotH;
	ctx.strokeStyle = "rgba(128,128,128,0.2)";
	ctx.lineWidth = 1;
	ctx.setLineDash([2, 4]);
	ctx.beginPath();
	ctx.moveTo(plotL, halfY);
	ctx.lineTo(plotR, halfY);
	ctx.stroke();
	ctx.setLineDash([]);

	// Mean line
	const meanY = plotB - mean * plotH;
	const meanColor = label === "female" ? "rgba(236,72,153,0.5)" : "rgba(59,130,246,0.5)";
	ctx.strokeStyle = meanColor;
	ctx.lineWidth = 1;
	ctx.setLineDash([4, 3]);
	ctx.beginPath();
	ctx.moveTo(plotL, meanY);
	ctx.lineTo(plotR, meanY);
	ctx.stroke();
	ctx.setLineDash([]);

	// Y-axis labels
	ctx.font = "8px Inter, sans-serif";
	ctx.textAlign = "right";
	ctx.fillStyle = "rgba(128,128,128,0.5)";
	ctx.fillText("1.0", plotL - 3, plotT + 4);
	ctx.fillText("0.5", plotL - 3, halfY + 3);
	ctx.fillText("0", plotL - 3, plotB + 1);

	// Draw frame confidence as area + line
	const stepW = plotW / frames.length;
	const lineColor = label === "female" ? "rgba(236,72,153,0.8)" : "rgba(59,130,246,0.8)";
	const fillColor = label === "female" ? "rgba(236,72,153,0.12)" : "rgba(59,130,246,0.12)";

	// Area fill
	ctx.beginPath();
	ctx.moveTo(plotL, plotB);
	for (let i = 0; i < frames.length; i++) {
		const x = plotL + (i + 0.5) * stepW;
		const y = plotB - Math.min(frames[i], 1) * plotH;
		if (i === 0) ctx.lineTo(x, y);
		else ctx.lineTo(x, y);
	}
	ctx.lineTo(plotL + (frames.length - 0.5) * stepW, plotB);
	ctx.closePath();
	ctx.fillStyle = fillColor;
	ctx.fill();

	// Line
	ctx.beginPath();
	for (let i = 0; i < frames.length; i++) {
		const x = plotL + (i + 0.5) * stepW;
		const y = plotB - Math.min(frames[i], 1) * plotH;
		if (i === 0) ctx.moveTo(x, y);
		else ctx.lineTo(x, y);
	}
	ctx.strokeStyle = lineColor;
	ctx.lineWidth = 1.5;
	ctx.stroke();

	// X-axis: time labels relative to segment start
	const totalSec = frames.length * FRAME_DUR;
	ctx.font = "7px Inter, sans-serif";
	ctx.textAlign = "center";
	ctx.fillStyle = "rgba(128,128,128,0.5)";
	const startT = segment.start_time ?? 0;
	ctx.fillText(_fmtTime(startT), plotL, plotB + 10);
	ctx.fillText(_fmtTime(startT + totalSec), plotR, plotB + 10);
	if (totalSec > 0.5) {
		const midT = startT + totalSec / 2;
		ctx.fillText(_fmtTime(midT), plotL + plotW / 2, plotB + 10);
	}

	// Mean label
	ctx.font = "7px Inter, sans-serif";
	ctx.textAlign = "left";
	ctx.fillStyle = meanColor;
	ctx.fillText(`μ=${(mean * 100).toFixed(0)}%`, plotR - 30, meanY - 3);
}

// ─── Clear panel ─────────────────────────────────────────────
export function clearMetricsPanel() {
	const empty = document.getElementById("metrics-empty");
	const content = document.getElementById("metrics-content");
	if (empty) {
		empty.innerHTML = `<svg width="32" height="32" viewBox="0 0 32 32" fill="none" opacity="0.3" aria-hidden="true"><circle cx="16" cy="16" r="14" stroke="currentColor" stroke-width="1.5"/><path d="M10 16 Q13 10 16 16 Q19 22 22 16" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg><span>点击音段<br/>查看声学特征</span>`;
		empty.hidden = false;
	}
	if (content) content.hidden = true;
}

function _fmtTime(sec) {
	if (sec == null) return "—";
	const m = Math.floor(sec / 60);
	const s = Math.floor(sec % 60);
	return `${m}:${s.toString().padStart(2, "0")}`;
}
