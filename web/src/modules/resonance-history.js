/**
 * resonance-history.js — Pure utilities for "same-script" history compare.
 *
 * No DOM, no IndexedDB, no network — just transforms over plain objects so
 * we can unit-test (and the renderer in resonance-panel.js can stay focused).
 *
 * Identity is text-similarity based, not mode-based: a session's "spoken
 * content" is whichever of `engine_c.script` (script-mode ground truth) or
 * `engine_c.transcript` (free-mode ASR output) is present, normalized into a
 * token bag. Two sessions are "the same recording" if their token bags have
 * Jaccard similarity ≥ MATCH_FUZZY_THRESHOLD, OR they resolved to the same
 * preset id. This unifies script ↔ free comparisons and survives ASR drift
 * after re-import.
 *
 * The level-delta threshold +/- 0.3 σ is a rough JND; adjust here if it gets
 * too noisy.
 */

import { CUSTOM_SCRIPT_ID, scriptsForLang } from "./scripts.js";

const DELTA_THRESHOLD = 0.3;

// Preset detection is stricter than pairwise match: we only auto-tag a
// recording with a preset id when we're very sure (Whisper on clean audio
// hits 0.90+ on the Rainbow Passage etc.). Pairwise match is more lenient
// because two transcripts of the same custom text both have ASR drift.
const PRESET_FUZZY_THRESHOLD = 0.85;
const MATCH_FUZZY_THRESHOLD = 0.7;

// Pitch-compensation advisory: triggered when the user's NN gender_score went
// up notably between attempts but the per-vowel resonance details regressed
// for the majority. This is the signature of "raising pitch by tightening the
// jaw / larynx" — the NN (which only sees F0 + voicing) buys it, but formant
// medians collapse (typically F1) so the per-vowel z-scores drop. Thresholds
// are conservative to avoid false alarms; tune here if real-world samples
// suggest otherwise.
const NN_DIVERGENCE_DELTA = 5;
const REGRESSED_RATIO_MIN = 0.5;
const MIN_DECORATED_FOR_DIAGNOSIS = 4;

// CJK Unified Ideographs (Basic) — covers all preset zh content.
const _CJK_RE = /[一-鿿]/;
// Hangul precomposed syllables — covers all preset ko content.
const _HANGUL_RE = /[가-힣]/;

export function tokenizeForMatch(text, language) {
	if (!text) return [];
	const norm = String(text).normalize("NFKC").toLowerCase();
	if (language === "zh-CN") {
		const out = [];
		for (const ch of norm) if (_CJK_RE.test(ch)) out.push(ch);
		return out;
	}
	if (language === "ko-KR") {
		// Korean uses per-syllable tokenization (1 Hangul block = 1 token) —
		// matches how zh-CN tokenizes per-hanzi.  Word-level Jaccard over
		// eojeol would over-penalise small particle variations (을/를/이/가),
		// so syllable-level is more forgiving for fuzzy preset matching.
		const out = [];
		for (const ch of norm) if (_HANGUL_RE.test(ch)) out.push(ch);
		return out;
	}
	// Letters + digits + apostrophe (don't, l'air); everything else → space.
	return norm
		.replace(/[^\p{L}\p{N}\s']/gu, " ")
		.split(/\s+/)
		.filter(Boolean);
}

/**
 * Unordered Jaccard over token bags. Uses set semantics (not multiset) so a
 * dropped/repeated stop-word doesn't tank the score on long passages.
 */
export function jaccardSimilarity(a, b) {
	if (!a?.length || !b?.length) return 0;
	const A = new Set(a);
	const B = new Set(b);
	let inter = 0;
	for (const t of A) if (B.has(t)) inter++;
	const union = A.size + B.size - inter;
	return union === 0 ? 0 : inter / union;
}

/**
 * Pull the spoken text from an engine_c block, regardless of mode:
 *   - script mode → engine_c.script (ground truth, exact)
 *   - free mode   → engine_c.transcript (ASR output, may have small errors)
 * Returns null if neither field is present (no engine_c → no comparison).
 */
export function extractSpokenText(summary) {
	const ec = summary?.engine_c;
	if (!ec) return null;
	const text = ec.script || ec.transcript;
	return text ? String(text) : null;
}

function _findBestPreset(tokens, language) {
	if (!tokens.length) return null;
	let best = null;
	let bestScore = 0;
	for (const preset of scriptsForLang(language)) {
		const score = jaccardSimilarity(tokens, tokenizeForMatch(preset.text, language));
		if (score >= PRESET_FUZZY_THRESHOLD && score > bestScore) {
			best = preset;
			bestScore = score;
		}
	}
	return best;
}

/**
 * Derive the identity fields persisted alongside each saved session. Unlike
 * the old strict version, this works for both script and free modes — as
 * long as engine_c has *some* text we can match on.
 *
 *   summary    — analyzer response's `summary` field (carries engine_c)
 *   fallbackLanguage — used only when summary lacks engine_c.language
 *
 * Returns:
 *   {
 *     language: "zh-CN" | "en-US" | "fr-FR" | "ko-KR" | null,
 *     script_id: preset id | "custom" | null,
 *     spoken_text_norm: trimmed lowercase text (debug / future regex),
 *     spoken_text_tokens: pre-tokenized array for fast Jaccard at match time,
 *   }
 *
 * spoken_text_tokens is empty (and script_id null) when no engine_c text
 * exists — findPriorAttempt treats that as not eligible.
 */
export async function buildScriptIdentity(summary, fallbackLanguage) {
	const ec = summary?.engine_c;
	const language = ec?.language ?? fallbackLanguage ?? null;
	const text = extractSpokenText(summary);
	if (!text) {
		return { language, script_id: null, spoken_text_norm: "", spoken_text_tokens: [] };
	}
	const tokens = tokenizeForMatch(text, language);
	const norm = String(text).trim().replace(/\s+/g, " ").toLowerCase();
	const preset = _findBestPreset(tokens, language);
	const script_id = preset ? preset.id : CUSTOM_SCRIPT_ID;
	return { language, script_id, spoken_text_norm: norm, spoken_text_tokens: tokens };
}

/**
 * Find the most recent session that's the "same recording" as the current
 * attempt and strictly older than `before_created_at`. Match logic:
 *
 *   1. Same preset id (both non-null, both non-"custom") → score 1.0 shortcut.
 *   2. Otherwise, Jaccard over the two sessions' spoken_text_tokens; require
 *      score ≥ MATCH_FUZZY_THRESHOLD.
 *
 * Old sessions saved before this code shipped don't have spoken_text_tokens
 * — we tokenize their summary on demand. cap=50 in IDB so the cost is small.
 */
export function findPriorAttempt({ sessions, language, currentTokens, currentScriptId, before_created_at }) {
	if (!Array.isArray(sessions)) return null;
	if (!currentTokens?.length && !currentScriptId) return null;
	const cutoff = before_created_at ?? Number.POSITIVE_INFINITY;

	let best = null;
	let bestCreatedAt = -Infinity;

	for (const s of sessions) {
		if (!s) continue;
		// Old sessions saved before session-level `language` was tracked still
		// carry it inside summary.engine_c.language — fall back so they're
		// not silently excluded from the candidate pool.
		const sLang = s.language ?? s.summary?.engine_c?.language ?? null;
		if (sLang !== language) continue;
		if ((s.createdAt ?? 0) >= cutoff) continue;

		// Preset id shortcut: deterministic and free.
		const presetMatch = currentScriptId && currentScriptId !== CUSTOM_SCRIPT_ID && s.script_id === currentScriptId;

		let score = 0;
		if (presetMatch) {
			score = 1;
		} else if (currentTokens?.length) {
			const candidateTokens =
				Array.isArray(s.spoken_text_tokens) && s.spoken_text_tokens.length
					? s.spoken_text_tokens
					: tokenizeForMatch(extractSpokenText(s.summary), s.language);
			score = jaccardSimilarity(currentTokens, candidateTokens);
		}

		if (score >= MATCH_FUZZY_THRESHOLD && (s.createdAt ?? 0) > bestCreatedAt) {
			best = s;
			bestCreatedAt = s.createdAt ?? 0;
		}
	}
	return best;
}

/**
 * Pull the per_vowel level rows from a session's saved summary. Returns []
 * when the session predates advice_v2 per_vowel (graceful no-op).
 */
export function extractPerVowel(session) {
	const rows = session?.summary?.advice?.resonance_panel?.per_vowel;
	return Array.isArray(rows) ? rows : [];
}

function _classifyDelta(delta) {
	if (delta >= DELTA_THRESHOLD) return "improved";
	if (delta <= -DELTA_THRESHOLD) return "regressed";
	return "stable";
}

/**
 * Align current per_vowel rows against prior ones by vowel label.
 *
 * Returns an array preserving the current rows' order, each augmented with:
 *   - prior_z:   the prior worst-formant z, or null if no match
 *   - delta:     current.z - prior_z, or null
 *   - change_key: "improved" | "regressed" | "stable" | "no_prior"
 *
 * Note: we compare worst-formant z values, not per-formant. The worst formant
 * can shift between recordings (F1→F2) but the user-facing meaning stays
 * "how far is the worst formant from the female reference?" — still a useful
 * progress signal even when the limiting formant moves.
 */
export function computePerVowelDeltas(currentPerVowel, priorPerVowel) {
	const current = Array.isArray(currentPerVowel) ? currentPerVowel : [];
	const priorByVowel = new Map();
	if (Array.isArray(priorPerVowel)) {
		for (const r of priorPerVowel) {
			if (r && typeof r.vowel === "string" && typeof r.z === "number") {
				priorByVowel.set(r.vowel, r.z);
			}
		}
	}
	return current.map((row) => {
		const prior_z = priorByVowel.has(row.vowel) ? priorByVowel.get(row.vowel) : null;
		if (prior_z === null) {
			return { ...row, prior_z: null, delta: null, change_key: "no_prior" };
		}
		const delta = Math.round((row.z - prior_z) * 100) / 100;
		return { ...row, prior_z, delta, change_key: _classifyDelta(delta) };
	});
}

/**
 * Detect "pitch-compensation" divergence between two attempts. Returns a key
 * the renderer maps to a localized advisory line, or null when no divergence.
 *
 *   currentScore — current session's overall_gender_score (NN, [0,100])
 *   priorScore   — prior session's overall_gender_score; null/undefined → no advisory
 *   decorated    — output of computePerVowelDeltas; we count change_key === "regressed"
 *
 * v1 returns either "pitch_compensation" or null. Future variants (e.g. F1/F2
 * collapse subtypes) should add new keys without changing this signature.
 */
export function detectPitchCompensation(currentScore, priorScore, decorated) {
	if (typeof currentScore !== "number" || typeof priorScore !== "number") return null;
	if (currentScore - priorScore < NN_DIVERGENCE_DELTA) return null;
	if (!Array.isArray(decorated) || decorated.length < MIN_DECORATED_FOR_DIAGNOSIS) return null;
	const regressed = decorated.filter((r) => r?.change_key === "regressed").length;
	if (regressed / decorated.length < REGRESSED_RATIO_MIN) return null;
	return "pitch_compensation";
}

/**
 * Format a past timestamp as a relative phrase ("5 minutes ago", "2 days ago").
 * Returns null if the timestamp is invalid; caller decides whether to render
 * the compare header at all.
 */
export function formatRelativeTime(timestamp, locale = "zh-CN") {
	if (!timestamp || !Number.isFinite(timestamp)) return null;
	const diffMs = timestamp - Date.now();
	const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
	const abs = Math.abs(diffMs);
	const minute = 60_000;
	const hour = 60 * minute;
	const day = 24 * hour;
	const week = 7 * day;
	if (abs < hour) return rtf.format(Math.round(diffMs / minute), "minute");
	if (abs < day) return rtf.format(Math.round(diffMs / hour), "hour");
	if (abs < week) return rtf.format(Math.round(diffMs / day), "day");
	return rtf.format(Math.round(diffMs / week), "week");
}
