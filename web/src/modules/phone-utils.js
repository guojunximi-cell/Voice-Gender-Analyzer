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
	return chars;
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
 * Group consecutive characters into sentences by time-gap heuristic.
 *
 * Rules (matches user spec):
 *   (a) gap > 0.5 s between adjacent real chars → split
 *   (b) sentence length ≥ 15 real chars → forced split (fallback cap)
 *   (c) empty/spacer chars are skipped (they are silence gaps, not content)
 *
 * Each sentence: { start, end, startIdx, endIdx, chars: [...] }
 * where startIdx / endIdx point into the ORIGINAL chars array (inclusive,
 * both pointing at real chars), so PlaybackSync can map activeCharIdx →
 * sentenceIdx without a second filter.
 */
export function groupCharsIntoSentences(chars) {
	if (!chars?.length) return [];

	const sentences = [];
	let cur = { chars: [], startIdx: -1, endIdx: -1 };
	let lastRealEnd = -Infinity;
	const MAX_CHARS = 15;
	const GAP_SEC = 0.5;

	const closeSentence = () => {
		if (!cur.chars.length) return;
		cur.start = cur.chars[0].start;
		cur.end = cur.chars[cur.chars.length - 1].end;
		sentences.push(cur);
		cur = { chars: [], startIdx: -1, endIdx: -1 };
	};

	for (let i = 0; i < chars.length; i++) {
		const c = chars[i];
		if (!c.char) continue; // skip spacer cells

		if (cur.chars.length > 0) {
			const gap = c.start - lastRealEnd;
			if (gap > GAP_SEC || cur.chars.length >= MAX_CHARS) {
				closeSentence();
			}
		}

		if (cur.startIdx === -1) cur.startIdx = i;
		cur.endIdx = i;
		cur.chars.push(c);
		lastRealEnd = c.end;
	}
	closeSentence();

	return sentences;
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
