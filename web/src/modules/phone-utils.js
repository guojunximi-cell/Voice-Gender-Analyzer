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
 * Group consecutive characters into sentences.
 *
 * Primary signal (when `silenceRanges` is non-empty): any silence interval
 * falling between two adjacent real chars triggers a sentence break.  These
 * ranges come from ffmpeg `silencedetect -30dB:d=0.5` in the sidecar — an
 * authoritative acoustic measurement, immune to MFA's habit of gluing
 * mid-sentence silence onto the preceding hanzi's phone cell.
 *
 * Fallback (when `silenceRanges` is empty): phone-to-phone gap > 0.5 s.
 * Unreliable when MFA attributes silence phones to the preceding word
 * (gap is then ~0), which is why Level 2 was added.
 *
 * Cap (always on): sentence length ≥ 15 real chars → forced split, so the
 * UI never has to fit an unreadable 30-char line in one row.
 *
 * Spacer cells (empty `char`) are skipped in both signal paths.
 *
 * Each sentence: { start, end, startIdx, endIdx, chars: [...] }
 * where startIdx / endIdx point into the ORIGINAL chars array (inclusive,
 * both pointing at real chars), so PlaybackSync can map activeCharIdx →
 * sentenceIdx without a second filter.
 */
export function groupCharsIntoSentences(chars, silenceRanges = []) {
	if (!chars?.length) return [];

	const sentences = [];
	let cur = { chars: [], startIdx: -1, endIdx: -1 };
	let lastRealEnd = -Infinity;
	const MAX_CHARS = 15;
	const GAP_SEC = 0.5;

	// 10 ms slop for silence-range containment: phone timings and silence
	// timings both round to 3 decimals but come from different subprocess
	// runs, so allow tiny misalignment at the edges.
	const SLOP = 0.01;
	const hasSilenceInfo = silenceRanges && silenceRanges.length > 0;
	// Sorted copy + advancing pointer — avoids an O(N*M) scan when both are
	// large.  Silences are monotone in time; so is the char loop.
	const silences = hasSilenceInfo ? [...silenceRanges].sort((a, b) => a.start - b.start) : [];
	let silenceCursor = 0;

	const hasSilenceBetween = (prevEnd, curStart) => {
		// Advance past silences that ended before prevEnd — they belong to an
		// earlier gap and can't split this pair.
		while (silenceCursor < silences.length && silences[silenceCursor].end < prevEnd - SLOP) {
			silenceCursor++;
		}
		for (let k = silenceCursor; k < silences.length; k++) {
			const s = silences[k];
			if (s.start > curStart + SLOP) break; // past the gap — none remaining can match
			if (s.start >= prevEnd - SLOP && s.end <= curStart + SLOP) return true;
		}
		return false;
	};

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
			const shouldSplit = hasSilenceInfo ? hasSilenceBetween(lastRealEnd, c.start) : c.start - lastRealEnd > GAP_SEC;
			if (shouldSplit || cur.chars.length >= MAX_CHARS) {
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
