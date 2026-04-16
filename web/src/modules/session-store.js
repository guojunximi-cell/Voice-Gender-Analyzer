// 历史记录存储：仅通过后端内存保存，不落盘、不用 localStorage，
// 进程退出即清空（"阅后即焚"式隐私策略）。
// 所有接口保持同步函数签名不变，内部改为异步；调用方通常无需感知
// 返回值（出错时静默降级，避免阻塞分析流程）。

const BASE = "/api/history";

async function _req(method, path = "", body) {
	const opts = { method };
	if (body !== undefined) {
		opts.headers = { "Content-Type": "application/json" };
		opts.body = JSON.stringify(body);
	}
	const res = await fetch(BASE + path, opts);
	if (!res.ok) throw new Error(`history ${method} ${path} -> ${res.status}`);
	return res.json();
}

/** Load all sessions from backend memory. */
export async function loadSessions() {
	try {
		const data = await _req("GET");
		return Array.isArray(data) ? data : [];
	} catch {
		return [];
	}
}

/**
 * Save a session to backend memory (fire-and-forget with logging).
 * session = { id, filename, f0_median, gender_score, color, summary, analysis }
 */
export function saveSession(session) {
	_req("POST", "", session).catch((e) => console.warn("saveSession failed", e));
}

/** Clear all sessions. */
export function clearSessions() {
	_req("DELETE").catch((e) => console.warn("clearSessions failed", e));
}

/** Remove a single session by id. */
export function removeSession(id) {
	_req("DELETE", `/${encodeURIComponent(id)}`).catch((e) =>
		console.warn("removeSession failed", e),
	);
}
