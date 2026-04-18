/**
 * phone-timeline.js — Orchestrator for the phone-level interactive timeline.
 *
 * Renders beneath the waveform when Engine C data is available:
 *   - SVG resonance heatmap band (HeatmapBand)
 *   - Clickable hanzi transcript row with karaoke sync (TranscriptRow)
 *   - Dual-axis pitch+resonance trend chart (TrendChart)
 *   - Playback synchronization hub (PlaybackSync)
 *
 * Feature-flagged via vga.timeline (see feature-flag.js).
 */

import { createBus } from "./bus.js";
import { renderFallback, renderLowPhoneBanner, renderNoSpeech } from "./engine-c-fallback.js";
import { HeatmapBand } from "./heatmap-band.js";
import { groupPhonesByChar } from "./phone-utils.js";
import { PlaybackSync } from "./playback-sync.js";
import { TranscriptRow } from "./transcript-row.js";
import { TrendChart } from "./trend-chart.js";

const LOW_PHONE_THRESHOLD = 8;

export class PhoneTimeline {
	/**
	 * @param {{ container: HTMLElement, wavesurfer: object|null }} opts
	 */
	constructor({ container, wavesurfer }) {
		this.root = container;
		this.ws = wavesurfer;
		this._rendered = false;
		this._chars = [];
		this._bus = null;
		this._sync = null;
		this._heatmap = null;
		this._transcript = null;
		this._trendChart = null;
	}

	/** Show the loading skeleton. */
	setLoading() {
		this._destroyChildren();
		this.root.innerHTML = `
			<div class="vga-timeline" data-state="skeleton">
				<div class="vga-skel vga-skel--band"></div>
				<div class="vga-skel vga-skel--row"></div>
				<div class="vga-skel vga-skel--chart"></div>
			</div>`;
		this._rendered = true;
	}

	/**
	 * Receive Engine C data and render the full timeline.
	 * @param {object|null} engineC — summary.engine_c from the API response
	 */
	setData(engineC) {
		if (!this._rendered) return;
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

		// Group phones into character cells
		this._chars = groupPhonesByChar(engineC.phones);

		// Determine duration from the last phone's end time
		const lastPhone = engineC.phones[engineC.phones.length - 1];
		const duration = lastPhone ? lastPhone.end : 0;

		// Build layout containers
		timeline.dataset.state = "ready";
		timeline.innerHTML = `
			<div class="vga-timeline__band"></div>
			<div class="vga-timeline__transcript"></div>
			<div class="vga-timeline__chart"></div>`;

		// Low phone count warning
		if (engineC.phone_count < LOW_PHONE_THRESHOLD) {
			renderLowPhoneBanner(timeline, engineC.phone_count);
		}

		// Create shared state + bus
		const reducedMotion =
			matchMedia("(prefers-reduced-motion: reduce)").matches ||
			localStorage.getItem("vga.reducedMotion") === "1";

		const state = {
			chars: this._chars,
			currentTime: 0,
			activeCharIdx: -1,
			isPlaying: false,
			autoScroll: true,
			reducedMotion,
		};

		this._bus = createBus();

		// Mount children
		const bandEl = timeline.querySelector(".vga-timeline__band");
		const transcriptEl = timeline.querySelector(".vga-timeline__transcript");
		const chartEl = timeline.querySelector(".vga-timeline__chart");

		// Heatmap band (uses raw phones for per-phone granularity)
		this._heatmap = new HeatmapBand();
		this._heatmap.mount({
			container: bandEl,
			phones: engineC.phones,
			duration,
			bus: this._bus,
		});

		// Transcript row (uses grouped chars)
		this._transcript = new TranscriptRow();
		this._transcript.mount({
			container: transcriptEl,
			chars: this._chars,
			bus: this._bus,
			state,
		});

		// Trend chart
		this._trendChart = new TrendChart();
		this._trendChart.mount({
			container: chartEl,
			chars: this._chars,
			duration,
			bus: this._bus,
		});

		// Playback sync (connects WaveSurfer ↔ bus)
		if (this.ws) {
			this._sync = new PlaybackSync({ wavesurfer: this.ws, state, bus: this._bus });
			this._sync.init();
		}

		// Announce completion to screen readers
		this._announceReady(this._chars.filter((c) => c.char).length);
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
		this._destroyChildren();
		this.root.innerHTML = "";
		this._rendered = false;
		this._chars = [];
	}

	/** Tear down child components without clearing the root container. */
	_destroyChildren() {
		this._sync?.destroy();
		this._heatmap?.destroy();
		this._transcript?.destroy();
		this._trendChart?.destroy();
		this._bus?.destroy();
		this._sync = null;
		this._heatmap = null;
		this._transcript = null;
		this._trendChart = null;
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
		announcer.textContent = `分析完成，共 ${charCount} 个字`;
	}
}
