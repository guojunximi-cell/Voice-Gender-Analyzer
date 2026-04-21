/**
 * classify.js — Turn Engine C phones into Engine-A-shaped segments using
 * pitch or resonance thresholds, so 声音占比 / waveform overlay / history
 * scatter can switch their classification source without touching their
 * render code.
 *
 * Thresholds come from diverging.js (single source of truth):
 *   pitch:     neutral = 165 Hz, confidence saturates at ±65 Hz
 *   resonance: neutral = 0.5,    confidence saturates at ±0.3
 *
 * Output segment shape mirrors Engine A's analysis[] entries:
 *   { label: "male"|"female"|"other", start_time, end_time, confidence }
 * Consecutive phones of the same label merge; confidence is the
 * duration-weighted mean within the merged run.
 */

import { THRESHOLDS } from "./diverging.js";

const PITCH_NEUTRAL = THRESHOLDS.pitchNeutralHz; // 165 Hz
const PITCH_SAT = 65; // Hz — distance that saturates confidence to 1
const RES_NEUTRAL = 0.5;
const RES_SAT = 0.3;

function _classifyPhone(phone, mode) {
	if (mode === "pitch") {
		const hz = phone.pitch;
		if (hz == null || !Number.isFinite(hz) || hz <= 0) {
			return { label: "other", confidence: 0 };
		}
		const diff = hz - PITCH_NEUTRAL;
		const label = diff >= 0 ? "female" : "male";
		const conf = Math.min(1, Math.abs(diff) / PITCH_SAT);
		return { label, confidence: conf };
	}
	if (mode === "resonance") {
		const r = phone.resonance;
		if (r == null || !Number.isFinite(r)) {
			return { label: "other", confidence: 0 };
		}
		const diff = r - RES_NEUTRAL;
		const label = diff >= 0 ? "female" : "male";
		const conf = Math.min(1, Math.abs(diff) / RES_SAT);
		return { label, confidence: conf };
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
	const segs = [];
	let cur = null;
	for (const p of phones) {
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
	let mDur = 0,
		mConf = 0,
		fDur = 0,
		fConf = 0;
	for (const s of segs) {
		const d = (s.end_time ?? 0) - (s.start_time ?? 0);
		if (d <= 0) continue;
		if (s.label === "male") {
			mDur += d;
			mConf += (s.confidence ?? 0) * d;
		} else if (s.label === "female") {
			fDur += d;
			fConf += (s.confidence ?? 0) * d;
		}
	}
	if (mDur === 0 && fDur === 0) {
		return {
			label: session.label ?? null,
			confidence: session.confidence ?? null,
		};
	}
	const label = fDur >= mDur ? "female" : "male";
	const confidence = label === "female" ? fConf / fDur : mConf / mDur;
	return { label, confidence: Math.min(1, Math.max(0, confidence)) };
}
