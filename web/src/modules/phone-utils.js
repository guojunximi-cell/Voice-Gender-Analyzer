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
				// Visual slot weight: 1 for a single CJK ideograph (unchanged
				// layout vs. the pre-weight era), clamp(letter_count, 2, 10)
				// for an English word.  Consumed by groupCharsByWeight (for
				// pagination) and by HeatmapBand / TranscriptRow (for per-slot
				// x / width derivation).  See _cellWeight below.
				weight: _cellWeight(p.char || ""),
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

// CJK ideograph (BMP Unified + Extension A).  A "char" that is a single CJK
// codepoint is a hanzi → weight 1 (one visual square, same as pre-weight
// behaviour).  Anything else is treated as an English word → its letter count
// clamped to [2, 10]: floor of 2 so "a"/"I" don't collapse to invisible, ceiling
// of 10 so "antidisestablishmentarianism" can't consume half a page.
function _cellWeight(ch) {
	if (!ch) return 0;
	// Spread to iterate code points (handles surrogate pairs even though CJK
	// BMP doesn't need it — future-proof for extension ranges).
	const cps = [...ch];
	if (cps.length === 1) {
		const cp = cps[0].codePointAt(0);
		if ((cp >= 0x4e00 && cp <= 0x9fff) || (cp >= 0x3400 && cp <= 0x4dbf)) return 1;
	}
	const letters = ch.match(/[A-Za-z]/g);
	const n = letters ? letters.length : cps.length;
	return Math.max(2, Math.min(10, n));
}

/**
 * Slice chars into pages whose members' `weight` sum fits within `weightBudget`.
 *
 * Rationale: equal-width slots (old behaviour) made "by"/"sit" float in the
 * same slot size as "possibility", and clipped "morning" when squeezed.
 * Weight-based packing gives each slot a width proportional to its visual
 * size so short + long words coexist honestly on one page.
 *
 * For CJK each cell has weight 1, so `weightBudget = N` reproduces the old
 * "N hanzi per page" behaviour exactly — this is not a separate code path,
 * it's the same algorithm with a language-specific weight function.
 *
 * Spacer cells (empty `char`) don't count toward the budget and aren't kept
 * in the page's `chars` array — they live only in the original `chars[]`
 * for time-continuity.
 *
 * Page shape (HeatmapBand / TranscriptRow consumers):
 *   { start, end, startIdx, endIdx, chars: [realCharRefs], totalWeight }
 * `startIdx` / `endIdx` point into the ORIGINAL chars[] (inclusive, real
 * chars) — PlaybackSync uses them to map activeCharIdx → pageIdx.
 * `totalWeight` is Σ(chars[i].weight), used by renderers to derive each
 * cell's [cumWeight, cumWeight+weight] sub-range within the page.
 */
export function groupCharsByWeight(chars, { weightBudget } = {}) {
	if (!chars?.length) return [];
	const budget = Math.max(1, weightBudget || 1);

	const pages = [];
	let cur = { chars: [], startIdx: -1, endIdx: -1, totalWeight: 0 };

	const closePage = () => {
		if (!cur.chars.length) return;
		cur.start = cur.chars[0].start;
		cur.end = cur.chars[cur.chars.length - 1].end;
		pages.push(cur);
		cur = { chars: [], startIdx: -1, endIdx: -1, totalWeight: 0 };
	};

	for (let i = 0; i < chars.length; i++) {
		const c = chars[i];
		if (!c.char) continue; // spacer cells don't count toward page capacity
		// Close the current page *before* adding this word if doing so would
		// overflow the budget — unless the page is empty (always fit ≥1 word
		// per page, even if a single clamp-max word technically exceeds the
		// narrow-container budget; pagination alone can't split a word).
		if (cur.chars.length && cur.totalWeight + c.weight > budget) closePage();
		if (cur.startIdx === -1) cur.startIdx = i;
		cur.endIdx = i;
		cur.chars.push(c);
		cur.totalWeight += c.weight;
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
