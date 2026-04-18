/**
 * transcript-row.js — Clickable character buttons with sub-labels.
 *
 * Each character cell is a <button> with:
 *   - 20 px hanzi label
 *   - 11 px monospace pitch (Hz) sub-label
 *   - 11 px monospace resonance (0–1) sub-label
 *
 * Roving tabindex keyboard navigation (not role="listbox").
 * Click/Enter → bus.emit('seek', charStart) → PlaybackSync → WaveSurfer.
 * Auto-scroll during playback with user-scroll suspension (5 s idle timeout).
 */

export class TranscriptRow {
	/**
	 * @param {{ container: HTMLElement, chars: Array, bus: object, state: object }} opts
	 */
	mount({ container, chars, bus, state }) {
		this.bus = bus;
		this.state = state;
		this.chars = chars;

		const group = document.createElement("div");
		group.setAttribute("role", "group");
		group.setAttribute("aria-label", "逐字转录。按左右方向键选字，回车播放到该位置。");
		group.className = "vga-transcript";

		this.els = chars.map((c, i) => {
			// Skip empty/null chars (silent gaps) — render as invisible spacer
			if (!c.char) {
				const spacer = document.createElement("span");
				spacer.style.width = "1px";
				spacer.setAttribute("aria-hidden", "true");
				group.appendChild(spacer);
				return null;
			}

			const btn = document.createElement("button");
			btn.type = "button";
			btn.className = "phone";
			btn.tabIndex = i === 0 ? 0 : -1;
			btn.setAttribute("aria-current", "false");
			btn.innerHTML = `
				<span class="phone__char">${_esc(c.char)}</span>
				<span class="phone__pitch" aria-label="音高">${_fmtHz(c.pitch)}</span>
				<span class="phone__res" aria-label="共鸣">${_fmtRes(c.resonance)}</span>`;
			btn.addEventListener("click", () => bus.emit("seek", c.start));
			btn.addEventListener("keydown", (e) => this._onKey(e, i));
			group.appendChild(btn);
			return btn;
		});

		container.appendChild(group);
		this._group = group;
		this._installScrollWatcher(group);

		// Listen for active changes
		this._onActive = ({ prevIdx, nextIdx }) => this._setActive(prevIdx, nextIdx);
		bus.on("activeCharChanged", this._onActive);

		// Show/hide return-to-current button
		this._returnBtn = null;
		this._onAutoScroll = (enabled) => {
			if (!this._returnBtn && !enabled) {
				this._returnBtn = document.createElement("button");
				this._returnBtn.type = "button";
				this._returnBtn.className = "vga-return-btn show";
				this._returnBtn.textContent = "回到当前";
				this._returnBtn.addEventListener("click", () => {
					this.state.autoScroll = true;
					bus.emit("autoScrollChanged", true);
					const idx = this.state.activeCharIdx;
					if (idx >= 0 && this.els[idx]) {
						this.els[idx].scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
					}
				});
				group.parentElement?.appendChild(this._returnBtn);
			}
			if (this._returnBtn) {
				this._returnBtn.classList.toggle("show", !enabled);
			}
		};
		bus.on("autoScrollChanged", this._onAutoScroll);
	}

	_setActive(prev, next) {
		if (prev >= 0 && this.els[prev]) {
			this.els[prev].setAttribute("aria-current", "false");
			this.els[prev].tabIndex = -1;
		}
		if (next >= 0 && this.els[next]) {
			const el = this.els[next];
			el.setAttribute("aria-current", "true");
			el.tabIndex = 0;
			if (this.state.autoScroll && this.state.isPlaying) {
				el.scrollIntoView({
					block: "nearest",
					inline: "center",
					behavior: this.state.reducedMotion ? "auto" : "smooth",
				});
			}
		}
	}

	_onKey(e, i) {
		const validEls = this.els.filter((el) => el != null);
		const validIndices = this.els.reduce((acc, el, idx) => {
			if (el) acc.push(idx);
			return acc;
		}, []);
		const posInValid = validIndices.indexOf(i);
		if (posInValid < 0) return;

		let nextPos = posInValid;
		if (e.key === "ArrowRight") nextPos = Math.min(posInValid + 1, validEls.length - 1);
		else if (e.key === "ArrowLeft") nextPos = Math.max(posInValid - 1, 0);
		else if (e.key === "Home") nextPos = 0;
		else if (e.key === "End") nextPos = validEls.length - 1;
		else if (e.key === "Enter" || e.key === " ") {
			e.preventDefault();
			this.bus.emit("seek", this.chars[i].start);
			return;
		} else return;

		e.preventDefault();
		const nextIdx = validIndices[nextPos];
		if (this.els[i]) this.els[i].tabIndex = -1;
		if (this.els[nextIdx]) {
			this.els[nextIdx].tabIndex = 0;
			this.els[nextIdx].focus();
		}
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
			if (this._onActive) this.bus.off("activeCharChanged", this._onActive);
			if (this._onAutoScroll) this.bus.off("autoScrollChanged", this._onAutoScroll);
		}
		this._returnBtn?.remove();
		this._group?.remove();
		this.els = [];
	}
}

function _fmtHz(v) {
	return v != null ? `${Math.round(v)}` : "\u2014";
}

function _fmtRes(v) {
	return v != null ? v.toFixed(2) : "\u2014";
}

function _esc(s) {
	const d = document.createElement("span");
	d.textContent = s;
	return d.innerHTML;
}
