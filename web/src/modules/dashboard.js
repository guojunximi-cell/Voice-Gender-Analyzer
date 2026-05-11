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
const SCHEMA_VERSION = 5;

/**
 * Single source of truth for every block: id → {defaultSize, defaultLayout?,
 * defaultVisible}. Adding a new block means: append an entry here + an HTML
 * template in `index.html` + a `dashboard.block.<id>` i18n key. The palette,
 * default layout, save/load all flow from this object.
 */
// User-tuned default layout (captured 2026-05-10 from a real session, v2).
// Visual map (12-col grid):
//   ┌──────────────┬──────────────────┐
//   │ PITCH 6×2    │ RESONANCE 6×8    │ y=0..1
//   ├────────┬─────┤                  │
//   │ STATS  │ FORM│                  │ y=2..7
//   │  4×6   │ 2×6 │                  │
//   └────────┴─────┴──────────────────┘
// NN + ADVICE hidden by default (available via "+加块" popover).
const BLOCK_REGISTRY = {
	pitch: { defaultSize: { w: 6, h: 2 }, defaultLayout: { x: 0, y: 0 }, defaultVisible: true },
	resonance: { defaultSize: { w: 6, h: 8 }, defaultLayout: { x: 6, y: 0 }, defaultVisible: true },
	stats: { defaultSize: { w: 4, h: 6 }, defaultLayout: { x: 0, y: 2 }, defaultVisible: true },
	formants: { defaultSize: { w: 2, h: 6 }, defaultLayout: { x: 4, y: 2 }, defaultVisible: true },
	nn: { defaultSize: { w: 3, h: 5 }, defaultVisible: false },
	advice: { defaultSize: { w: 3, h: 3 }, defaultVisible: false },
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
	return { version: SCHEMA_VERSION, layout, hidden };
})();

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
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) return DEFAULT_LAYOUT;
		const parsed = JSON.parse(raw);
		if (parsed?.version !== SCHEMA_VERSION) return DEFAULT_LAYOUT;
		if (!Array.isArray(parsed.layout)) return DEFAULT_LAYOUT;
		// Filter to known IDs only — defensive against stale entries
		const layout = parsed.layout.filter((it) => ALL_BLOCK_IDS.includes(it?.id));
		const hidden = ALL_BLOCK_IDS.filter((id) => !layout.some((it) => it.id === id));
		return { version: SCHEMA_VERSION, layout, hidden };
	} catch (_) {
		return DEFAULT_LAYOUT;
	}
}

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
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: SCHEMA_VERSION, layout, hidden }));
	} catch (_) {}
	_emit({ visibleIds, hidden });
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

	// Event delegation: × in any block header hides that block.
	container.addEventListener("click", (e) => {
		const btn = e.target.closest(".block-hide-btn");
		if (!btn) return;
		e.preventDefault();
		const id = btn.dataset.blockId;
		if (id) hideBlock(id);
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
	_grid.removeWidget(el, false);
	el.setAttribute("hidden", "");
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
