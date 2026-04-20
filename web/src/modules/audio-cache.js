// 前端内存音频缓存：Map<sessionId, File>，用于在点击散点图历史条目时
// 还原波形播放器。不持久化、不落盘、不同步到后端——与 session-store
// 走 /api/history 的"阅后即焚"内存模型保持一致。
//
// 容量与后端 voiceya/routers/api.py 的 _HISTORY_CAP 保持一致；超出时按
// 插入序 LRU 淘汰最老条目。偶发 miss（刷新/被淘汰）由 main.js 的冷路径
// 优雅降级为"仅音素时间线"。

const AUDIO_CACHE_CAP = 50;

const _cache = new Map();

export function set(id, file) {
	if (!id || !file) return;
	if (_cache.has(id)) _cache.delete(id);
	_cache.set(id, file);
	while (_cache.size > AUDIO_CACHE_CAP) {
		const oldest = _cache.keys().next().value;
		if (oldest === undefined) break;
		_cache.delete(oldest);
	}
}

export function get(id) {
	return _cache.get(id);
}

export function has(id) {
	return _cache.has(id);
}

export function remove(id) {
	_cache.delete(id);
}

export function clear() {
	_cache.clear();
}
