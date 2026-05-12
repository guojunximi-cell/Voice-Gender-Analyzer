/**
 * metrics-panel.js — Right panel: whole-file acoustic averages.
 *
 * Data sources:
 *   - Engine C (`summary.engine_c`) → pitch / resonance / F1-F3 (phone-mean)
 *   - Engine A (`analysis[]`)       → duration-weighted classifier confidence
 *
 * Rendered once per analysis (not per segment click).  When `summary.engine_c`
 * is null (Engine C disabled or failed), the panel shows a static notice.
 */

import { certaintTag, fmt } from "../utils.js";
import { setBlockHasContent } from "./dashboard.js";
import { t } from "./i18n.js";
import { clearResonancePanel } from "./resonance-panel.js";

// ─── Aggregators ─────────────────────────────────────────────
function _medianFormants(phones) {
	const pick = (k) => {
		if (!phones?.length) return null;
		const vs = [];
		for (const p of phones) {
			const v = p[k];
			if (v != null && v > 0) vs.push(v);
		}
		if (!vs.length) return null;
		vs.sort((a, b) => a - b);
		const m = vs.length >> 1;
		return vs.length % 2 ? vs[m] : (vs[m - 1] + vs[m]) / 2;
	};
	return { f1: pick("F1"), f2: pick("F2"), f3: pick("F3") };
}

// Duration-weighted Engine A confidence, grouped by male/female.
// Returns the dominant-by-duration side with its weighted confidence, so the
// single gender thumb reflects the file as a whole rather than one segment.
function _weightedEngineA(analysis) {
	if (!analysis?.length) return null;
	let mDur = 0,
		mConf = 0,
		fDur = 0,
		fConf = 0;
	for (const s of analysis) {
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
	if (mDur === 0 && fDur === 0) return null;
	const label = fDur >= mDur ? "female" : "male";
	const conf = label === "female" ? fConf / fDur : mConf / mDur;
	return { label, confidence: Math.min(1, Math.max(0, conf)), speechSec: mDur + fDur };
}

// ─── Public: render whole-file averages ──────────────────────
export function renderMetricsPanel(summary, analysis) {
	const ec = summary?.engine_c;
	const hasEC = !!(ec && ec.phones?.length);
	// Pitch + Formants are Engine C-derived (phone-mean F0, median formants).
	setBlockHasContent("pitch", hasEC);
	setBlockHasContent("formants", hasEC);
	// NN block depends on the analysis array, not Engine C.
	const hasNN = Array.isArray(analysis) && analysis.length > 0;
	setBlockHasContent("nn", hasNN);
	if (!hasEC) return;

	// ── 对齐质量提示 ─────────────────────────────────────────
	// phone_ratio < 0.8 / coverage < 0.3 时后端已标 low_quality，附上具体
	// 百分比让用户判断到底是漏读还是干脆没读。script 模式下最常见原因是
	// 跳读；free 模式下常见原因是噪音太大被 MFA 吞掉。
	const warnEl = document.getElementById("mc-align-warning");
	const warnTextEl = document.getElementById("mc-align-warning-text");
	const ac = ec.alignment_confidence;
	if (warnEl) {
		if (ac?.low_quality) {
			const parts = [];
			if (ac.phone_ratio != null) parts.push(t("metrics.alignPhoneRatio", { ratio: ac.phone_ratio.toFixed(2) }));
			if (ac.coverage != null) parts.push(t("metrics.alignCoverage", { pct: Math.round(ac.coverage * 100) }));
			const hint = t(ec.mode === "script" ? "metrics.alignHintScript" : "metrics.alignHintFree");
			if (warnTextEl) warnTextEl.textContent = `${hint}（${parts.join("，")}）`;
			warnEl.hidden = false;
		} else {
			warnEl.hidden = true;
		}
	}

	// ── F0 + Formants (frontend-computed phone mean) ────────
	// F0 与下方"音高范围"指示器同源（median，与后端 overall_f0_median_hz
	// 命名一致；mean 仅作 fallback），避免 164 Hz 的文字配在 200 Hz 附近
	// 的滑块上自相矛盾。
	const pitch = ec.median_pitch_hz;
	const pitchStd = ec.stdev_pitch_hz;
	const { f1, f2, f3 } = _medianFormants(ec.phones);

	const pitchMedianTag = document.getElementById("mc-pitch-median-tag");
	if (pitchMedianTag) {
		if (pitch != null) {
			pitchMedianTag.textContent = `${Math.round(pitch)} Hz`;
			pitchMedianTag.hidden = false;
		} else {
			pitchMedianTag.hidden = true;
		}
	}
	const setFormant = (id, val) => {
		const el = document.getElementById(id);
		if (el) el.textContent = val != null ? `${Math.round(val)} Hz` : "—";
	};
	setFormant("mc-f0", pitch);
	setFormant("mc-f1", f1);
	setFormant("mc-f2", f2);
	setFormant("mc-f3", f3);

	// ── Pitch range reference bar ───────────────────────────
	// 整个范围条都是线性 Hz 刻度（ticks 用 space-between，zones 按线性 Hz 算宽度）。
	// 之前 log2 映射会把 166 Hz 推到 53%（= "200" 位置），视觉不一致。
	const hzToPct = (hz) => ((Math.max(80, Math.min(320, hz)) - 80) / (320 - 80)) * 100;

	// 范围条：优先从 phones.pitch 取 p5~p95（比 min/max 抗 outlier）；
	// 样本不足时兜底为 median ± stdev。
	const rangeEl = document.getElementById("mc-pitch-range");
	if (rangeEl) {
		const pitches = (ec.phones || [])
			.map((p) => p.pitch)
			.filter((v) => typeof v === "number" && v >= 40 && v <= 600)
			.sort((a, b) => a - b);
		let lo, hi;
		if (pitches.length >= 5) {
			lo = pitches[Math.floor(pitches.length * 0.05)];
			hi = pitches[Math.floor(pitches.length * 0.95)];
		} else if (pitch != null && pitchStd != null) {
			lo = pitch - pitchStd;
			hi = pitch + pitchStd;
		}
		if (lo != null && hi != null && hi > lo) {
			const loPct = hzToPct(lo);
			const hiPct = hzToPct(hi);
			requestAnimationFrame(() => {
				rangeEl.style.left = `${loPct}%`;
				rangeEl.style.width = `${hiPct - loPct}%`;
			});
		} else {
			rangeEl.style.width = "0";
		}
	}

	// Median tick：与上面卡片的 pitch 同值，落在范围条内部作为中位标记。
	const pitchIndicator = document.getElementById("mc-pitch-indicator");
	if (pitchIndicator && pitch) {
		requestAnimationFrame(() => {
			pitchIndicator.style.left = `${hzToPct(pitch)}%`;
		});
	}

	// ── Duration-weighted Engine A summary ──────────────────
	const weighted = _weightedEngineA(analysis);

	// ── Header label: overall speech duration ───────────────
	const headerLabel = document.getElementById("mc-segment-label");
	if (headerLabel) {
		headerLabel.textContent = weighted
			? t("metrics.headerOverallSpeech", { dur: fmt(weighted.speechSec) })
			: t("metrics.headerOverall");
	}

	// ── Certainty tag (reuses the segment-shaped util) ──────
	const tagEl = document.getElementById("mc-certainty-tag");
	if (tagEl) {
		const tag = weighted ? certaintTag(weighted) : "";
		tagEl.textContent = tag;
		tagEl.hidden = !tag;
	}
}

export function clearMetricsPanel() {
	setBlockHasContent("pitch", false);
	setBlockHasContent("formants", false);
	setBlockHasContent("nn", false);
	const warnEl = document.getElementById("mc-align-warning");
	if (warnEl) warnEl.hidden = true;
	clearResonancePanel();
}
