/**
 * scatter.js — Gender expression strip chart (Canvas 2D)
 *
 * Y-axis: Comprehensive gender score (0~100%)
 *         0% = ♂ 男性化, 50% = 中性, 100% = ♀ 女性化
 * Each session renders as a horizontal strip at its score Y. Strip thickness
 * adapts to the canvas height; sessions whose Y values would collide get
 * grouped into a cluster and split the plot width so each stays clickable.
 *
 * Click a strip → fires onDotClick(session).
 */

import { scoreToColor as _scoreToColorUtil } from "../utils.js";
import { getMode } from "./classify-mode.js";
import { classifyForMode, dominantForMode } from "./classify.js";

// ─── Layout constants ────────────────────────────────────────
const PAD = { top: 14, right: 14, bottom: 14, left: 14 };
const STRIP_H_MIN = 4;
const STRIP_H_MAX = 10;
const HIT_PAD_Y = 4; // vertical click leeway around each strip
const SEG_GAP = 2; // horizontal gap between cluster segments

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

/** Resolve gender score under the current classify mode.  engineA falls
 *  through to the session's stored `label`/`confidence`; pitch/resonance
 *  reclassify from Engine C phones when available, with graceful fallback. */
function _getScore(s) {
	const mode = getMode();
	const { label, confidence } =
		mode === "engineA" ? { label: s.label, confidence: s.confidence } : dominantForMode(s, mode);
	if (label !== "female" && label !== "male") return 50;
	const conf = confidence != null ? confidence : s.gender_score != null ? s.gender_score / 100 : 0.5;
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

/** Compute layout: canvas geometry, adaptive strip thickness, and the
 *  per-session horizontal segment. Sessions whose score Y values fall within
 *  CLUSTER_GAP of one another form a cluster and split the plot width equally,
 *  so overlapping bands stay individually clickable instead of stacking. */
function _layout() {
	const W = _w(),
		H = _h();
	const plotLeft = PAD.left;
	const plotRight = W - PAD.right;
	const plotTop = PAD.top;
	const plotBottom = H - PAD.bottom;
	const plotW = plotRight - plotLeft;
	const plotH = plotBottom - plotTop;

	const STRIP_H = Math.max(STRIP_H_MIN, Math.min(STRIP_H_MAX, Math.round(plotH / 35)));
	const CLUSTER_GAP = STRIP_H + 2 * HIT_PAD_Y + 4;

	const geom = sessions.map((s, idx) => ({
		s,
		idx,
		y: _scoreToY(_getScore(s), plotTop, plotBottom),
	}));

	const sorted = geom.slice().sort((a, b) => a.y - b.y);
	const clusters = [];
	for (const g of sorted) {
		const last = clusters[clusters.length - 1];
		if (last && g.y - last.maxY < CLUSTER_GAP) {
			last.members.push(g);
			last.maxY = Math.max(last.maxY, g.y);
		} else {
			clusters.push({ members: [g], maxY: g.y });
		}
	}

	const segments = new Map();
	for (const cluster of clusters) {
		cluster.members.sort((a, b) => a.idx - b.idx);
		const N = cluster.members.length;
		const segW = plotW / N;
		for (let ci = 0; ci < N; ci++) {
			const m = cluster.members[ci];
			segments.set(m.s.id, {
				x: plotLeft + ci * segW,
				w: segW,
				y: m.y,
				clusterSize: N,
			});
		}
	}

	return { W, H, plotLeft, plotRight, plotTop, plotBottom, plotW, plotH, STRIP_H, segments };
}

// ─── Draw ─────────────────────────────────────────────────────
function _draw() {
	if (!canvas || !ctx) return;

	const { W, H, plotLeft, plotRight, plotTop, plotBottom, plotW, STRIP_H, segments } = _layout();
	ctx.clearRect(0, 0, W, H);

	// ── Background gradient (male=blue bottom → female=pink top) ──
	const bg = ctx.createLinearGradient(0, plotBottom, 0, plotTop);
	bg.addColorStop(0, "rgba(59,130,246,0.09)");
	bg.addColorStop(0.5, "rgba(167,139,250,0.02)");
	bg.addColorStop(1, "rgba(244,63,94,0.09)");
	ctx.fillStyle = bg;
	ctx.fillRect(plotLeft, plotTop, plotW, plotBottom - plotTop);

	// ── Center neutral reference line (no labels) ────────────────
	const centerY = _scoreToY(50, plotTop, plotBottom);
	ctx.save();
	ctx.strokeStyle = "rgba(128,128,128,0.35)";
	ctx.lineWidth = 1;
	ctx.beginPath();
	ctx.moveTo(plotLeft, centerY);
	ctx.lineTo(plotRight, centerY);
	ctx.stroke();
	ctx.restore();

	// ── Bars: thin strips at score position; clustered ones share a row ──
	for (let i = 0; i < sessions.length; i++) {
		const s = sessions[i];
		const seg = segments.get(s.id);
		if (!seg) continue;
		const score = _getScore(s);
		const isSelected = s.id === selectedId;
		const isHovered = s.id === hoveredId;
		const color = _scoreToColor(score);
		const sy = seg.y - STRIP_H / 2;
		const drawX = seg.clusterSize > 1 ? seg.x + SEG_GAP / 2 : seg.x;
		const drawW = seg.clusterSize > 1 ? Math.max(2, seg.w - SEG_GAP) : seg.w;

		if (isSelected || isHovered) {
			ctx.save();
			ctx.shadowColor = color;
			ctx.shadowBlur = isSelected ? 14 : 7;
		}

		ctx.fillStyle = _withAlpha(color, isSelected ? 1 : isHovered ? 0.9 : 0.65);
		ctx.fillRect(drawX, sy, drawW, STRIP_H);

		if (isSelected) {
			ctx.strokeStyle = "rgba(255,255,255,0.85)";
			ctx.lineWidth = 1.5;
			ctx.strokeRect(drawX, sy, drawW, STRIP_H);
		}

		if (isSelected || isHovered) ctx.restore();

		// Range extent line — shows min/max voiced segment score for selected session
		if (isSelected && s.analysis) {
			const segs = classifyForMode(s, getMode());
			const voicedScores = segs
				.filter((seg2) => seg2.label === "male" || seg2.label === "female")
				.map((seg2) => {
					const c = seg2.confidence ?? 0.5;
					return seg2.label === "female" ? 50 + c * 50 : 50 - c * 50;
				});
			if (voicedScores.length > 1) {
				const yTop = _scoreToY(Math.max(...voicedScores), plotTop, plotBottom);
				const yBottom = _scoreToY(Math.min(...voicedScores), plotTop, plotBottom);
				const cx = drawX + drawW / 2;
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
	}
}

// ─── Hit test (strips) ────────────────────────────────────────
function _hitTest(ex, ey) {
	const { plotLeft, plotRight, segments, STRIP_H } = _layout();
	if (ex < plotLeft || ex > plotRight) return null;
	const halfH = STRIP_H / 2 + HIT_PAD_Y;
	for (let i = 0; i < sessions.length; i++) {
		const s = sessions[i];
		const seg = segments.get(s.id);
		if (!seg) continue;
		if (ex < seg.x || ex > seg.x + seg.w) continue;
		if (ey < seg.y - halfH || ey > seg.y + halfH) continue;
		return s;
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
