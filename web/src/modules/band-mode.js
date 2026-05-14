/**
 * band-mode.js — Heatmap band granularity toggle.
 *
 *   - phone → 每个 phone 一格（默认，原行为）
 *   - word  → 每个 char/word 一格，颜色 = 该 char 内 phones 的时长加权平均
 *
 * 镜像 scatter-mode.js：单一模块级值 + 发布订阅，写入 localStorage。
 * 命名 "char/word" 在 zh-CN 下其实是单字（一个 hanzi 一格），
 * 在 en-US / fr-FR 下是单词（一个 word 一格），底层数据结构一致
 * （groupPhonesByChar 已按 char 字段分组），所以同一个 mode 切换
 * 对三种语言都有意义。
 */

const STORAGE_KEY = "vga.timeline.bandMode";
const VALID = new Set(["phone", "word"]);

let _mode = (() => {
	try {
		const v = localStorage.getItem(STORAGE_KEY);
		return VALID.has(v) ? v : "phone";
	} catch (_) {
		return "phone";
	}
})();

const _listeners = new Set();

export function getBandMode() {
	return _mode;
}

export function setBandMode(m) {
	if (!VALID.has(m) || m === _mode) return;
	const prev = _mode;
	_mode = m;
	try {
		localStorage.setItem(STORAGE_KEY, m);
	} catch (_) {}
	for (const cb of _listeners) {
		try {
			cb(m, prev);
		} catch (_) {}
	}
}

export function onBandModeChange(cb) {
	_listeners.add(cb);
	return () => _listeners.delete(cb);
}
