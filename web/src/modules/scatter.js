/**
 * scatter.js — Gender expression bar chart (Canvas 2D)
 *
 * Y-axis: Comprehensive gender score (0~100%)
 *         0% = ♂ 男性化, 50% = 中性, 100% = ♀ 女性化
 * X-axis: Each session as a vertical bar
 *
 * Click a bar → fires onDotClick(session).
 */

import { scoreToColor as _scoreToColorUtil, resolveCSSVar } from "../utils.js";

// ─── Layout constants ────────────────────────────────────────
const PAD = { top: 36, right: 44, bottom: 24, left: 48 };
const BAR_MAX_W = 56;
const BAR_MIN_W = 8;
const BAR_GAP_RATIO = 0.35; // gap / slot width

// ─── Module state ─────────────────────────────────────────────
let canvas,
	ctx,
	dpr = 1;
let sessions = []; // { id, filename, gender_score, confidence, label, color }
let selectedId = null;
let hoveredId = null;
let _onDotClick = null;
let _onDeselect = null;

// ─── Init ─────────────────────────────────────────────────────
export function initScatter(canvasEl, { onDotClick, onDeselect } = {}) {
	canvas = canvasEl;
	_onDotClick = onDotClick;
	_onDeselect = onDeselect;

	canvas.addEventListener("click", _handleClick);
	canvas.addEventListener("mousemove", _handleHover);
	canvas.addEventListener("mouseleave", () => {
		hoveredId = null;
		_draw();
	});

	const ro = new ResizeObserver(() => _resize());
	ro.observe(canvas.parentElement);
	_resize();
}

// ─── Public API ───────────────────────────────────────────────
export function addSession(session) {
	sessions = sessions.filter((s) => s.id !== session.id);
	sessions.push(session);
	_draw();
}

export function loadAllSessions(arr) {
	sessions = arr.slice();
	_draw();
}

export function selectSession(id) {
	selectedId = id;
	_draw();
}

export function clearAllSessions() {
	sessions = [];
	selectedId = null;
	hoveredId = null;
	_draw();
}

export function removeSession(id) {
	sessions = sessions.filter((s) => s.id !== id);
	if (selectedId === id) selectedId = null;
	hoveredId = null;
	_draw();
}

export function redraw() {
	_resize();
}

// ─── Helpers ──────────────────────────────────────────────────
function _w() {
	return canvas.width / dpr;
}
function _h() {
	return canvas.height / dpr;
}

/** Resolve gender score — mirrors renderGenderBar in metrics-panel.js. */
function _getScore(s) {
	const label = s.label;
	if (label !== "female" && label !== "male") return 50;
	const conf = s.confidence != null ? s.confidence : s.gender_score != null ? s.gender_score / 100 : 0.5;
	return label === "female" ? 50 + Math.min(conf, 1) * 50 : 50 - Math.min(conf, 1) * 50;
}

/** Blue(0) → violet(50) → rose(100). Delegates to shared util (strips alpha). */
function _scoreToColor(score) {
	// _scoreToColorUtil returns rgba(); strip the alpha for compatibility with _withAlpha
	return _scoreToColorUtil(score)
		.replace(/,[\d.]+\)$/, ")")
		.replace("rgba", "rgb");
}

/** Inject alpha into an rgb() string. */
function _withAlpha(rgb, a) {
	return rgb.replace("rgb(", "rgba(").replace(")", `,${a})`);
}

/** Score → canvas Y (0%=bottom, 100%=top). */
function _scoreToY(score, plotTop, plotBottom) {
	const ratio = Math.max(0, Math.min(100, score)) / 100;
	return plotBottom - ratio * (plotBottom - plotTop);
}

/** Compute bar layout from current canvas size. */
function _layout() {
	const W = _w(),
		H = _h();
	const plotLeft = PAD.left;
	const plotRight = W - PAD.right;
	const plotTop = PAD.top;
	const plotBottom = H - PAD.bottom;
	const plotW = plotRight - plotLeft;
	const n = Math.max(1, sessions.length);
	const slotW = plotW / n;
	const barW = Math.max(BAR_MIN_W, Math.min(BAR_MAX_W, slotW * (1 - BAR_GAP_RATIO)));
	return { W, H, plotLeft, plotRight, plotTop, plotBottom, plotW, slotW, barW };
}

// ─── Draw ─────────────────────────────────────────────────────
function _draw() {
	if (!canvas || !ctx) return;

	const { W, H, plotLeft, plotRight, plotTop, plotBottom, plotW, slotW, barW } = _layout();
	ctx.clearRect(0, 0, W, H);

	const textColor = resolveCSSVar("--text-muted") || "#888";
	const lineColor = resolveCSSVar("--border") || "rgba(128,128,128,0.15)";
	const isSmall = W < 260;

	// ── Background gradient (male=blue bottom → female=pink top) ──
	const bg = ctx.createLinearGradient(0, plotBottom, 0, plotTop);
	bg.addColorStop(0, "rgba(59,130,246,0.09)");
	bg.addColorStop(0.5, "rgba(167,139,250,0.02)");
	bg.addColorStop(1, "rgba(244,63,94,0.09)");
	ctx.fillStyle = bg;
	ctx.fillRect(plotLeft, plotTop, plotW, plotBottom - plotTop);

	// ── Center line (neutral / 50%) ───────────────────────────────
	const centerY = _scoreToY(50, plotTop, plotBottom);

	// ── Y-axis grid lines & tick labels (± format) ────────────────
	const ticks = [0, 25, 50, 75, 100];
	ctx.font = `${isSmall ? 9 : 10}px Inter, sans-serif`;
	for (const pct of ticks) {
		const y = _scoreToY(pct, plotTop, plotBottom);
		const isNeutral = pct === 50;

		ctx.save();
		ctx.strokeStyle = isNeutral ? "rgba(128,128,128,0.45)" : lineColor;
		ctx.lineWidth = isNeutral ? 1.5 : 1;
		ctx.setLineDash(isNeutral ? [] : [3, 5]);
		ctx.beginPath();
		ctx.moveTo(plotLeft, y);
		ctx.lineTo(plotRight, y);
		ctx.stroke();
		ctx.restore();

		// Map score 0-100 → display -100 to +100
		const dev = (pct - 50) * 2;
		const label = dev === 0 ? "0" : dev > 0 ? `+${dev}` : `${dev}`;
		ctx.fillStyle = dev > 0 ? "rgba(236,72,153,0.7)" : dev < 0 ? "rgba(59,130,246,0.7)" : textColor;
		ctx.textAlign = "right";
		ctx.fillText(`${label}%`, plotLeft - 4, y + 3.5);
	}

	// ── Zone labels (inside plot area) ────────────────────────────
	ctx.font = `${isSmall ? 9 : 10}px Inter, sans-serif`;
	ctx.fillStyle = "rgba(59,130,246,0.45)";
	ctx.textAlign = "left";
	ctx.fillText("♂ 男", plotLeft + 4, plotBottom - 5);

	ctx.fillStyle = "rgba(128,128,128,0.4)";
	ctx.textAlign = "left";
	ctx.fillText("中性", plotLeft + 4, centerY - 4);

	ctx.fillStyle = "rgba(236,72,153,0.5)";
	ctx.textAlign = "left";
	ctx.fillText("♀ 女", plotLeft + 4, plotTop + 12);

	// ── Y-axis title (rotated) ─────────────────────────────────────
	if (!isSmall) {
		ctx.save();
		ctx.translate(12, (plotTop + plotBottom) / 2);
		ctx.rotate(-Math.PI / 2);
		ctx.textAlign = "center";
		ctx.fillStyle = textColor;
		ctx.font = "10px Inter, sans-serif";
		ctx.fillText("综合性别表达 (%)", 0, 0);
		ctx.restore();
	}

	// ── Bars: single-column thin strips at score position ────────
	const STRIP_H = 8;
	for (let i = 0; i < sessions.length; i++) {
		const s = sessions[i];
		const score = _getScore(s);
		const isSelected = s.id === selectedId;
		const isHovered = s.id === hoveredId;
		const color = _scoreToColor(score);
		const isFemale = score >= 50;
		const scoreY = _scoreToY(score, plotTop, plotBottom);
		const sy = scoreY - STRIP_H / 2;

		if (isSelected || isHovered) {
			ctx.save();
			ctx.shadowColor = color;
			ctx.shadowBlur = isSelected ? 14 : 7;
		}

		ctx.fillStyle = _withAlpha(color, isSelected ? 1 : isHovered ? 0.9 : 0.65);
		ctx.fillRect(plotLeft, sy, plotW, STRIP_H);

		if (isSelected) {
			ctx.strokeStyle = "rgba(255,255,255,0.85)";
			ctx.lineWidth = 1.5;
			ctx.strokeRect(plotLeft, sy, plotW, STRIP_H);
		}

		if (isSelected || isHovered) ctx.restore();

		// Range extent line — shows min/max voiced segment score for selected session
		if (isSelected && s.analysis) {
			const voicedScores = s.analysis
				.filter((seg) => seg.label === "male" || seg.label === "female")
				.map((seg) => {
					const c = seg.confidence ?? 0.5;
					return seg.label === "female" ? 50 + c * 50 : 50 - c * 50;
				});
			if (voicedScores.length > 1) {
				const yTop = _scoreToY(Math.max(...voicedScores), plotTop, plotBottom);
				const yBottom = _scoreToY(Math.min(...voicedScores), plotTop, plotBottom);
				const cx = (plotLeft + plotRight) / 2;
				ctx.save();
				ctx.strokeStyle = _withAlpha(color, 0.35);
				ctx.lineWidth = 1;
				ctx.setLineDash([2, 3]);
				ctx.beginPath();
				ctx.moveTo(cx, yTop);
				ctx.lineTo(cx, yBottom);
				ctx.stroke();
				ctx.restore();
			}
		}

		// Score label to the right of plot
		const dev = Math.round(Math.abs(score - 50) * 2);
		const sign = isFemale ? "+" : "-";
		const tipLabel = dev === 0 ? "0%" : `${sign}${dev}%`;
		ctx.fillStyle = isSelected ? resolveCSSVar("--text-primary") || "#eee" : _withAlpha(color, 0.9);
		ctx.font = `${isSelected ? "bold " : ""}${isSmall ? 9 : 10}px Inter, sans-serif`;
		ctx.textAlign = "left";
		ctx.fillText(tipLabel, plotRight + 4, scoreY + 3.5);
	}
}

// ─── Hit test (strips) ────────────────────────────────────────
function _hitTest(ex, ey) {
	const { plotLeft, plotRight, plotTop, plotBottom } = _layout();
	const HIT_PAD = 8;
	if (ex < plotLeft || ex > plotRight) return null;
	for (let i = 0; i < sessions.length; i++) {
		const s = sessions[i];
		const score = _getScore(s);
		const scoreY = _scoreToY(score, plotTop, plotBottom);
		if (ey >= scoreY - HIT_PAD && ey <= scoreY + HIT_PAD) return s;
	}
	return null;
}

function _getEventPos(e) {
	const rect = canvas.getBoundingClientRect();
	return { x: e.clientX - rect.left, y: e.clientY - rect.top };
}

function _handleClick(e) {
	const { x, y } = _getEventPos(e);
	const hit = _hitTest(x, y);
	selectedId = hit ? hit.id : null;
	_draw();
	if (hit) _onDotClick?.(hit);
	else _onDeselect?.();
}

function _handleHover(e) {
	const { x, y } = _getEventPos(e);
	const hit = _hitTest(x, y);
	const newHovered = hit?.id ?? null;
	if (newHovered !== hoveredId) {
		hoveredId = newHovered;
		canvas.style.cursor = newHovered ? "pointer" : "default";
		_draw();
	}
}

// ─── Resize ───────────────────────────────────────────────────
function _resize() {
	if (!canvas?.parentElement) return;
	const rect = canvas.parentElement.getBoundingClientRect();
	if (!rect.width || !rect.height) return;

	dpr = window.devicePixelRatio || 1;
	canvas.width = rect.width * dpr;
	canvas.height = rect.height * dpr;
	canvas.style.width = rect.width + "px";
	canvas.style.height = rect.height + "px";
	ctx = canvas.getContext("2d");
	ctx.scale(dpr, dpr);
	_draw();
}
