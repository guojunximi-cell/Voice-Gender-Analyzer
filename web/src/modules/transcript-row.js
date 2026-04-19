/**
 * transcript-row.js — Sentence-paginated hanzi transcript.
 *
 * Two explicit entry points for sentence switching:
 *   setActiveSentenceFromPlayback(idx) — playback-driven, NEVER scrolls the page
 *   setActiveSentenceFromUserNav(idx)  — user clicked prev/next, may scrollIntoView
 *
 * The distinction is semantic (two named methods), not heuristic — no
 * timestamps, no flags guessing intent.  PlaybackSync calls the first,
 * nav-button handlers call the second.
 *
 * Within the currently-displayed sentence, the active-char highlight still
 * uses scrollIntoView (char-level, not window-level) so karaoke sync inside
 * the visible transcript keeps working.
 */

const FADE_MS = 150;

export class TranscriptRow {
	/**
	 * @param {{
	 *   container: HTMLElement,
	 *   chars: Array,
	 *   sentences: Array,
	 *   bus: object,
	 *   state: object,
	 * }} opts
	 */
	mount({ container, chars, sentences, bus, state }) {
		this.bus = bus;
		this.state = state;
		this.chars = chars;
		this.sentences = sentences;
		this.currentSentenceIdx = 0;
		this._activeBtn = null;

		const wrap = document.createElement("div");
		wrap.className = "vga-transcript-wrap";

		// Readout row above the transcript — shows the active char's pitch /
		// resonance numbers in one place instead of squeezing them under every
		// character.  Per-char numbers used to overlap badly when the time-
		// allocated cell was narrower than the 4-digit number's natural width;
		// pulling them into a single readout removes that constraint entirely.
		this._readout = document.createElement("div");
		this._readout.className = "vga-transcript-readout";
		this._readout.setAttribute("aria-live", "polite");
		this._readout.innerHTML =
			`<span class="vga-transcript-readout__char">\u2014</span>` +
			`<span class="vga-transcript-readout__metric"><span class="vga-transcript-readout__label">\u97f3\u9ad8</span><span class="vga-transcript-readout__pitch">\u2014</span></span>` +
			`<span class="vga-transcript-readout__metric"><span class="vga-transcript-readout__label">\u5171\u9e23</span><span class="vga-transcript-readout__res">\u2014</span></span>`;
		wrap.appendChild(this._readout);
		this._readoutChar = this._readout.querySelector(".vga-transcript-readout__char");
		this._readoutPitch = this._readout.querySelector(".vga-transcript-readout__pitch");
		this._readoutRes = this._readout.querySelector(".vga-transcript-readout__res");

		this._group = document.createElement("div");
		this._group.setAttribute("role", "group");
		this._group.className = "vga-transcript";
		wrap.appendChild(this._group);

		this._nav = this._buildNav();
		wrap.appendChild(this._nav.root);

		container.appendChild(wrap);
		this._wrap = wrap;

		this._renderSentence(0, { animate: false });
		this._installScrollWatcher(this._group);

		// Click on empty space within the transcript group → clear the active-
		// char highlight, mirroring the waveform's "click outside a segment to
		// deselect" affordance.  Visual-only: if playback is running, the next
		// audioprocess tick will re-highlight the current char.
		this._onGroupClick = (e) => {
			if (e.target.closest("button.phone")) return;
			if (!this._activeBtn) return;
			this._activeBtn.setAttribute("aria-current", "false");
			this._activeBtn.tabIndex = -1;
			this._activeBtn = null;
			this._updateReadout(null);
		};
		this._group.addEventListener("click", this._onGroupClick);

		// Active-char: visual highlight only, never scroll.  With sentence
		// pagination the entire sentence fits on screen, so there's no need
		// to scroll to the active char — and scrolling on every tick was
		// the actual cause of "page jumps during playback".
		this._onActiveChar = ({ prevIdx, nextIdx }) => this._setActiveChar(prevIdx, nextIdx);
		bus.on("activeCharChanged", this._onActiveChar);

		// Active-sentence (from playback) — explicit no-scroll path.
		this._onActiveSentence = ({ nextIdx }) => {
			if (nextIdx !== this.currentSentenceIdx) {
				this.setActiveSentenceFromPlayback(nextIdx);
			}
		};
		bus.on("activeSentenceChanged", this._onActiveSentence);

		// Return-to-current: user-initiated, treat as manual nav.
		this._returnBtn = null;
		this._onAutoScroll = (enabled) => {
			if (!this._returnBtn && !enabled) {
				this._returnBtn = document.createElement("button");
				this._returnBtn.type = "button";
				this._returnBtn.className = "vga-return-btn show";
				this._returnBtn.textContent = "\u56de\u5230\u5f53\u524d";
				this._returnBtn.addEventListener("click", () => {
					this.state.autoScroll = true;
					bus.emit("autoScrollChanged", true);
					const s = this.state.activeSentenceIdx;
					if (s >= 0 && s !== this.currentSentenceIdx) {
						this.setActiveSentenceFromUserNav(s);
					}
				});
				wrap.appendChild(this._returnBtn);
			}
			if (this._returnBtn) {
				this._returnBtn.classList.toggle("show", !enabled);
			}
		};
		bus.on("autoScrollChanged", this._onAutoScroll);
	}

	// ── Public entry points ────────────────────────────────────────

	/**
	 * Playback-driven: rebuild the transcript for the new sentence.
	 * Never scrolls the page.
	 */
	setActiveSentenceFromPlayback(idx) {
		this._renderSentence(idx, { animate: true });
	}

	/**
	 * User-nav: rebuild and scroll the wrap into view ({block: 'nearest'},
	 * so a fully-visible wrap stays put; only scrolls if scrolled off).
	 *
	 * Also emits activeSentenceChanged so HeatmapBand / TrendChart band /
	 * GenderLegend follow the user's choice — without this, the transcript
	 * row would advance but the rest of the timeline would stay on whatever
	 * sentence playback last entered.  TranscriptRow's own subscriber is
	 * guarded by `nextIdx !== currentSentenceIdx`, so the emit is a no-op
	 * for self.
	 */
	setActiveSentenceFromUserNav(idx) {
		this._renderSentence(idx, { animate: true });
		this._wrap?.scrollIntoView({ block: "nearest" });
		this.state.activeSentenceIdx = idx;
		this.bus.emit("activeSentenceChanged", {
			prevIdx: -1,
			nextIdx: idx,
			sentence: this.sentences[idx],
		});
	}

	// ── Sentence rendering ─────────────────────────────────────────

	_renderSentence(idx, { animate }) {
		if (!this.sentences.length) return;
		const clamped = Math.max(0, Math.min(this.sentences.length - 1, idx));
		this.currentSentenceIdx = clamped;
		const s = this.sentences[clamped];

		// Sentence's time window — used to compute each char's left/width as
		// percentages of the row, mirroring HeatmapBand's `viewBox="0 0 sDur 1"`
		// so column positions match exactly between the two rows.
		const sStart = s.start;
		const sDur = Math.max(0.001, s.end - s.start);

		const rebuild = () => {
			this._group.innerHTML = "";
			this._btnByCharIdx = new Map();
			this._activeBtn = null;

			// Container width × widthPct = the time-allocated pixel width of each
			// button.  We pick ONE uniform font size for every char in the
			// sentence — driven by the narrowest cell — so the row reads as a
			// proper line of text rather than a ransom-note mix of sizes.  The
			// narrowest cell still fits its glyph (Chinese width ≈ font-size, ~10 %
			// safety margin), and wider cells just show the same-size glyph
			// centred in extra whitespace.
			const groupWidth = this._group.clientWidth || this._wrap?.clientWidth || 360;
			const CHAR_FONT_MAX = 28;
			const CHAR_FONT_MIN = 14;
			let minWidthPx = Infinity;
			for (let i = 0; i < s.chars.length; i++) {
				const c = s.chars[i];
				const widthPct = ((c.end - c.start) / sDur) * 100;
				const expectedPx = (widthPct / 100) * groupWidth;
				if (expectedPx < minWidthPx) minWidthPx = expectedPx;
			}
			const charFont = Math.max(
				CHAR_FONT_MIN,
				Math.min(CHAR_FONT_MAX, Math.floor(minWidthPx * 0.9)),
			);

			for (let i = 0; i < s.chars.length; i++) {
				const c = s.chars[i];
				const leftPct = ((c.start - sStart) / sDur) * 100;
				const widthPct = ((c.end - c.start) / sDur) * 100;

				const btn = document.createElement("button");
				btn.type = "button";
				btn.className = "phone";
				btn.tabIndex = i === 0 ? 0 : -1;
				btn.setAttribute("aria-current", "false");
				btn.style.left = `${leftPct}%`;
				btn.style.width = `${widthPct}%`;
				btn.innerHTML = `<span class="phone__char" style="font-size:${charFont}px">${_esc(c.char)}</span>`;
				btn._charData = c;
				btn.addEventListener("click", () => {
					this.bus.emit("seek", c.start);
					this._updateReadout(c);
				});
				btn.addEventListener("keydown", (e) => this._onCharKey(e, i));
				this._group.appendChild(btn);
			}

			// Map original-chars index → button (step over ORIGINAL chars,
			// skip spacers, line up with rendered buttons in order).
			const btns = this._group.querySelectorAll("button.phone");
			let btnCursor = 0;
			for (let i = s.startIdx; i <= s.endIdx; i++) {
				if (!this.chars[i].char) continue;
				if (btnCursor < btns.length) {
					this._btnByCharIdx.set(i, btns[btnCursor]);
					btnCursor++;
				}
			}

			this._updateNav();
			this._setActiveChar(-1, this.state.activeCharIdx);
		};

		if (animate && !this.state.reducedMotion) {
			this._group.style.opacity = "0";
			setTimeout(() => {
				rebuild();
				this._group.style.transition = `opacity ${FADE_MS}ms linear`;
				this._group.style.opacity = "1";
			}, FADE_MS);
		} else {
			rebuild();
		}
	}

	// ── Nav bar ───────────────────────────────────────────────────
	_buildNav() {
		const root = document.createElement("div");
		root.className = "vga-sentence-nav";
		root.setAttribute("role", "navigation");
		root.setAttribute("aria-label", "\u53e5\u5b50\u5206\u9875");

		const prev = document.createElement("button");
		prev.type = "button";
		prev.className = "vga-sentence-nav__btn";
		prev.setAttribute("aria-label", "\u4e0a\u4e00\u53e5");
		prev.innerHTML = "&larr;";
		prev.addEventListener("click", () => this._navClick(-1));

		const counter = document.createElement("span");
		counter.className = "vga-sentence-nav__counter";
		counter.setAttribute("aria-live", "polite");

		const next = document.createElement("button");
		next.type = "button";
		next.className = "vga-sentence-nav__btn";
		next.setAttribute("aria-label", "\u4e0b\u4e00\u53e5");
		next.innerHTML = "&rarr;";
		next.addEventListener("click", () => this._navClick(1));

		root.append(prev, counter, next);

		root.addEventListener("keydown", (e) => {
			if (e.key === "ArrowLeft") {
				e.preventDefault();
				this._navClick(-1);
			} else if (e.key === "ArrowRight") {
				e.preventDefault();
				this._navClick(1);
			}
		});

		return { root, prev, next, counter };
	}

	_navClick(delta) {
		const target = this.currentSentenceIdx + delta;
		if (target < 0 || target >= this.sentences.length) return;
		this.setActiveSentenceFromUserNav(target);
	}

	_updateNav() {
		const total = this.sentences.length;
		const idx = this.currentSentenceIdx;
		this._nav.counter.textContent = `${idx + 1} / ${total}`;
		this._nav.prev.disabled = idx === 0;
		this._nav.next.disabled = idx === total - 1;
	}

	// ── Active char highlight within current sentence (visual only) ───
	_setActiveChar(_prev, next) {
		if (this._activeBtn) {
			this._activeBtn.setAttribute("aria-current", "false");
			this._activeBtn.tabIndex = -1;
			this._activeBtn = null;
		}
		if (next < 0) {
			this._updateReadout(null);
			return;
		}
		const btn = this._btnByCharIdx?.get(next);
		if (!btn) {
			this._updateReadout(null);
			return;
		}
		btn.setAttribute("aria-current", "true");
		btn.tabIndex = 0;
		this._activeBtn = btn;
		this._updateReadout(btn._charData);
	}

	_updateReadout(c) {
		if (!this._readoutChar) return;
		if (!c) {
			this._readoutChar.textContent = "\u2014";
			this._readoutPitch.textContent = "\u2014";
			this._readoutRes.textContent = "\u2014";
			return;
		}
		this._readoutChar.textContent = c.char || "\u2014";
		this._readoutPitch.textContent = c.pitch != null ? `${Math.round(c.pitch)} Hz` : "\u2014";
		this._readoutRes.textContent = c.resonance != null ? c.resonance.toFixed(2) : "\u2014";
	}

	_onCharKey(e, i) {
		const btns = Array.from(this._group.querySelectorAll("button.phone"));
		if (!btns.length) return;

		let nextPos = i;
		if (e.key === "ArrowRight") nextPos = Math.min(i + 1, btns.length - 1);
		else if (e.key === "ArrowLeft") nextPos = Math.max(i - 1, 0);
		else if (e.key === "Home") nextPos = 0;
		else if (e.key === "End") nextPos = btns.length - 1;
		else if (e.key === "Enter" || e.key === " ") {
			e.preventDefault();
			const c = this.sentences[this.currentSentenceIdx].chars[i];
			this.bus.emit("seek", c.start);
			return;
		} else return;

		e.preventDefault();
		btns[i].tabIndex = -1;
		btns[nextPos].tabIndex = 0;
		btns[nextPos].focus();
	}

	_installScrollWatcher(el) {
		let idleTimer;
		const onUserScroll = () => {
			if (!this.state.isPlaying) return;
			this.state.autoScroll = false;
			this.bus.emit("autoScrollChanged", false);
			clearTimeout(idleTimer);
			idleTimer = setTimeout(() => {
				this.state.autoScroll = true;
				this.bus.emit("autoScrollChanged", true);
			}, 5000);
		};
		el.addEventListener("wheel", onUserScroll, { passive: true });
		el.addEventListener("touchmove", onUserScroll, { passive: true });
	}

	destroy() {
		if (this.bus) {
			if (this._onActiveChar) this.bus.off("activeCharChanged", this._onActiveChar);
			if (this._onActiveSentence) this.bus.off("activeSentenceChanged", this._onActiveSentence);
			if (this._onAutoScroll) this.bus.off("autoScrollChanged", this._onAutoScroll);
		}
		if (this._group && this._onGroupClick) this._group.removeEventListener("click", this._onGroupClick);
		this._returnBtn?.remove();
		this._wrap?.remove();
		this._btnByCharIdx = null;
	}
}

function _esc(s) {
	const d = document.createElement("span");
	d.textContent = s;
	return d.innerHTML;
}
