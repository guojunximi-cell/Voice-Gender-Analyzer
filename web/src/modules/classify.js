/**
 * classify.js — Turn Engine C phones into Engine-A-shaped segments using
 * pitch or resonance thresholds, so 声音占比 / waveform overlay / history
 * scatter can switch their classification source without touching their
 * render code.
 *
 * Thresholds come from zones.js (single source of truth, also feeds the
 * Pitch Range bar widths and Resonance scale zones below):
 *   pitch:     male < 145 Hz   ≤  neutral  ≤ 185 Hz < female
 *   resonance: male < p25      ≤  neutral  ≤ p75    < female  (per language)
 *
 * In resonance mode, the global "include consonants" toggle (consonants-
 * toggle.js) decides whether non-vowel phones contribute to the segment
 * count.  Default ON so the top tab and the 共鸣表现 panel stay aligned;
 * flipping to OFF gives a vowel-only view in both places at once.
 *
 * Output segment shape mirrors Engine A's analysis[] entries:
 *   { label: "male"|"neutral"|"female"|"other", start_time, end_time, confidence }
 * Consecutive phones of the same label merge; confidence is the
 * duration-weighted mean within the merged run.
 */

import { getIncludeConsonants } from "./consonants-toggle.js";
import { getLang } from "./i18n.js";
import { pitchConfidence, pitchZone, resonanceConfidence, resonanceZone } from "./zones.js";

function _classifyPhone(phone, mode) {
	if (mode === "pitch") {
		const hz = phone.pitch;
		const label = pitchZone(hz);
		if (!label) return { label: "other", confidence: 0 };
		return { label, confidence: pitchConfidence(hz, label) };
	}
	if (mode === "resonance") {
		const r = phone.resonance;
		const lang = getLang();
		const label = resonanceZone(r, lang);
		if (!label) return { label: "other", confidence: 0 };
		return { label, confidence: resonanceConfidence(r, label, lang) };
	}
	return null;
}

function _finalize(run) {
	const confidence = run._durSum > 0 ? run._confSum / run._durSum : 0;
	return {
		label: run.label,
		start_time: run.start_time,
		end_time: run.end_time,
		confidence: Math.min(1, Math.max(0, confidence)),
	};
}

export function classifyPhones(phones, mode) {
	if (!phones?.length || (mode !== "pitch" && mode !== "resonance")) return [];
	// Resonance mode honours the consonants toggle; pitch mode is unaffected
	// (F0 is meaningful for sonorants but not a UX concern here — pitch
	// has no "include consonants" toggle exposed).  Phones missing the
	// `is_vowel` field default to true to preserve old session behaviour.
	const dropConsonants = mode === "resonance" && !getIncludeConsonants();
	const segs = [];
	let cur = null;
	for (const p of phones) {
		if (dropConsonants && p.is_vowel === false) continue;
		const c = _classifyPhone(p, mode);
		if (!c) continue;
		const dur = Math.max(0, (p.end ?? 0) - (p.start ?? 0));
		if (dur <= 0) continue;
		if (cur && cur.label === c.label) {
			cur.end_time = p.end;
			cur._confSum += c.confidence * dur;
			cur._durSum += dur;
		} else {
			if (cur) segs.push(_finalize(cur));
			cur = {
				label: c.label,
				start_time: p.start,
				end_time: p.end,
				_confSum: c.confidence * dur,
				_durSum: dur,
			};
		}
	}
	if (cur) segs.push(_finalize(cur));
	return segs;
}

export function hasEngineC(summary) {
	return !!summary?.engine_c?.phones?.length;
}

/** Resolve segments for a session given the current mode.  Falls back to
 *  Engine A analysis if the requested mode has no data available. */
export function classifyForMode({ analysis, summary }, mode) {
	if (mode === "pitch" || mode === "resonance") {
		if (hasEngineC(summary)) {
			return classifyPhones(summary.engine_c.phones, mode);
		}
	}
	return analysis || [];
}

/** Duration-weighted dominant label + confidence for the scatter chart. */
export function dominantForMode(session, mode) {
	const segs = classifyForMode(session, mode);
	const acc = { male: { dur: 0, conf: 0 }, neutral: { dur: 0, conf: 0 }, female: { dur: 0, conf: 0 } };
	for (const s of segs) {
		const d = (s.end_time ?? 0) - (s.start_time ?? 0);
		if (d <= 0) continue;
		const slot = acc[s.label];
		if (!slot) continue;
		slot.dur += d;
		slot.conf += (s.confidence ?? 0) * d;
	}
	const total = acc.male.dur + acc.neutral.dur + acc.female.dur;
	if (total === 0) {
		return {
			label: session.label ?? null,
			confidence: session.confidence ?? null,
		};
	}
	const winner = ["male", "neutral", "female"].reduce((best, k) => (acc[k].dur > acc[best].dur ? k : best), "male");
	const confidence = acc[winner].dur > 0 ? acc[winner].conf / acc[winner].dur : 0;
	return { label: winner, confidence: Math.min(1, Math.max(0, confidence)) };
}
