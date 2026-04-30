/**
 * phone-timeline.js — Orchestrator for the phone-level interactive timeline.
 *
 * Renders beneath the waveform when Engine C data is available:
 *   - SVG pitch heatmap band (HeatmapBand, keyed on pitch Hz)
 *   - Clickable hanzi transcript row with karaoke sync (TranscriptRow)
 *   - SVG resonance heatmap band (HeatmapBand, keyed on resonance 0–1)
 *   - Playback synchronization hub (PlaybackSync)
 *
 * Feature-flagged via vga.timeline (see feature-flag.js).
 */

import { createBus } from "./bus.js";
import { divergingPitch, divergingResonance } from "./diverging.js";
import { renderFallback, renderLowPhoneBanner, renderNoSpeech } from "./engine-c-fallback.js";
import { GenderLegend } from "./gender-legend.js";
import { HeatmapBand } from "./heatmap-band.js";
import { getLang, t } from "./i18n.js";
import { findSentenceIdx, groupCharsByWeight, groupPhonesByChar } from "./phone-utils.js";
import { PlaybackSync } from "./playback-sync.js";
import { TranscriptRow } from "./transcript-row.js";

const LOW_PHONE_THRESHOLD = 8;

// Weight-based pagination: each page's Σ weight must fit `weightBudget`.
// weightBudget ≈ contentWidth / PX_PER_UNIT.  Per cell, weight is 1 for a
// single CJK hanzi and clamp(letter_count, 2, 10) for an English word (see
// _cellWeight in phone-utils.js) — so one unit ≈ the width a single hanzi
// or a single English letter should occupy on screen.  PX_PER_UNIT is chosen
// per-language: CJK renders at 28 px glyph so 32 px/unit leaves breathing
// room; English at ~18 px/letter packs 4-5 avg words into ~500 px.
// MIN_UNITS_PER_PAGE guards extremely narrow containers from producing
// nav-spamming single-word pages.
const PX_PER_UNIT_CJK = 32;
const PX_PER_UNIT_EN = 18;
const MIN_UNITS_PER_PAGE_CJK = 6;
const MIN_UNITS_PER_PAGE_EN = 6;

const pitchTitleFn = (p) => {
	const charLabel = p.char || "\u2205";
	// Show the phone's raw measured pitch in the tooltip (honest per-phone
	// read-out) even though the fill color comes from the char-level value.
	const raw = p.pitch != null && p.pitch > 0 ? `${p.pitch.toFixed(0)} Hz` : "\u2014";
	const useInterp = p.charPitch != null && (p.pitch == null || p.pitch <= 0);
	return useInterp
		? t("timeline.pitchTitleInterp", { char: charLabel, phone: p.phone, raw, interp: p.charPitch.toFixed(0) })
		: t("timeline.pitchTitle", { char: charLabel, phone: p.phone, raw });
};

const resonanceTitleFn = (p) => {
	const charLabel = p.char || "\u2205";
	const resLabel = p.resonance != null ? p.resonance.toFixed(2) : "\u2014";
	return t("timeline.resonanceTitle", { char: charLabel, phone: p.phone, res: resLabel });
};

export class PhoneTimeline {
	/**
	 * @param {{ container: HTMLElement, wavesurfer: object|null }} opts
	 */
	constructor({ container, wavesurfer }) {
		this.root = container;
		this.ws = wavesurfer;
		this._rendered = false;
		this._chars = [];
		this._sentences = [];
		this._bus = null;
		this._sync = null;
		this._pitchBand = null;
		this._resonanceBand = null;
		this._transcript = null;
		this._legend = null;
		this._onCursorMove = null;
		this._onCursorLeave = null;
		this._cursorRowsEl = null;
		this._resizeObs = null;
		this._state = null;
		this._weightBudget = 0;
	}

	/** Show the loading skeleton. */
	setLoading() {
		this._resizeObs?.disconnect();
		this._resizeObs = null;
		this._destroyChildren();
		this.root.innerHTML = `
			<div class="vga-timeline" data-state="skeleton">
				<div class="vga-skel vga-skel--band"></div>
				<div class="vga-skel vga-skel--row"></div>
				<div class="vga-skel vga-skel--band"></div>
			</div>`;
		this._rendered = true;
	}

	/**
	 * Receive Engine C data and render the full timeline.
	 * @param {object|null} engineC — summary.engine_c from the API response
	 */
	setData(engineC) {
		if (!this._rendered) return;
		this._resizeObs?.disconnect();
		this._resizeObs = null;
		this._destroyChildren();

		const timeline = this.root.querySelector(".vga-timeline");
		if (!timeline) return;

		// No data at all → failure fallback
		if (!engineC) {
			timeline.dataset.state = "error";
			renderFallback(timeline);
			return;
		}

		// Empty transcript → no-speech fallback
		if (!engineC.transcript?.trim()) {
			timeline.dataset.state = "empty";
			renderNoSpeech(timeline);
			return;
		}

		// No phones → failure (MFA likely failed)
		if (!engineC.phones?.length) {
			timeline.dataset.state = "error";
			renderFallback(timeline);
			return;
		}

		// Group phones into character cells.  Pagination happens below, after
		// the layout DOM is in place so we can measure the band's real width.
		this._chars = groupPhonesByChar(engineC.phones);
		this._engineC = engineC;

		// Dev-mode scroll monitor: verify no unexpected scroll occurs during
		// playback.  The app uses a fixed-height .app-layout with the actual
		// scrolling happening inside .panel-center (window.scrollY stays 0
		// regardless), so we must monitor the panel's scrollTop — not the
		// window's.  Console check: `window._scrollMonitor` — if min === max
		// === scrollAtLoad, nothing scrolled the panel.
		if (import.meta.env.DEV && typeof window !== "undefined") {
			const panel = document.querySelector(".panel-center");
			const y = panel ? panel.scrollTop : 0;
			window._scrollMonitor = {
				target: panel ? ".panel-center" : "window",
				scrollAtLoad: y,
				min: y,
				max: y,
			};
			if (panel && !window._scrollMonitorInstalled) {
				window._scrollMonitorInstalled = true;
				panel.addEventListener(
					"scroll",
					() => {
						const m = window._scrollMonitor;
						if (!m) return;
						const cy = panel.scrollTop;
						if (cy < m.min) m.min = cy;
						if (cy > m.max) m.max = cy;
					},
					{ passive: true },
				);
			}
		}

		// Build layout containers.  Sandwich order (inside .vga-timeline__rows):
		//   [音高] pitch band
		//   [    ] transcript (readout + hanzi)
		//   [共鸣] resonance band
		// Each row is [label slot | content slot]; the label slot has a fixed
		// width so the three content slots line up to the pixel — preserving
		// time-alignment between the two bands and the hanzi above.  The nav
		// (← 7/8 →) and the single shared palette legend both sit below, so
		// nothing interrupts the sandwich.
		timeline.dataset.state = "ready";
		timeline.innerHTML = `
			<div class="vga-timeline__readout-row"></div>
			<div class="vga-timeline__rows">
				<div class="vga-timeline__row vga-timeline__row--pitch">
					<span class="vga-timeline__label">${t("timeline.pitch")}</span>
					<div class="vga-timeline__band vga-timeline__band--pitch"></div>
				</div>
				<div class="vga-timeline__row vga-timeline__row--transcript">
					<span class="vga-timeline__label" aria-hidden="true"></span>
					<div class="vga-timeline__transcript"></div>
				</div>
				<div class="vga-timeline__row vga-timeline__row--resonance">
					<span class="vga-timeline__label">${t("timeline.resonance")}</span>
					<div class="vga-timeline__band vga-timeline__band--resonance"></div>
				</div>
				<div class="vga-timeline__cursor" aria-hidden="true"></div>
			</div>
			<div class="vga-timeline__nav-row"></div>
			<div class="vga-timeline__footer">
				<div class="vga-timeline__footer-legend"></div>
			</div>`;

		// Low phone count warning
		if (engineC.phone_count < LOW_PHONE_THRESHOLD) {
			renderLowPhoneBanner(timeline, engineC.phone_count);
		}

		// Measure real content width now that the layout DOM exists, pack
		// chars into weight-budgeted pages, log dev diagnostics, then mount
		// the interactive children.  _mountInteractive is reused by
		// _maybeReslice on resize.
		this._weightBudget = this._computeWeightBudget();
		this._sentences = groupCharsByWeight(this._chars, { weightBudget: this._weightBudget });
		this._logDevDiagnostic();
		this._mountInteractive({ initialSentenceIdx: 0 });

		// Rebuild pagination when content width crosses a char boundary.
		const pitchBandEl = timeline.querySelector(".vga-timeline__band--pitch");
		if (pitchBandEl) {
			this._resizeObs = new ResizeObserver(() => this._maybeReslice());
			this._resizeObs.observe(pitchBandEl);
		}
	}

	/**
	 * Measure content-slot width and derive `⌊w / PX_PER_UNIT⌋` weight budget.
	 * Falls back through rows → root when an inner slot hasn't laid out yet.
	 */
	_computeWeightBudget() {
		const pitchBand = this.root.querySelector(".vga-timeline__band--pitch");
		const rowsEl = this.root.querySelector(".vga-timeline__rows");
		const w = pitchBand?.clientWidth || rowsEl?.clientWidth || this.root.clientWidth || 320;
		// Latin scripts (en-US, fr-FR) share word-spaced layout; zh-CN uses CJK packing.
		// Positive list rather than `!== "zh-CN"` so a future CJK locale (ja-JP, ko-KR)
		// doesn't silently inherit Latin layout.
		const isLatin = ["en-US", "fr-FR"].includes(getLang());
		const pxPer = isLatin ? PX_PER_UNIT_EN : PX_PER_UNIT_CJK;
		const minUnits = isLatin ? MIN_UNITS_PER_PAGE_EN : MIN_UNITS_PER_PAGE_CJK;
		return Math.max(minUnits, Math.floor(w / pxPer));
	}

	/**
	 * Re-pack chars when the budget changes on resize.  Destroys + re-mounts
	 * the interactive children so their internal sentence caches stay in sync;
	 * the ResizeObserver's `next === current` early-return keeps this from
	 * running on every px of resize drag.
	 */
	_maybeReslice() {
		const next = this._computeWeightBudget();
		if (next === this._weightBudget || !this._chars?.length) return;
		this._weightBudget = next;
		this._sentences = groupCharsByWeight(this._chars, { weightBudget: next });

		// Preserve visual continuity: land on the page containing the currently
		// active char.  -1 or not-found → first page.
		const activeCharIdx = this._state?.activeCharIdx ?? -1;
		const targetPage = Math.max(0, findSentenceIdx(activeCharIdx, this._sentences));

		this._destroyChildren();
		this._logDevDiagnostic();
		this._mountInteractive({ initialSentenceIdx: targetPage });
	}

	/**
	 * Mount HeatmapBand x 2, TranscriptRow, GenderLegend, crosshair handlers
	 * and PlaybackSync against the current `this._sentences`.  Reused by
	 * initial `setData` and by `_maybeReslice`.
	 */
	_mountInteractive({ initialSentenceIdx }) {
		const timeline = this.root.querySelector(".vga-timeline");
		if (!timeline) return;
		const engineC = this._engineC;

		const reducedMotion =
			matchMedia("(prefers-reduced-motion: reduce)").matches || localStorage.getItem("vga.reducedMotion") === "1";

		const state = {
			chars: this._chars,
			sentences: this._sentences,
			currentTime: 0,
			activeCharIdx: -1,
			activeSentenceIdx: initialSentenceIdx,
			isPlaying: false,
			autoScroll: true,
			reducedMotion,
		};
		this._state = state;

		this._bus = createBus();

		const pitchBandEl = timeline.querySelector(".vga-timeline__band--pitch");
		const resonanceBandEl = timeline.querySelector(".vga-timeline__band--resonance");
		const transcriptEl = timeline.querySelector(".vga-timeline__transcript");
		const navEl = timeline.querySelector(".vga-timeline__nav-row");
		const readoutEl = timeline.querySelector(".vga-timeline__readout-row");
		const footerLegendEl = timeline.querySelector(".vga-timeline__footer-legend");
		const rowsEl = timeline.querySelector(".vga-timeline__rows");
		const cursorEl = timeline.querySelector(".vga-timeline__cursor");

		// Pitch heatmap (top).  Color per char-level aggregate (inherited by
		// all phones of that char) so unvoiced consonants don't leave gaps
		// inside otherwise-voiced hanzi.  See phone-utils._fillCharPitch.
		this._pitchBand = new HeatmapBand();
		this._pitchBand.mount({
			container: pitchBandEl,
			phones: engineC.phones,
			sentences: this._sentences,
			bus: this._bus,
			colorFn: (p) => divergingPitch(p.charPitch),
			titleFn: pitchTitleFn,
			ariaLabel: t("timeline.ariaPitch"),
			ariaDescription: t("timeline.ariaPitchDesc"),
		});

		// Transcript row (paginated by width).  navContainer / readoutContainer
		// lift the nav (below resonance) and the active-char readout (above
		// pitch band) out of the transcript wrap, keeping the three time-
		// aligned rows (pitch / hanzi / resonance) as one uninterrupted block.
		this._transcript = new TranscriptRow();
		this._transcript.mount({
			container: transcriptEl,
			chars: this._chars,
			sentences: this._sentences,
			bus: this._bus,
			state,
			navContainer: navEl,
			readoutContainer: readoutEl,
		});
		if (initialSentenceIdx > 0) this._transcript.setActiveSentenceFromUserNav(initialSentenceIdx);

		// Resonance heatmap (bottom)
		this._resonanceBand = new HeatmapBand();
		this._resonanceBand.mount({
			container: resonanceBandEl,
			phones: engineC.phones,
			sentences: this._sentences,
			bus: this._bus,
			colorFn: (p) => divergingResonance(p.resonance),
			titleFn: resonanceTitleFn,
			ariaLabel: t("timeline.ariaResonance"),
			ariaDescription: t("timeline.ariaResonanceDesc"),
		});

		this._legend = new GenderLegend();
		this._legend.mount({ container: footerLegendEl });

		// Hover crosshair: a 1px vertical line across the three rows makes the
		// "same column = same moment in time" relationship explicit.  We query
		// the content slot's left edge from the DOM (not a hardcoded offset) so
		// the line ignores the label column and only spans the data region.
		this._cursorRowsEl = rowsEl;
		if (rowsEl && cursorEl) {
			const contentRef = timeline.querySelector(".vga-timeline__row--pitch .vga-timeline__band");
			this._onCursorMove = (e) => {
				const rows = rowsEl.getBoundingClientRect();
				const content = contentRef.getBoundingClientRect();
				if (e.clientX < content.left || e.clientX > content.right) {
					cursorEl.classList.remove("visible");
					return;
				}
				cursorEl.style.left = `${e.clientX - rows.left}px`;
				cursorEl.classList.add("visible");
			};
			this._onCursorLeave = () => cursorEl.classList.remove("visible");
			rowsEl.addEventListener("mousemove", this._onCursorMove);
			rowsEl.addEventListener("mouseleave", this._onCursorLeave);
		}

		// Playback sync (connects WaveSurfer ↔ bus)
		if (this.ws) {
			this._sync = new PlaybackSync({ wavesurfer: this.ws, state, bus: this._bus });
			this._sync.init();
		}

		// Announce completion to screen readers (initial mount only).
		if (initialSentenceIdx === 0) this._announceReady(this._chars.filter((c) => c.char).length);
	}

	_logDevDiagnostic() {
		if (!(import.meta.env.DEV && typeof window !== "undefined")) return;
		let lastRealEnd = -Infinity;
		window._vgaChars = this._chars.map((c, i) => {
			const gap = c.char ? c.start - lastRealEnd : null;
			if (c.char) lastRealEnd = c.end;
			return {
				i,
				char: c.char || "·spacer·",
				start: +c.start.toFixed(3),
				end: +c.end.toFixed(3),
				dur: +(c.end - c.start).toFixed(3),
				gapToPrev: gap == null ? "" : +gap.toFixed(3),
				phoneLabels: c.phones.map((p) => p.phone).join(","),
			};
		});
		window._vgaSentences = this._sentences.map((s, i) => ({
			i,
			start: +s.start.toFixed(3),
			end: +s.end.toFixed(3),
			text: s.chars.map((c) => c.char).join(" "),
			len: s.chars.length,
			totalWeight: s.totalWeight,
		}));
		window._vgaSilenceRanges = this._engineC?.silence_ranges || [];
		// biome-ignore lint/suspicious/noConsole: dev-only diagnostic
		console.log(
			`[Engine C] ${window._vgaSentences.length} pages, weight budget ${this._weightBudget} (weight-packed, silence_ranges unused)`,
		);
		// biome-ignore lint/suspicious/noConsole: dev-only diagnostic
		console.table(window._vgaSentences);
	}

	/**
	 * 渲染完成后再补挂 wavesurfer——用于"先显示静态音素轨，音频就绪后补卡拉 OK"的流程。
	 * 重复调用或在未渲染时调用均安全（no-op）。
	 */
	attachWavesurfer(ws) {
		if (!ws || !this._rendered || this._sync || !this._state || !this._bus) return;
		this.ws = ws;
		this._sync = new PlaybackSync({ wavesurfer: ws, state: this._state, bus: this._bus });
		this._sync.init();
	}

	/** Set error/failure state. */
	setError(_err) {
		if (!this._rendered) return;
		this._destroyChildren();
		const timeline = this.root.querySelector(".vga-timeline");
		if (timeline) {
			timeline.dataset.state = "error";
			renderFallback(timeline);
		}
	}

	/** Clean up everything. */
	destroy() {
		this._resizeObs?.disconnect();
		this._resizeObs = null;
		this._destroyChildren();
		this.root.innerHTML = "";
		this._rendered = false;
		this._chars = [];
		this._engineC = null;
		this._state = null;
	}

	/** Tear down child components without clearing the root container. */
	_destroyChildren() {
		if (this._cursorRowsEl) {
			if (this._onCursorMove) this._cursorRowsEl.removeEventListener("mousemove", this._onCursorMove);
			if (this._onCursorLeave) this._cursorRowsEl.removeEventListener("mouseleave", this._onCursorLeave);
		}
		this._cursorRowsEl = null;
		this._onCursorMove = null;
		this._onCursorLeave = null;
		this._sync?.destroy();
		this._pitchBand?.destroy();
		this._resonanceBand?.destroy();
		this._transcript?.destroy();
		this._legend?.destroy();
		this._bus?.destroy();
		this._sync = null;
		this._pitchBand = null;
		this._resonanceBand = null;
		this._transcript = null;
		this._legend = null;
		this._bus = null;
	}

	/** Polite SR announcement on analysis complete. */
	_announceReady(charCount) {
		let announcer = document.getElementById("vga-timeline-announcer");
		if (!announcer) {
			announcer = document.createElement("div");
			announcer.id = "vga-timeline-announcer";
			announcer.setAttribute("role", "status");
			announcer.setAttribute("aria-live", "polite");
			announcer.className = "vga-sr-only";
			document.body.appendChild(announcer);
		}
		announcer.textContent = t("timeline.announceReady", { n: charCount });
	}
}
