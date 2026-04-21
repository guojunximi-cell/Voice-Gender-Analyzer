/**
 * engine-c-fallback.js — Empty-state / failure / low-data UI for Engine C.
 *
 * Shows contextual Chinese copy when the phone-level timeline cannot render:
 *   - Engine C failed entirely (sidecar error, MFA failed, etc.)
 *   - Empty transcript (no speech detected)
 *   - Too few phones for meaningful analysis (<8)
 */

/**
 * Render the full failure block into the given container.
 */
export function renderFallback(container) {
	container.innerHTML = `
		<section class="vga-fallback" role="alert">
			<h3>无法生成逐字时间轴</h3>
			<p>我们已经识别到音频，但未能完成逐字对齐分析。</p>
			<h4>常见原因</h4>
			<ul>
				<li>录音太短（建议 5 秒以上）</li>
				<li>非普通话内容（目前仅支持中文普通话）</li>
				<li>背景噪声过大</li>
				<li>录音中没有清晰语音</li>
			</ul>
			<h4>建议</h4>
			<ol>
				<li>在安静环境中重新录制</li>
				<li>朗读一段 10~30 秒的普通话文本</li>
				<li>保持与麦克风 15~25 cm 距离</li>
			</ol>
			<p>您仍然可以查看波形和下方的神经网络估计。</p>
		</section>`;
}

/**
 * Render the "too few phones" warning banner above the timeline.
 * @param {HTMLElement} container
 * @param {number} count
 */
export function renderLowPhoneBanner(container, count) {
	const banner = document.createElement("div");
	banner.className = "vga-low-phone-banner";
	banner.textContent = `仅检测到 ${count} 个音素，统计可能不够稳定。建议录制至少 10 秒的连续语音以获得更可靠的分析。`;
	container.prepend(banner);
}

/**
 * Render the "no speech" empty state.
 */
export function renderNoSpeech(container) {
	container.innerHTML = `
		<section class="vga-fallback">
			<h3>未检测到语音内容</h3>
			<p>音频中未找到可分析的语音。是否为纯背景音或乐器？</p>
			<p>请录制一段包含说话内容的音频后重试。</p>
		</section>`;
}
