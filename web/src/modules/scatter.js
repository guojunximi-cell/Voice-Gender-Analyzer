/**
 * scatter.js — History scatter (Canvas 2D, two layout modes)
 *
 *   Score mode (default): Y = comprehensive gender score (0–100%, 0%=♂ → 100%=♀).
 *     Each session is a full-width horizontal strip at its score Y; strips
 *     whose Y values collide cluster and split the plot width.
 *
 *   Time mode: Y = createdAt mapped via a 40/30/30 hybrid scale (top=now,
 *     bottom=oldest), X = gender score (left=♂, right=♀).  Each session is
 *     a small dot; hover surfaces a tooltip with date / filename / score.
 *
 * Mode is owned by `scatter-mode.js` and persisted to localStorage; the
 * dispatcher `_draw` cross-fades between mode renderers during transitions.
 *
 * Click hit → fires onDotClick(session).
 */

import { scoreToColor as _scoreToColorUtil } from "../utils.js";
import { getMode } from "./classify-mode.js";
import { classifyForMode, dominantForMode } from "./classify.js";
import { getLang, t } from "./i18n.js";
import { getScatterMode, onScatterModeChange } from "./scatter-mode.js";

// ─── Layout constants (score mode) ───────────────────────────
const PAD = { top: 14, right: 14, bottom: 14, left: 14 };
const STRIP_H_MIN = 4;
const STRIP_H_MAX = 10;
const HIT_PAD_Y = 4; // vertical click leeway around each strip
const SEG_GAP = 2; // horizontal gap between cluster segments

// ─── Layout constants (time mode) ────────────────────────────
const TIME_LEFT_GUTTER = 36; // portrait: reserved column for tick labels
const TIME_BOTTOM_GUTTER = 16; // landscape: reserved row for tick labels
const TIME_DOT_EDGE_PAD = 8; // keep dots away from gutter / opposite edge
const DOT_R = 3.5; // dot radius (diameter 7px)
const DOT_HIT_PAD = 3; // pointer leeway around each dot
const JITTER_STEP = 2; // ±2px Y per collision step
const JITTER_MAX = 6; // give up & accept overlap past this
// Symmetric probe offsets in collision-resolution order: ideal first, then
// ±2, ±4, ±6.  If every probe collides, the last entry is used (overlap
// accepted) — practically unreachable with the 50-session cap.
const _JITTER_PROBES = [0, JITTER_STEP, -JITTER_STEP, 2 * JITTER_STEP, -2 * JITTER_STEP, JITTER_MAX, -JITTER_MAX];
// Hybrid time mapping: ageMs<DAY occupies the first 40% of the time axis,
// DAY<age<WEEK the next 30%, age>WEEK the last 30% (sqrt-compressed, floor
// at 30d).  Returned offset is in [0, 1]; orientation maps it to x or y.
const TIME_DAY = 24 * 3600 * 1000;
const TIME_WEEK = 7 * TIME_DAY;
const TIME_HOUR = 3600 * 1000;
const TICKS_MIN_SPAN_MS = 60_000; // hide ticks for sub-minute spans

// ─── Module state ─────────────────────────────────────────────
let canvas,
	ctx,
	dpr = 1;
let sessions = []; // { id, filename, gender_score, confidence, label, color }
let selectedId = null;
let hoveredId = null;
let _onDotClick = null;
let _onDeselect = null;

// Cross-fade transition between modes.  When `_transitionStart != null`, the
// RAF loop drives the canvas; any other path that wants to redraw (data
// change, resize, hover, theme) calls `_draw`, which snaps and cancels.
const TRANSITION_MS = 240;
let _animRaf = null;
let _transitionStart = null;
let _transitionFrom = null;
let _transitionTo = null;

// Tooltip (time mode only): cached element + hover-debounce timer + pending
// id so a fast mouse-flick across dots doesn't show the wrong tooltip.
const TOOLTIP_DELAY_MS = 240;
let _tooltipEl = null;
let _hoverTimer = null;
let _pendingTooltipId = null;

// ─── Init ─────────────────────────────────────────────────────
export function initScatter(canvasEl, { onDotClick, onDeselect } = {}) {
	canvas = canvasEl;
	_onDotClick = onDotClick;
	_onDeselect = onDeselect;
	_tooltipEl = document.getElementById("scatter-tooltip");

	canvas.addEventListener("click", _handleClick);
	canvas.addEventListener("mousemove", _handleHover);
	canvas.addEventListener("mouseleave", () => {
		hoveredId = null;
		_hideTooltip();
		_draw();
	});

	const ro = new ResizeObserver(() => _resize());
	ro.observe(canvas.parentElement);
	_resize();

	// Drive the cross-fade ourselves: main.js doesn't need to call
	// `redraw()` after a mode change, the transition handler does it.
	// Hide any visible tooltip immediately so it doesn't trail the old mode.
	onScatterModeChange((next, prev) => {
		_hideTooltip();
		_startTransition(prev, next);
	});
}

// ─── Public API ───────────────────────────────────────────────
export function addSession(session) {
	sessions = sessions.filter((s) => s.id !== session.id);
	sessions.push(session);
	_hideTooltip();
	_draw();
}

export function loadAllSessions(arr) {
	sessions = arr.slice();
	_hideTooltip();
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
	_hideTooltip();
	_draw();
}

export function removeSession(id) {
	sessions = sessions.filter((s) => s.id !== id);
	if (selectedId === id) selectedId = null;
	hoveredId = null;
	_hideTooltip();
	_draw();
}

export function redraw() {
	_hideTooltip();
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

/** Score-mode layout: canvas geometry, adaptive strip thickness, and the
 *  per-session horizontal segment. Sessions whose score Y values fall within
 *  CLUSTER_GAP of one another form a cluster and split the plot width equally,
 *  so overlapping bands stay individually clickable instead of stacking. */
function _layoutScore() {
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

/** Map age-in-ms to a [0, 1] offset along the time axis (0 = newest end,
 *  1 = oldest end).  Same hybrid 40/30/30 curve as before — orientation-
 *  agnostic now: portrait uses it for Y (top→bottom), landscape for X
 *  (right→left). */
function _ageRatio(ageMs) {
	const a = Math.max(0, ageMs);
	if (a <= TIME_DAY) return (a / TIME_DAY) * 0.4;
	if (a <= TIME_WEEK) return 0.4 + ((a - TIME_DAY) / (TIME_WEEK - TIME_DAY)) * 0.3;
	const excessDays = (a - TIME_WEEK) / TIME_DAY;
	return 0.7 + Math.min(1, Math.sqrt(excessDays / 30)) * 0.3;
}

/** Map score 0–100 to a [0, 1] offset along the score axis. */
function _scoreRatio(score) {
	return Math.max(0, Math.min(100, score)) / 100;
}

/** Time-mode layout: per-session (x, y) plus dot-region geometry and the
 *  current orientation so the renderer can place ticks and reference lines.
 *  When the canvas is wider than tall we swap axes — X carries time
 *  (oldest left → newest right), Y carries score (♂ bottom → ♀ top); ticks
 *  move from the left gutter to a bottom gutter.  Collision Y-jitter is
 *  unchanged (still on the canvas Y axis regardless of orientation). */
function _layoutTime() {
	const W = _w(),
		H = _h();
	const plotLeft = PAD.left;
	const plotRight = W - PAD.right;
	const plotTop = PAD.top;
	const plotBottom = H - PAD.bottom;
	const now = Date.now();
	const landscape = W > H;

	// Mirror the gutter on the opposite side so the dot region (and therefore
	// the score=50% reference line) sits at the geometric center of the plot,
	// aligned with the bg gradient's midpoint.  The "balance" pad on the
	// opposite side stays empty visually but the gradient fills it.
	let dotLeft, dotRight, dotTop, dotBottom;
	if (landscape) {
		dotLeft = plotLeft + TIME_DOT_EDGE_PAD;
		dotRight = plotRight - TIME_DOT_EDGE_PAD;
		dotTop = plotTop + TIME_BOTTOM_GUTTER + TIME_DOT_EDGE_PAD;
		dotBottom = plotBottom - TIME_BOTTOM_GUTTER - TIME_DOT_EDGE_PAD;
	} else {
		dotLeft = plotLeft + TIME_LEFT_GUTTER + TIME_DOT_EDGE_PAD;
		dotRight = plotRight - TIME_LEFT_GUTTER - TIME_DOT_EDGE_PAD;
		dotTop = plotTop;
		dotBottom = plotBottom;
	}
	const dW = dotRight - dotLeft;
	const dH = dotBottom - dotTop;

	const sorted = sessions.slice().sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0));
	const dots = new Map();
	const placed = [];
	const minDist = DOT_R * 2 + 1;

	for (const s of sorted) {
		const ageMs = Math.max(0, now - (s.createdAt ?? now));
		const ar = _ageRatio(ageMs);
		const sr = _scoreRatio(_getScore(s));
		const baseX = landscape ? dotRight - ar * dW : dotLeft + sr * dW;
		const baseY = landscape ? dotBottom - sr * dH : dotTop + ar * dH;
		let x = baseX;
		let y = baseY;
		for (const dy of _JITTER_PROBES) {
			y = baseY + dy;
			const collides = placed.some((p) => {
				const px = p.x - x;
				const py = p.y - y;
				return px * px + py * py < minDist * minDist;
			});
			if (!collides) break;
		}
		dots.set(s.id, { x, y });
		placed.push({ x, y });
	}

	return { plotLeft, plotRight, plotTop, plotBottom, dotLeft, dotRight, dotTop, dotBottom, now, landscape, dots };
}

/** Pick 2–4 relative-time tick labels based on data span.  Each entry is
 *  `{ageMs, label}`; render Y is computed from `_timeToY(now-ageMs, ...)`. */
function _getTimeTicks(spanMs) {
	if (spanMs < TIME_HOUR) {
		return [
			{ ageMs: 0, label: t("scatter.tick.justNow") },
			{ ageMs: 30 * 60 * 1000, label: t("scatter.tick.minutesAgoFmt", { n: 30 }) },
		];
	}
	if (spanMs < TIME_DAY) {
		return [
			{ ageMs: 0, label: t("scatter.tick.justNow") },
			{ ageMs: 6 * TIME_HOUR, label: t("scatter.tick.hoursAgoFmt", { n: 6 }) },
			{ ageMs: TIME_DAY, label: t("scatter.tick.dayAgo") },
		];
	}
	if (spanMs < TIME_WEEK) {
		return [
			{ ageMs: 0, label: t("scatter.tick.justNow") },
			{ ageMs: TIME_DAY, label: t("scatter.tick.dayAgo") },
			{ ageMs: 3 * TIME_DAY, label: t("scatter.tick.daysAgoFmt", { n: 3 }) },
			{ ageMs: TIME_WEEK, label: t("scatter.tick.weekAgo") },
		];
	}
	return [
		{ ageMs: 0, label: t("scatter.tick.justNow") },
		{ ageMs: TIME_DAY, label: t("scatter.tick.dayAgo") },
		{ ageMs: TIME_WEEK, label: t("scatter.tick.weekAgo") },
		{ ageMs: 30 * TIME_DAY, label: t("scatter.tick.monthAgo") },
	];
}

// Render time mode (orientation-aware: Y=time/X=score in portrait, swapped
// in landscape).  See `_drawScoreMode` for the alpha-multiplier convention.
function _drawTimeMode(alpha) {
	if (!canvas || !ctx || alpha <= 0) return;

	const { plotLeft, plotRight, plotTop, plotBottom, dotLeft, dotRight, dotTop, dotBottom, now, landscape, dots } =
		_layoutTime();
	const dW = dotRight - dotLeft;
	const dH = dotBottom - dotTop;

	ctx.save();
	ctx.globalAlpha = alpha;

	// ── Background gradient — score axis runs ♂ blue → ♀ pink ──
	// Spans the full plot (not just the dot region) so the gutter / edge pads
	// participate in the wash instead of staying blank.  Middle stop is held
	// near the end-stop opacity — score mode can drop the middle to ~0.02
	// because its full-width strips dominate visually, but time mode's tiny
	// dots leave the bg as the main fill, and a low-opacity middle reads as
	// two disconnected bars.
	const bg = landscape
		? ctx.createLinearGradient(0, plotBottom, 0, plotTop)
		: ctx.createLinearGradient(plotLeft, 0, plotRight, 0);
	bg.addColorStop(0, "rgba(59,130,246,0.10)");
	bg.addColorStop(0.5, "rgba(167,139,250,0.08)");
	bg.addColorStop(1, "rgba(244,63,94,0.10)");
	ctx.fillStyle = bg;
	ctx.fillRect(plotLeft, plotTop, plotRight - plotLeft, plotBottom - plotTop);

	// ── Neutral reference line at score=50%, perpendicular to score axis ──
	ctx.save();
	ctx.strokeStyle = "rgba(128,128,128,0.35)";
	ctx.lineWidth = 1;
	ctx.beginPath();
	if (landscape) {
		const cy = (dotTop + dotBottom) / 2;
		ctx.moveTo(dotLeft, cy);
		ctx.lineTo(dotRight, cy);
	} else {
		const cx = (dotLeft + dotRight) / 2;
		ctx.moveTo(cx, dotTop);
		ctx.lineTo(cx, dotBottom);
	}
	ctx.stroke();
	ctx.restore();

	// ── Tick labels — left gutter (portrait) or bottom gutter (landscape) ──
	if (sessions.length > 0) {
		const oldestCreatedAt = sessions.reduce((acc, s) => Math.min(acc, s.createdAt ?? now), Number.POSITIVE_INFINITY);
		const spanMs = Math.max(0, now - oldestCreatedAt);
		if (spanMs > TICKS_MIN_SPAN_MS) {
			const ticks = _getTimeTicks(spanMs).filter((tk) => tk.ageMs <= spanMs * 1.05);
			ctx.save();
			ctx.fillStyle = "rgba(128,128,128,0.7)";
			ctx.font = "10px system-ui, -apple-system, sans-serif";
			if (landscape) {
				ctx.textBaseline = "alphabetic";
				ctx.textAlign = "center";
				const tickY = plotBottom - 2;
				for (const tk of ticks) {
					ctx.fillText(tk.label, dotRight - _ageRatio(tk.ageMs) * dW, tickY);
				}
			} else {
				ctx.textBaseline = "middle";
				ctx.textAlign = "left";
				for (const tk of ticks) {
					ctx.fillText(tk.label, plotLeft, dotTop + _ageRatio(tk.ageMs) * dH);
				}
			}
			ctx.restore();
		}
	}

	// ── Dots ────────────────────────────────────────────────────
	for (const s of sessions) {
		const dot = dots.get(s.id);
		if (!dot) continue;
		const score = _getScore(s);
		const isSelected = s.id === selectedId;
		const isHovered = s.id === hoveredId;
		const color = _scoreToColor(score);

		if (isSelected || isHovered) {
			ctx.save();
			ctx.shadowColor = color;
			ctx.shadowBlur = isSelected ? 10 : 6;
		}

		ctx.fillStyle = _withAlpha(color, isSelected ? 1 : isHovered ? 0.95 : 0.78);
		ctx.beginPath();
		ctx.arc(dot.x, dot.y, DOT_R, 0, Math.PI * 2);
		ctx.fill();

		if (isSelected) {
			ctx.strokeStyle = "rgba(255,255,255,0.9)";
			ctx.lineWidth = 1.5;
			ctx.stroke();
		}

		if (isSelected || isHovered) ctx.restore();
	}

	ctx.restore();
}

// ─── Draw ─────────────────────────────────────────────────────
// Dispatcher: clears canvas once, then composes mode renderers with a global
// alpha each.  One clear per frame is mandatory — `clearRect` ignores
// `globalAlpha`, so cross-fade can't be done by re-clearing.  Any non-anim
// caller (data change, resize, hover) snaps mid-flight transitions.
function _draw() {
	if (!canvas || !ctx) return;
	if (_transitionStart != null) _cancelTransition();
	const W = _w(),
		H = _h();
	ctx.clearRect(0, 0, W, H);
	_drawByMode(getScatterMode(), 1);
}

function _drawByMode(mode, alpha) {
	if (mode === "time") _drawTimeMode(alpha);
	else _drawScoreMode(alpha);
}

function _easeInOut(x) {
	return x < 0.5 ? 2 * x * x : 1 - ((-2 * x + 2) * (-2 * x + 2)) / 2;
}

function _startTransition(prevMode, nextMode) {
	if (!canvas || !ctx) return;
	if (prevMode === nextMode) {
		_draw();
		return;
	}
	if (_animRaf != null) cancelAnimationFrame(_animRaf);
	_transitionStart = performance.now();
	_transitionFrom = prevMode;
	_transitionTo = nextMode;
	_animRaf = requestAnimationFrame(_animLoop);
}

function _animLoop() {
	if (_transitionStart == null) return;
	const elapsed = performance.now() - _transitionStart;
	const tNorm = Math.min(1, elapsed / TRANSITION_MS);
	const eased = _easeInOut(tNorm);

	const W = _w(),
		H = _h();
	ctx.clearRect(0, 0, W, H);
	_drawByMode(_transitionFrom, 1 - eased);
	_drawByMode(_transitionTo, eased);

	if (tNorm < 1) {
		_animRaf = requestAnimationFrame(_animLoop);
	} else {
		_animRaf = null;
		_transitionStart = null;
		_transitionFrom = null;
		_transitionTo = null;
	}
}

function _cancelTransition() {
	if (_animRaf != null) cancelAnimationFrame(_animRaf);
	_animRaf = null;
	_transitionStart = null;
	_transitionFrom = null;
	_transitionTo = null;
}

// Render score mode (Y=性别分数, full-width strips) into the current canvas.
// `alpha` multiplies into every fill/stroke via `ctx.globalAlpha`; pass 1 for
// solo render, < 1 during a cross-fade.  Caller is responsible for clearRect.
function _drawScoreMode(alpha) {
	if (!canvas || !ctx || alpha <= 0) return;

	const { plotLeft, plotRight, plotTop, plotBottom, plotW, STRIP_H, segments } = _layoutScore();

	ctx.save();
	ctx.globalAlpha = alpha;

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

	ctx.restore();
}

// ─── Hit test ─────────────────────────────────────────────────
function _hitTest(ex, ey) {
	return getScatterMode() === "time" ? _hitTestTime(ex, ey) : _hitTestScore(ex, ey);
}

function _hitTestScore(ex, ey) {
	const { plotLeft, plotRight, segments, STRIP_H } = _layoutScore();
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

function _hitTestTime(ex, ey) {
	const { dots } = _layoutTime();
	const r = DOT_R + DOT_HIT_PAD;
	const r2 = r * r;
	for (let i = 0; i < sessions.length; i++) {
		const s = sessions[i];
		const d = dots.get(s.id);
		if (!d) continue;
		const dx = d.x - ex;
		const dy = d.y - ey;
		if (dx * dx + dy * dy <= r2) return s;
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
	_hideTooltip();
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
	if (getScatterMode() === "time" && hit) {
		_scheduleTooltip(hit);
	} else {
		_hideTooltip();
	}
}

// ─── Tooltip (time mode) ──────────────────────────────────────
function _scheduleTooltip(session) {
	if (_pendingTooltipId === session.id) return;
	_pendingTooltipId = session.id;
	if (_hoverTimer) clearTimeout(_hoverTimer);
	_hoverTimer = setTimeout(() => {
		_hoverTimer = null;
		if (_pendingTooltipId === session.id && getScatterMode() === "time") {
			_showTooltip(session);
		}
	}, TOOLTIP_DELAY_MS);
}

function _hideTooltip() {
	if (_hoverTimer) clearTimeout(_hoverTimer);
	_hoverTimer = null;
	_pendingTooltipId = null;
	_tooltipEl?.classList.remove("visible");
}

function _showTooltip(session) {
	if (!_tooltipEl || !canvas?.parentElement) return;
	const { dots } = _layoutTime();
	const dot = dots.get(session.id);
	if (!dot) return;

	// `getLang()` already returns BCP 47 ("zh-CN" / "en-US" / "fr-FR"), pass straight in.
	const fmt = new Intl.DateTimeFormat(getLang(), {
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
	});
	const dateStr = session.createdAt ? fmt.format(new Date(session.createdAt)) : "";
	const score = Math.round(_getScore(session));

	_tooltipEl.querySelector(".scatter-tooltip-time").textContent = dateStr;
	_tooltipEl.querySelector(".scatter-tooltip-name").textContent = session.filename ?? "";
	_tooltipEl.querySelector(".scatter-tooltip-score").textContent = t("scatter.tooltip.scoreFmt", { n: score });

	// Make visible (offscreen) so we can measure, then position.
	_tooltipEl.style.left = "0px";
	_tooltipEl.style.top = "0px";
	_tooltipEl.classList.add("visible");
	const wrapW = canvas.parentElement.clientWidth;
	const wrapH = canvas.parentElement.clientHeight;
	const ttW = _tooltipEl.offsetWidth;
	const ttH = _tooltipEl.offsetHeight;

	let left = dot.x + 8;
	let top = dot.y - ttH - 8;
	if (left + ttW > wrapW - 4) left = dot.x - ttW - 8;
	if (left < 4) left = 4;
	if (top < 4) top = dot.y + 8;
	if (top + ttH > wrapH - 4) top = wrapH - ttH - 4;

	_tooltipEl.style.left = `${left}px`;
	_tooltipEl.style.top = `${top}px`;
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
