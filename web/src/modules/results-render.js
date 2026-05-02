// 把 4 个面板渲染抽出来：analyze 成功路径、历史还原、导入文件、切语言重渲染
// 都共用这一组——避免漂移。
//
// 故意只管"不依赖波形 ready 的"那几步：stats / segments / metrics / advice。
// drawTimeline（依赖 wavesurfer.duration）和 _phoneTimeline.setData（依赖
// 时间线生命周期）由调用方按各自时机处理。返回值 segs 方便调用方在波形
// ready 后直接 drawTimeline(segs)。

import { getMode } from "./classify-mode.js";
import { classifyForMode } from "./classify.js";
import { renderAdvicePanel, renderMetricsPanel } from "./metrics-panel.js";
import { renderSegments, renderStats } from "./results.js";

/**
 * @param {{summary: object, analysis: object[]}} session
 * @returns {object[]} classified segments for the current classify mode
 */
export function renderFromSummary({ summary, analysis }) {
	const segs = classifyForMode({ summary, analysis }, getMode());
	renderStats(segs);
	renderSegments(analysis);
	renderMetricsPanel(summary, analysis);
	renderAdvicePanel(summary?.advice);
	return segs;
}
