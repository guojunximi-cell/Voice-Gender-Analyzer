/**
 * dashboard.js — Right-panel acoustic blocks.
 *
 * Blocks (pitch / formants / nn / resonance / stats / advice) live in
 * `index.html` as `.grid-stack-item[data-block-id="…"]`
 * templates. We wire them into a Gridstack v11 grid so the user can drag,
 * resize, hide, or re-add via the panel-header "+加块" popover. Drag handle
 * (`⋮⋮`) and resize handles only fade in on block hover, so the body stays
 * fully interactive (collapsibles, mode switchers, buttons all work without
 * arming an "edit mode"). We use a custom `data-block-id` attribute (not
 * Gridstack's `gs-id`) for our own DOM queries, since Gridstack strips
 * `gs-id` after init.
 *
 * BLOCK_REGISTRY (below) is the single source of truth — adding a new block
 * means: append a registry entry + an HTML template + a `dashboard.block.<id>`
 * i18n key.
 *
 * Layout state persists in localStorage `vga.acoustic.dashboard` (schema v1):
 *   { version: 1, layout: [{ id, x, y, w, h }, …], hidden: [id, …] }
 *
 * Pattern follows classify-mode.js / consonants-toggle.js — module-level
 * singleton + pub/sub.
 */

import { GridStack } from "gridstack";

import "gridstack/dist/gridstack.min.css";

const STORAGE_KEY = "vga.acoustic.dashboard";
// Bump on layout-affecting changes (registry shape, default sizes) so users
// with stale localStorage get the new defaults instead of a partially wrong
// rehydration. v3 = save() bug fix. v4/v5 = user-tuned default layouts.
// v6 = added viewportType branch (separate mobile default).
// v7 = added collapsed map (per-block fold state).
// v8 = desktop default redesigned (full-width pitch + resonance, 4-up bottom row).
const SCHEMA_VERSION = 8;
// Height to which a block shrinks when collapsed (1 cell ≈ 50px = header only).
const COLLAPSED_H = 1;
const MOBILE_BREAKPOINT = 780;

/**
 * Single source of truth for every block: id → {defaultSize, defaultLayout?,
 * defaultVisible}. Adding a new block means: append an entry here + an HTML
 * template in `index.html` + a `dashboard.block.<id>` i18n key. The palette,
 * default layout, save/load all flow from this object.
 */
// Desktop default (captured 2026-05-10 from a real user-tuned session, v4):
// pitch + resonance go full-width on top, then a wide DISTRIBUTION + three
// narrow blocks on the bottom row. All 6 blocks visible by default.
//   ┌────────────────────────────────────┐
//   │  PITCH 12×2                        │ y=0..1
//   ├────────────────────────────────────┤
//   │  RESONANCE 12×8                    │ y=2..9
//   │                                    │
//   ├────────────────┬─────┬─────┬───────┤
//   │   STATS        │FORM │ NN  │ADVICE │ y=10..14
//   │   6×5          │ 2×5 │ 2×5 │ 2×5   │
//   └────────────────┴─────┴─────┴───────┘
const BLOCK_REGISTRY = {
	pitch: { defaultSize: { w: 12, h: 2 }, defaultLayout: { x: 0, y: 0 }, defaultVisible: true },
	resonance: { defaultSize: { w: 12, h: 8 }, defaultLayout: { x: 0, y: 2 }, defaultVisible: true },
	stats: { defaultSize: { w: 6, h: 5 }, defaultLayout: { x: 0, y: 10 }, defaultVisible: true },
	formants: { defaultSize: { w: 2, h: 5 }, defaultLayout: { x: 6, y: 10 }, defaultVisible: true },
	nn: { defaultSize: { w: 2, h: 5 }, defaultLayout: { x: 8, y: 10 }, defaultVisible: true },
	advice: { defaultSize: { w: 2, h: 5 }, defaultLayout: { x: 10, y: 10 }, defaultVisible: true },
};
export const ALL_BLOCK_IDS = Object.keys(BLOCK_REGISTRY);

const DEFAULT_LAYOUT = (() => {
	const layout = [];
	const hidden = [];
	for (const [id, def] of Object.entries(BLOCK_REGISTRY)) {
		if (def.defaultVisible) {
			layout.push({ id, ...def.defaultLayout, ...def.defaultSize });
		} else {
			hidden.push(id);
		}
	}
	return { version: SCHEMA_VERSION, viewportType: "desktop", layout, hidden };
})();

// Mobile (<=780px) default — explicit single-column stack so gridstack's
// oneColumn collapse can't reorder them. Order matches the user-approved
// 2026-05-10 mobile screenshot: pitch → resonance → stats → formants.
// NN + advice stay hidden (available via "+加块" popover) just like desktop.
const DEFAULT_LAYOUT_MOBILE = {
	version: SCHEMA_VERSION,
	viewportType: "mobile",
	layout: [
		{ id: "pitch", x: 0, y: 0, w: 12, h: 2 },
		{ id: "resonance", x: 0, y: 2, w: 12, h: 8 },
		{ id: "stats", x: 0, y: 10, w: 12, h: 6 },
		{ id: "formants", x: 0, y: 16, w: 12, h: 2 },
	],
	hidden: ["nn", "advice"],
};

function _viewportType() {
	if (typeof window === "undefined") return "desktop";
	return window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`).matches ? "mobile" : "desktop";
}

function _defaultFor(vt) {
	return vt === "mobile" ? DEFAULT_LAYOUT_MOBILE : DEFAULT_LAYOUT;
}

let _grid = null;
const _listeners = new Set();
let _saveTimer = null;
let _resizeObserver = null;

// Width buckets for responsive in-block reflow (CSS reads .block-w1..w4):
//   w1: <240px — most cramped, content goes single-column
//   w2: 240-479
//   w3: 480-719
//   w4: ≥720 — widest, multi-column layouts
function _bucketForWidth(w) {
	if (w < 240) return "block-w1";
	if (w < 480) return "block-w2";
	if (w < 720) return "block-w3";
	return "block-w4";
}
const _ALL_BUCKETS = ["block-w1", "block-w2", "block-w3", "block-w4"];

function loadState() {
	const vt = _viewportType();
	const fallback = () => ({ ..._defaultFor(vt), collapsed: {} });
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) return fallback();
		const parsed = JSON.parse(raw);
		if (parsed?.version !== SCHEMA_VERSION) return fallback();
		// Pre-v6 entries lack viewportType; treat them as desktop so a desktop
		// layout opened on a phone falls through to the mobile default rather
		// than rendering 6-col blocks at 32px each.
		const storedVt = parsed.viewportType ?? "desktop";
		if (storedVt !== vt) return fallback();
		if (!Array.isArray(parsed.layout)) return fallback();
		// Filter to known IDs only — defensive against stale entries
		const layout = parsed.layout.filter((it) => ALL_BLOCK_IDS.includes(it?.id));
		const hidden = ALL_BLOCK_IDS.filter((id) => !layout.some((it) => it.id === id));
		// collapsed[id] = expanded height to restore on un-collapse. Filter to
		// IDs that are still visible so stale entries can't keep a deleted
		// block "collapsed" forever.
		const visibleIds = new Set(layout.map((it) => it.id));
		const collapsed = {};
		if (parsed.collapsed && typeof parsed.collapsed === "object") {
			for (const [id, h] of Object.entries(parsed.collapsed)) {
				if (visibleIds.has(id) && Number.isFinite(h) && h > COLLAPSED_H) {
					collapsed[id] = h;
				}
			}
		}
		return { version: SCHEMA_VERSION, viewportType: vt, layout, hidden, collapsed };
	} catch (_) {
		return fallback();
	}
}

// Track collapse state in-memory so toggleBlockCollapse can restore the
// previous expanded height. Mirrors localStorage.collapsed but lets us avoid
// re-reading on every toggle.
const _collapsedHeights = {}; // id → prevH

function _writeStateNow() {
	if (!_grid) return;
	// Read from engine.nodes directly — Gridstack's `grid.save()` mutates the
	// returned objects (deletes node.el, see gridstack.js#547), so the
	// dataset.blockId lookup would silently return undefined and filter every
	// block out, leaving us with `layout: []` + `hidden: ALL` and an empty
	// dashboard on next reload.
	const layout = _grid.engine.nodes
		.map((node) => ({
			id: node.el?.dataset?.blockId,
			x: node.x,
			y: node.y,
			w: node.w,
			h: node.h,
		}))
		.filter((it) => it.id && ALL_BLOCK_IDS.includes(it.id));
	const visibleIds = new Set(layout.map((it) => it.id));
	const hidden = ALL_BLOCK_IDS.filter((id) => !visibleIds.has(id));
	const viewportType = _viewportType();
	// Snapshot in-memory collapsed map, but only for currently-visible blocks.
	const collapsed = {};
	for (const [id, h] of Object.entries(_collapsedHeights)) {
		if (visibleIds.has(id)) collapsed[id] = h;
	}
	try {
		localStorage.setItem(
			STORAGE_KEY,
			JSON.stringify({ version: SCHEMA_VERSION, viewportType, layout, hidden, collapsed }),
		);
	} catch (_) {}
	_emit({ visibleIds, hidden, collapsed });
}

// Debounced save: gridstack 'change' fires on every pixel of a drag/resize.
// Coalesce into one localStorage write 280ms after the user lets go (still
// inside the prompt-cache 5-min window so subsequent renders aren't slow).
function saveStateDebounced() {
	if (_saveTimer) clearTimeout(_saveTimer);
	_saveTimer = setTimeout(() => {
		_saveTimer = null;
		_writeStateNow();
	}, 280);
}

// Immediate save for one-shot events (added / removed) — no need to debounce
// these since they fire once per user action.
function saveStateNow() {
	if (_saveTimer) {
		clearTimeout(_saveTimer);
		_saveTimer = null;
	}
	_writeStateNow();
}

function _emit(state) {
	for (const cb of _listeners) {
		try {
			cb(state);
		} catch (_) {}
	}
}

export function initDashboard(container) {
	if (!container) return null;
	if (_grid) return _grid;

	_grid = GridStack.init(
		{
			column: 12,
			cellHeight: 50,
			margin: 6,
			handle: ".block-drag-handle",
			resizable: { handles: "se, e, s" },
			animate: true,
			float: false,
			disableOneColumnMode: false,
			oneColumnSize: 780,
			auto: false,
		},
		container,
	);

	const state = loadState();

	// Apply saved layout: surface visible blocks, hide the rest.
	const seen = new Set();
	for (const item of state.layout) {
		const el = container.querySelector(`.grid-stack-item[data-block-id="${item.id}"]`);
		if (!el) continue;
		el.removeAttribute("hidden");
		_grid.makeWidget(el, { x: item.x, y: item.y, w: item.w, h: item.h, autoPosition: false });
		seen.add(item.id);
	}
	for (const id of ALL_BLOCK_IDS) {
		if (seen.has(id)) continue;
		const el = container.querySelector(`.grid-stack-item[data-block-id="${id}"]`);
		if (el) el.setAttribute("hidden", "");
	}

	// Re-hydrate collapsed state. Layout already has h=COLLAPSED_H for these
	// blocks (they were saved that way after the user collapsed them); we just
	// need to flip the data-collapsed flag + remember the prevH for restore.
	for (const [id, prevH] of Object.entries(state.collapsed || {})) {
		const el = container.querySelector(`.grid-stack-item[data-block-id="${id}"]`);
		if (!el || el.hasAttribute("hidden")) continue;
		_collapsedHeights[id] = prevH;
		el.setAttribute("data-collapsed", "true");
	}

	_grid.on("change", saveStateDebounced);
	_grid.on("removed", (e, items) => {
		// Stop observing removed widgets so the bucket class isn't stuck.
		for (const it of items || []) {
			if (it.el && _resizeObserver) _resizeObserver.unobserve(it.el);
		}
		saveStateNow();
	});
	_grid.on("added", (e, items) => {
		for (const it of items || []) {
			if (it.el && _resizeObserver) _resizeObserver.observe(it.el);
		}
		saveStateNow();
	});

	// Observe each block's content rect to swap responsive bucket classes.
	// Rules in main.css read .block-w1..w4 to switch between 1/2/3/4-col
	// layouts (resonance vowel grid, formants grid, etc) so content reflows
	// instead of overflowing into a scrollbar.
	if (typeof ResizeObserver !== "undefined") {
		_resizeObserver = new ResizeObserver((entries) => {
			for (const entry of entries) {
				const w = entry.contentRect.width;
				const bucket = _bucketForWidth(w);
				const el = entry.target;
				let dirty = false;
				for (const b of _ALL_BUCKETS) {
					if (b === bucket) {
						if (!el.classList.contains(b)) {
							el.classList.add(b);
							dirty = true;
						}
					} else if (el.classList.contains(b)) {
						el.classList.remove(b);
						dirty = true;
					}
				}
				// no-op if !dirty; ResizeObserver fires often
			}
		});
		for (const node of _grid.engine.nodes) {
			if (node.el) _resizeObserver.observe(node.el);
		}
	}

	// Long-press to enter edit mode: 0.8s pointerdown anywhere on a block
	// arms it so .block-drag-handle, .block-hide-btn, and .ui-resizable-handle
	// fade in. Prevents drag/resize/close affordances from cluttering the
	// reading view; works on touch (no hover required).
	const ARM_DELAY_MS = 800;
	const ARM_MOVE_TOLERANCE = 8; // px — small wiggle is OK, larger = scroll
	let armTimer = null;
	let armedEl = null;
	let armStartX = 0;
	let armStartY = 0;

	function disarmAll() {
		if (armTimer) {
			clearTimeout(armTimer);
			armTimer = null;
		}
		if (armedEl) {
			armedEl.removeAttribute("data-edit-armed");
			armedEl = null;
		}
	}

	function armBlock(el) {
		if (armedEl && armedEl !== el) armedEl.removeAttribute("data-edit-armed");
		armedEl = el;
		el.setAttribute("data-edit-armed", "true");
		// Haptic feedback on devices that support it (iOS Safari does NOT
		// expose vibrate, but Android Chrome / Firefox do). Single short pulse
		// confirms the mode change without being intrusive.
		try {
			navigator.vibrate?.(40);
		} catch (_) {}
	}

	container.addEventListener("pointerdown", (e) => {
		// Bail on interactive descendants — chevron / hide / collapse / tabs /
		// resize handles / inputs all do their own thing on click.
		if (e.target.closest("button, [role='tab'], a, input, textarea, select, .ui-resizable-handle, .gs-resize")) {
			return;
		}
		const card = e.target.closest(".grid-stack-item");
		if (!card) return;
		// New press always cancels any pending arm + disarms previously-armed
		// block so only one is "in edit mode" at a time.
		disarmAll();
		armStartX = e.clientX;
		armStartY = e.clientY;
		armTimer = setTimeout(() => {
			armTimer = null;
			armBlock(card);
		}, ARM_DELAY_MS);
	});

	const cancelPendingArm = () => {
		if (armTimer) {
			clearTimeout(armTimer);
			armTimer = null;
		}
	};
	container.addEventListener("pointerup", cancelPendingArm);
	container.addEventListener("pointercancel", () => disarmAll());
	container.addEventListener("pointermove", (e) => {
		if (!armTimer) return;
		// Treat any meaningful movement as scroll/drag intent → cancel arming.
		if (Math.abs(e.clientX - armStartX) > ARM_MOVE_TOLERANCE || Math.abs(e.clientY - armStartY) > ARM_MOVE_TOLERANCE) {
			cancelPendingArm();
		}
	});
	// Click outside any armed block disarms it.
	document.addEventListener("pointerdown", (e) => {
		if (!armedEl) return;
		if (!e.target.closest(".grid-stack-item")) disarmAll();
		else if (e.target.closest(".grid-stack-item") !== armedEl) {
			// Pointer pressed on a different block — that block gets its own
			// fresh arm sequence, which already disarms via the container
			// listener above. Nothing to do here.
		}
	});

	// Event delegation: × hides, chevron collapses/expands.
	container.addEventListener("click", (e) => {
		const hideBtn = e.target.closest(".block-hide-btn");
		if (hideBtn) {
			e.preventDefault();
			const id = hideBtn.dataset.blockId;
			if (id) hideBlock(id);
			return;
		}
		const collapseBtn = e.target.closest(".block-collapse-btn");
		if (collapseBtn) {
			e.preventDefault();
			const id = collapseBtn.dataset.blockId;
			if (id) toggleBlockCollapse(id);
		}
	});

	return _grid;
}

export function getGrid() {
	return _grid;
}

export function hideBlock(id) {
	if (!_grid) return;
	const el = _grid.el.querySelector(`.grid-stack-item[data-block-id="${id}"]`);
	if (!el) return;
	if (_resizeObserver) _resizeObserver.unobserve(el);
	// Drop any collapse state — if the user re-adds the block via the palette
	// they should get a fresh expanded view, not a phantom collapsed one.
	delete _collapsedHeights[id];
	el.removeAttribute("data-collapsed");
	_grid.removeWidget(el, false);
	el.setAttribute("hidden", "");
}

/**
 * Toggle a block between collapsed (header-only) and expanded.
 * Stores the previous height so expand restores the user's chosen size.
 */
export function toggleBlockCollapse(id) {
	if (!_grid) return;
	const el = _grid.el.querySelector(`.grid-stack-item[data-block-id="${id}"]`);
	if (!el) return;
	const node = _grid.engine.nodes.find((n) => n.el === el);
	if (!node) return;
	const isCollapsed = !!_collapsedHeights[id];
	if (isCollapsed) {
		const prevH = _collapsedHeights[id];
		delete _collapsedHeights[id];
		el.removeAttribute("data-collapsed");
		_grid.update(el, { h: prevH });
	} else {
		// Don't trap a block at h=COLLAPSED_H by collapsing-while-already-1; if
		// the user shrunk it manually to 1, restore default size on expand.
		const prevH = node.h > COLLAPSED_H ? node.h : BLOCK_REGISTRY[id]?.defaultSize?.h || 3;
		_collapsedHeights[id] = prevH;
		el.setAttribute("data-collapsed", "true");
		_grid.update(el, { h: COLLAPSED_H });
	}
	saveStateNow();
}

export function isBlockCollapsed(id) {
	return !!_collapsedHeights[id];
}

export function showBlock(id) {
	if (!_grid) return;
	const el = _grid.el.querySelector(`.grid-stack-item[data-block-id="${id}"]`);
	if (!el) return;
	const alreadyIn = _grid.engine.nodes.some((n) => n.el === el);
	if (alreadyIn) return;
	el.removeAttribute("hidden");
	const size = BLOCK_REGISTRY[id]?.defaultSize || { w: 6, h: 3 };
	_grid.makeWidget(el, { ...size, autoPosition: true });
	if (_resizeObserver) _resizeObserver.observe(el);
}

export function getHiddenBlockIds() {
	if (!_grid) return [...ALL_BLOCK_IDS];
	const visible = new Set(_grid.engine.nodes.map((n) => n.el?.dataset?.blockId).filter(Boolean));
	return ALL_BLOCK_IDS.filter((id) => !visible.has(id));
}

export function resetLayout() {
	try {
		localStorage.removeItem(STORAGE_KEY);
	} catch (_) {}
	location.reload();
}

export function onLayoutChange(cb) {
	_listeners.add(cb);
	return () => _listeners.delete(cb);
}

/**
 * Per-block content/empty toggle. Block bodies have a `[data-block-empty]`
 * placeholder + `[data-block-content]` wrapper. Render functions call this
 * to swap them based on data availability.
 */
export function setBlockHasContent(blockId, hasContent) {
	const root = document.querySelector(`.grid-stack-item[data-block-id="${blockId}"]`);
	if (!root) return;
	const empty = root.querySelector("[data-block-empty]");
	const content = root.querySelector("[data-block-content]");
	if (empty) empty.hidden = !!hasContent;
	if (content) content.hidden = !hasContent;
}
