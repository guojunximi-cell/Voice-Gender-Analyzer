/**
 * playback-sync.js — Central bus wiring between WaveSurfer and timeline children.
 *
 * Subscribes to WaveSurfer events (audioprocess, seeking, play, pause, finish)
 * and translates them into bus events consumed by the two HeatmapBand
 * instances (pitch + resonance) and TranscriptRow.
 *
 * Owns both the active-char and active-sentence computations so that all
 * consumers share a single pass per tick.
 */

import { findActiveIdx, findSentenceIdx } from "./phone-utils.js";

export class PlaybackSync {
	/**
	 * @param {{ wavesurfer: object, state: object, bus: object }} opts
	 *   state must have: { chars, sentences, currentTime, activeCharIdx,
	 *                      activeSentenceIdx, isPlaying, autoScroll }
	 */
	constructor({ wavesurfer, state, bus }) {
		this.ws = wavesurfer;
		this.state = state;
		this.bus = bus;
		this._lastCharIdx = -1;
		this._lastSentenceIdx = -1;
		this._unsubs = [];
	}

	init() {
		const ws = this.ws;
		const bus = this.bus;

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
		const charIdx = findActiveIdx(t, this.state.chars, this._lastCharIdx);
		if (charIdx !== this._lastCharIdx) {
			const prev = this._lastCharIdx;
			this._lastCharIdx = charIdx;
			this.state.activeCharIdx = charIdx;
			this.bus.emit("activeCharChanged", { prevIdx: prev, nextIdx: charIdx });

			// Did the sentence change too?
			const sentences = this.state.sentences || [];
			const sentenceIdx = findSentenceIdx(charIdx, sentences);
			if (sentenceIdx !== this._lastSentenceIdx && sentenceIdx >= 0) {
				const prevS = this._lastSentenceIdx;
				this._lastSentenceIdx = sentenceIdx;
				this.state.activeSentenceIdx = sentenceIdx;
				this.bus.emit("activeSentenceChanged", {
					prevIdx: prevS,
					nextIdx: sentenceIdx,
					sentence: sentences[sentenceIdx],
				});
			}
		}
		this.bus.emit("currentTimeChanged", t);
	}

	destroy() {
		for (const unsub of this._unsubs) unsub();
		this._unsubs = [];
	}
}
