// Shared IndexedDB connection used by session-store.js 和 audio-cache.js。
// 两个 store 合用同一个库，清空历史时能原子性地一起清掉，避免孤儿音频 Blob。
// IDB 不可用（Safari 隐私模式等）时 openDB 会 reject，调用方自行降级到内存。

const DB_NAME = "vga-store";
const DB_VERSION = 1;
export const STORE_SESSIONS = "sessions";
export const STORE_AUDIO = "audio";

let _dbPromise = null;

export function openDB() {
	if (_dbPromise) return _dbPromise;
	_dbPromise = new Promise((resolve, reject) => {
		if (typeof indexedDB === "undefined") {
			reject(new Error("IndexedDB unavailable"));
			return;
		}
		const req = indexedDB.open(DB_NAME, DB_VERSION);
		req.onupgradeneeded = () => {
			const db = req.result;
			if (!db.objectStoreNames.contains(STORE_SESSIONS)) {
				const s = db.createObjectStore(STORE_SESSIONS, { keyPath: "id" });
				s.createIndex("createdAt", "createdAt");
			}
			if (!db.objectStoreNames.contains(STORE_AUDIO)) {
				const a = db.createObjectStore(STORE_AUDIO, { keyPath: "id" });
				a.createIndex("createdAt", "createdAt");
			}
		};
		req.onsuccess = () => resolve(req.result);
		req.onerror = () => reject(req.error);
		req.onblocked = () => reject(new Error("IndexedDB open blocked"));
	});
	_dbPromise.catch(() => {
		_dbPromise = null;
	});
	return _dbPromise;
}

export function reqOK(request) {
	return new Promise((resolve, reject) => {
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => reject(request.error);
	});
}
