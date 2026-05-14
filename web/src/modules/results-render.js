// 把面板渲染抽出来：analyze 成功路径、历史还原、导入文件、切语言重渲染
// 都共用这一组——避免漂移。
//
// 故意只管"不依赖波形 ready 的"那几步：stats / metrics / resonance。
// drawTimeline（依赖 wavesurfer.duration）和 _phoneTimeline.setData（依赖
// 时间线生命周期）由调用方按各自时机处理。返回值 segs 方便调用方在波形
// ready 后直接 drawTimeline(segs)。

import { getMode } from "./classify-mode.js";
import { classifyForMode } from "./classify.js";
import { renderMetricsPanel } from "./metrics-panel.js";
import { renderResonancePanel } from "./resonance-panel.js";
import { renderStats } from "./results.js";

/**
 * @param {{summary: object, analysis: object[], createdAt?: number}} session
 * @returns {object[]} classified segments for the current classify mode
 *
 * `createdAt` is forwarded to renderResonancePanel so the same-script history
 * compare can pick a strictly-earlier prior attempt. Restored sessions carry
 * their saved timestamp; fresh analysis results don't, and the panel falls
 * back to Date.now() (safe — the new session isn't saved yet at render time).
 */
export function renderFromSummary({ summary, analysis, createdAt }) {
	const segs = classifyForMode({ summary, analysis }, getMode());
	renderStats(segs);
	renderMetricsPanel(summary, analysis);
	renderResonancePanel(summary?.advice?.resonance_panel, { summary, createdAt });
	return segs;
}
