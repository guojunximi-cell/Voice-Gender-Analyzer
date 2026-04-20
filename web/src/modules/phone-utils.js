/**
 * phone-utils.js — Data transforms for phone-level timeline.
 *
 * groupPhonesByChar:  Collapse consecutive phones sharing the same char
 *                     into single character cells with aggregated metrics.
 *
 * findActiveIdx:      Cached-index + forward-check + binary-search fallback
 *                     to map currentTime → active character index at ~rAF rate.
 */

/**
 * Group consecutive phones that share the same `char` value into character
 * cells.  Phones with empty/null char are kept as invisible spacers.
 *
 * Each returned cell: { start, end, char, pitch, resonance, phones: [...] }
 */
export function groupPhonesByChar(phones) {
	if (!phones?.length) return [];
	const chars = [];
	for (const p of phones) {
		const last = chars[chars.length - 1];
		// Merge into previous cell if same char and adjacent in time (<20 ms gap)
		if (last && p.char && last.char === p.char && Math.abs(last.end - p.start) < 0.02) {
			last.end = p.end;
			last.phones.push(p);
		} else {
			chars.push({
				start: p.start,
				end: p.end,
				char: p.char || "",
				phones: [p],
				// Aggregates computed below
				pitch: null,
				resonance: null,
				F1: null,
				F2: null,
				F3: null,
			});
		}
	}
	// Compute aggregates per character cell
	for (const c of chars) {
		const voiced = c.phones.filter((p) => p.pitch > 0);
		c.pitch = voiced.length ? _mean(voiced.map((p) => p.pitch)) : null;
		const resVals = c.phones.map((p) => p.resonance).filter((r) => r != null);
		c.resonance = resVals.length ? _mean(resVals) : null;
		const f1Vals = c.phones.map((p) => p.F1).filter((v) => v != null);
		c.F1 = f1Vals.length ? _mean(f1Vals) : null;
		const f2Vals = c.phones.map((p) => p.F2).filter((v) => v != null);
		c.F2 = f2Vals.length ? _mean(f2Vals) : null;
		const f3Vals = c.phones.map((p) => p.F3).filter((v) => v != null);
		c.F3 = f3Vals.length ? _mean(f3Vals) : null;
	}

	// Pitch is fundamentally sparse at the phone level: Praat can't extract F0
	// from unvoiced consonants (/t/, /k/, /p/…) and outlier rejection at the
	// sidecar drops more.  For the heatmap we want every voiced hanzi to show
	// a color — so we (1) lift pitch to char level (all phones of a char share
	// one color), and (2) fill char-level gaps by linear interpolation in time
	// between the nearest voiced neighbours.  Resonance is left alone: LPC
	// produces formants even for unvoiced phones, so per-phone resolution is
	// honest and useful.
	_fillCharPitch(chars);
	for (const c of chars) {
		const v = c.pitchInterp;
		for (const p of c.phones) p.charPitch = v;
	}

	return chars;
}

/**
 * Write `c.pitchInterp` on every char cell.  Voiced chars copy their measured
 * `c.pitch`; null chars that sit between two voiced neighbours get a linear
 * interpolation by time; null chars at the edges hold the nearest value
 * constant.  Chars with no voiced neighbour at all stay null (e.g. a whole
 * phrase of only unvoiced phones — rare in Mandarin).  Spacer cells (empty
 * char) are skipped so silence doesn't anchor interpolation paths.
 */
function _fillCharPitch(chars) {
	const real = chars.filter((c) => c.char);
	if (!real.length) return;

	for (let i = 0; i < real.length; i++) {
		const c = real[i];
		if (c.pitch != null) {
			c.pitchInterp = c.pitch;
			continue;
		}
		let lo = i - 1;
		while (lo >= 0 && real[lo].pitch == null) lo--;
		let hi = i + 1;
		while (hi < real.length && real[hi].pitch == null) hi++;
		const prev = lo >= 0 ? real[lo] : null;
		const next = hi < real.length ? real[hi] : null;
		if (prev && next) {
			const span = next.start - prev.end;
			const t = span > 0 ? (c.start - prev.end) / span : 0.5;
			c.pitchInterp = prev.pitch + (next.pitch - prev.pitch) * Math.max(0, Math.min(1, t));
		} else if (prev) {
			c.pitchInterp = prev.pitch;
		} else if (next) {
			c.pitchInterp = next.pitch;
		} else {
			c.pitchInterp = null;
		}
	}
}

/**
 * Find the active character index for a given time.
 * Uses cached last index + one-forward check for O(1) during sequential
 * playback; falls back to binary search on seek.
 *
 * @param {number} t - Current time in seconds
 * @param {Array} chars - Sorted character cells from groupPhonesByChar
 * @param {number} lastIdx - Previous active index (cache)
 * @returns {number} Active index, or -1 if no character is active
 */
export function findActiveIdx(t, chars, lastIdx) {
	if (!chars.length) return -1;

	// Fast path: still in the same cell
	if (lastIdx >= 0 && lastIdx < chars.length) {
		const c = chars[lastIdx];
		if (t >= c.start && t < c.end) return lastIdx;
		// Next cell (sequential playback)
		const n = chars[lastIdx + 1];
		if (n && t >= n.start && t < n.end) return lastIdx + 1;
	}

	// Binary search fallback (seek)
	let lo = 0,
		hi = chars.length - 1;
	while (lo <= hi) {
		const m = (lo + hi) >> 1;
		if (t < chars[m].start) hi = m - 1;
		else if (t >= chars[m].end) lo = m + 1;
		else return m;
	}
	return -1;
}

function _mean(arr) {
	return arr.reduce((a, b) => a + b, 0) / arr.length;
}

/**
 * Slice chars into fixed-size pages of `charCount` real hanzi each.
 *
 * Pure width-driven: ignores acoustic signals (silence, phone gaps) entirely.
 * Caller picks `charCount` from `⌊containerPx / readablePxPerChar⌋`, so the
 * resulting pagination tracks the viewport.  Spacer cells (empty `char`) are
 * never counted toward the page size and never kept in the page's `chars`
 * array — they live only in the original `chars[]` for time-continuity.
 *
 * Each page has the same shape as the previous acoustic-sentence output, so
 * HeatmapBand and TranscriptRow consume it unchanged:
 *   { start, end, startIdx, endIdx, chars: [realCharRefs] }
 * `startIdx` / `endIdx` point into the ORIGINAL chars[] (inclusive, both
 * pointing at real chars) — PlaybackSync uses these to map activeCharIdx → pageIdx.
 */
export function groupCharsByWidth(chars, { charCount } = {}) {
	if (!chars?.length) return [];
	const N = Math.max(1, Math.floor(charCount || 1));

	const pages = [];
	let cur = { chars: [], startIdx: -1, endIdx: -1 };

	const closePage = () => {
		if (!cur.chars.length) return;
		cur.start = cur.chars[0].start;
		cur.end = cur.chars[cur.chars.length - 1].end;
		pages.push(cur);
		cur = { chars: [], startIdx: -1, endIdx: -1 };
	};

	for (let i = 0; i < chars.length; i++) {
		const c = chars[i];
		if (!c.char) continue; // spacer cells don't count toward page capacity
		if (cur.startIdx === -1) cur.startIdx = i;
		cur.endIdx = i;
		cur.chars.push(c);
		if (cur.chars.length >= N) closePage();
	}
	closePage();
	return pages;
}

/**
 * Find the sentence containing a given char index.
 * Returns -1 if charIdx is -1 (no active char) or points at a spacer
 * between sentences.  Linear scan — sentences are typically < 50.
 */
export function findSentenceIdx(charIdx, sentences) {
	if (charIdx < 0 || !sentences?.length) return -1;
	for (let i = 0; i < sentences.length; i++) {
		if (charIdx >= sentences[i].startIdx && charIdx <= sentences[i].endIdx) {
			return i;
		}
	}
	return -1;
}
