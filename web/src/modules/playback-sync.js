/**
 * playback-sync.js — Central bus wiring between WaveSurfer and timeline children.
 *
 * Subscribes to WaveSurfer events (audioprocess, seeking, play, pause, finish)
 * and translates them into bus events consumed by HeatmapBand, TranscriptRow,
 * and TrendChart.
 *
 * Owns the active-index computation (via findActiveIdx) so that all consumers
 * share a single binary-search-per-tick, not one each.
 */

import { findActiveIdx } from "./phone-utils.js";

export class PlaybackSync {
	/**
	 * @param {{ wavesurfer: object, state: object, bus: object }} opts
	 *   state must have: { chars, currentTime, activeCharIdx, isPlaying, autoScroll }
	 */
	constructor({ wavesurfer, state, bus }) {
		this.ws = wavesurfer;
		this.state = state;
		this.bus = bus;
		this._lastIdx = -1;
		this._unsubs = [];
	}

	init() {
		const ws = this.ws;
		const bus = this.bus;

		// WaveSurfer event subscriptions
		const onProcess = (t) => this._onTime(t);
		const onSeeking = (t) => this._onTime(t);
		const onPlay = () => {
			this.state.isPlaying = true;
			bus.emit("playStateChanged", true);
		};
		const onPause = () => {
			this.state.isPlaying = false;
			bus.emit("playStateChanged", false);
		};
		const onFinish = () => {
			this.state.isPlaying = false;
			bus.emit("playStateChanged", false);
		};

		ws.on("audioprocess", onProcess);
		ws.on("seeking", onSeeking);
		ws.on("play", onPlay);
		ws.on("pause", onPause);
		ws.on("finish", onFinish);

		this._unsubs.push(
			() => ws.un("audioprocess", onProcess),
			() => ws.un("seeking", onSeeking),
			() => ws.un("play", onPlay),
			() => ws.un("pause", onPause),
			() => ws.un("finish", onFinish),
		);

		// Bus: character click → seek wavesurfer
		const onSeek = (t) => {
			if (ws && ws.getDuration()) {
				ws.seekTo(t / ws.getDuration());
			}
		};
		bus.on("seek", onSeek);
		this._unsubs.push(() => bus.off("seek", onSeek));
	}

	_onTime(t) {
		this.state.currentTime = t;
		const idx = findActiveIdx(t, this.state.chars, this._lastIdx);
		if (idx !== this._lastIdx) {
			const prev = this._lastIdx;
			this._lastIdx = idx;
			this.state.activeCharIdx = idx;
			this.bus.emit("activeCharChanged", { prevIdx: prev, nextIdx: idx });
		}
		this.bus.emit("currentTimeChanged", t);
	}

	destroy() {
		for (const unsub of this._unsubs) unsub();
		this._unsubs = [];
	}
}
