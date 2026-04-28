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

import { certaintTag, fmt, LABEL_META } from "../utils.js";
import { t } from "./i18n.js";

function animNum(el, target, suffix = "", duration = 600) {
	if (!el) return;
	const start = performance.now();
	const from = parseFloat(el.dataset.current || 0) || 0;
	el.dataset.current = target;
	function tick(now) {
		const p = Math.min((now - start) / duration, 1);
		const ease = 1 - Math.pow(1 - p, 3);
		el.textContent = Math.round(from + (target - from) * ease) + suffix;
		if (p < 1) requestAnimationFrame(tick);
	}
	requestAnimationFrame(tick);
}

function animBar(el, pct, delay = 0) {
	if (!el) return;
	setTimeout(() => {
		el.style.width = `${Math.max(0, Math.min(100, pct))}%`;
	}, delay);
}

// ─── Aggregators ─────────────────────────────────────────────
function _meanFormants(phones) {
	const pick = (k) => {
		if (!phones?.length) return null;
		const vs = [];
		for (const p of phones) {
			const v = p[k];
			if (v != null && v > 0) vs.push(v);
		}
		return vs.length ? vs.reduce((a, b) => a + b, 0) / vs.length : null;
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
	const empty = document.getElementById("metrics-empty");
	const content = document.getElementById("metrics-content");
	if (!empty || !content) return;

	const ec = summary?.engine_c;
	if (!ec || !ec.phones?.length) {
		empty.innerHTML = `<svg width="32" height="32" viewBox="0 0 32 32" fill="none" opacity="0.3" aria-hidden="true"><circle cx="16" cy="16" r="14" stroke="currentColor" stroke-width="1.5"/><path d="M10 16 Q13 10 16 16 Q19 22 22 16" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg><span>${t("metrics.noEngineC")}</span>`;
		empty.hidden = false;
		content.hidden = true;
		return;
	}

	empty.hidden = true;
	content.hidden = false;

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

	// ── F0 card ─────────────────────────────────────────────
	// 卡片上的数字与下方"音高范围"指示器必须同源，否则 164 Hz 的文字会配
	// 落在 200 Hz 附近的滑块，看起来自相矛盾。统一走 median（更鲁棒，也
	// 与后端 overall_f0_median_hz 命名一致），mean 仅作 fallback。
	const pitch = ec.median_pitch_hz ?? ec.mean_pitch_hz;
	const pitchStd = ec.stdev_pitch_hz;
	animNum(document.getElementById("mc-f0-median"), Math.round(pitch ?? 0), " Hz");
	const stdEl = document.getElementById("mc-f0-std");
	if (stdEl) stdEl.textContent = `±${pitchStd != null ? Math.round(pitchStd) : "—"} Hz`;

	// ── Resonance card (0..1 → percent) ─────────────────────
	const resPct = ec.mean_resonance != null ? Math.round(ec.mean_resonance * 100) : 0;
	animNum(document.getElementById("mc-res-val"), resPct, "%");
	animBar(document.getElementById("mc-res-bar"), resPct, 80);

	// ── Formants (frontend-computed phone mean) ─────────────
	const { f1, f2, f3 } = _meanFormants(ec.phones);
	const setFormant = (id, val) => {
		const el = document.getElementById(id);
		if (el) el.textContent = val != null ? `${Math.round(val)} Hz` : "—";
	};
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
	const empty = document.getElementById("metrics-empty");
	const content = document.getElementById("metrics-content");
	if (empty) {
		empty.innerHTML = `<svg width="32" height="32" viewBox="0 0 32 32" fill="none" opacity="0.3" aria-hidden="true"><circle cx="16" cy="16" r="14" stroke="currentColor" stroke-width="1.5"/><path d="M10 16 Q13 10 16 16 Q19 22 22 16" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg><span>${t("metrics.emptyUpload")}</span>`;
		empty.hidden = false;
	}
	if (content) content.hidden = true;
	const warnEl = document.getElementById("mc-align-warning");
	if (warnEl) warnEl.hidden = true;
	clearAdvicePanel();
}

// ─── Advice v2 panel ─────────────────────────────────────────
// Renders summary.advice. Two surfaces:
//   1. #advice-panel (always available): one-sentence summary + gating warning.
//      Independent of Engine C — visible whenever summary.advice exists.
//   2. #mc-f0-zone (inside the Engine-C pitch card): zone label chip
//      ("中低基频" / "声学中性区间" …) sourced from f0_panel.range_zone_key.
// See docs/plans/v2_redesign_measurement.md §1, §3.
export function renderAdvicePanel(advice) {
	const panel = document.getElementById("advice-panel");
	const zoneEl = document.getElementById("mc-f0-zone");
	if (!panel) return;
	if (!advice) {
		panel.hidden = true;
		if (zoneEl) zoneEl.hidden = true;
		return;
	}
	panel.hidden = false;

	const warnEl = document.getElementById("advice-warning");
	const warnText = document.getElementById("advice-warning-text");
	const firstWarn = advice.warnings?.[0];
	if (warnEl && warnText && firstWarn) {
		warnText.textContent = t(firstWarn.key, firstWarn.params || {});
		warnEl.hidden = false;
	} else if (warnEl) {
		warnEl.hidden = true;
	}

	const summaryEl = document.getElementById("advice-summary");
	if (summaryEl) {
		if (advice.summary_panel) {
			summaryEl.textContent = t(advice.summary_panel.text_key, advice.summary_panel.text_params || {});
			summaryEl.hidden = false;
		} else {
			summaryEl.hidden = true;
		}
	}

	const zoneKey = advice.f0_panel?.range_zone_key;
	if (zoneEl) {
		if (zoneKey) {
			zoneEl.textContent = t(`advice.zone.${zoneKey}`);
			zoneEl.dataset.zone = zoneKey;
			zoneEl.hidden = false;
		} else {
			zoneEl.hidden = true;
		}
	}
}

export function clearAdvicePanel() {
	const panel = document.getElementById("advice-panel");
	if (panel) panel.hidden = true;
	const zoneEl = document.getElementById("mc-f0-zone");
	if (zoneEl) zoneEl.hidden = true;
}
