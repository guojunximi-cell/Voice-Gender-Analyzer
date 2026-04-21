// 历史记录存储：持久化在浏览器 IndexedDB 中，刷新和切换音频都不丢。
// 老版本走 /api/history 的"阅后即焚"内存模型已下线；现在数据留在用户本地磁盘，
// 只能由用户主动清空（见 main.js 的"清空历史"按钮）。
//
// 所有写接口都是 fire-and-forget（签名保留 void），调用方无需感知异步；
// 出错时只打日志，不阻塞分析流程。容量上限 CAP 条，按 createdAt 升序 LRU 淘汰。

import { STORE_SESSIONS, openDB, reqOK } from "./idb.js";

const CAP = 50;

export async function loadSessions() {
	try {
		const db = await openDB();
		const tx = db.transaction(STORE_SESSIONS, "readonly");
		const rows = await reqOK(tx.objectStore(STORE_SESSIONS).index("createdAt").getAll());
		return Array.isArray(rows) ? rows : [];
	} catch (e) {
		console.warn("loadSessions failed", e);
		return [];
	}
}

export function saveSession(session) {
	_put(session).catch((e) => console.warn("saveSession failed", e));
}

export function clearSessions() {
	_clearAll().catch((e) => console.warn("clearSessions failed", e));
}

export function removeSession(id) {
	_remove(id).catch((e) => console.warn("removeSession failed", e));
}

async function _put(session) {
	const db = await openDB();
	const row = { ...session, createdAt: session.createdAt ?? Date.now() };
	await new Promise((resolve, reject) => {
		const tx = db.transaction(STORE_SESSIONS, "readwrite");
		const store = tx.objectStore(STORE_SESSIONS);
		store.put(row);
		const countReq = store.count();
		countReq.onsuccess = () => {
			const need = countReq.result - CAP;
			if (need <= 0) return;
			const cursorReq = store.index("createdAt").openCursor();
			let removed = 0;
			cursorReq.onsuccess = () => {
				const c = cursorReq.result;
				if (!c || removed >= need) return;
				if (c.value.id !== row.id) {
					c.delete();
					removed++;
				}
				c.continue();
			};
		};
		tx.oncomplete = resolve;
		tx.onerror = () => reject(tx.error);
		tx.onabort = () => reject(tx.error ?? new Error("tx aborted"));
	});
}

async function _remove(id) {
	const db = await openDB();
	await new Promise((resolve, reject) => {
		const tx = db.transaction(STORE_SESSIONS, "readwrite");
		tx.objectStore(STORE_SESSIONS).delete(id);
		tx.oncomplete = resolve;
		tx.onerror = () => reject(tx.error);
	});
}

async function _clearAll() {
	const db = await openDB();
	await new Promise((resolve, reject) => {
		const tx = db.transaction(STORE_SESSIONS, "readwrite");
		tx.objectStore(STORE_SESSIONS).clear();
		tx.oncomplete = resolve;
		tx.onerror = () => reject(tx.error);
	});
}
