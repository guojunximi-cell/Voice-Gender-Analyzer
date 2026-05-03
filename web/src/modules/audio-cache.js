// 音频文件持久化到 IndexedDB——用户刷新或切换条目后仍能回放历史音频。
// 与 session-store 共用 vga-store 数据库。双重上限：COUNT_CAP 条 + BYTES_CAP 字节，
// 按 createdAt 升序 LRU 淘汰；任一上限超限就从最老的开始删。
// IDB 不可用（隐私模式等）时回退到内存 Map，行为与旧版一致（刷新即失）。
//
// 接口变动：get()/has() 改为 async，返回 Promise。set/remove/clear 仍为 fire-and-forget。

import { openDB, STORE_AUDIO } from "./idb.js";

const COUNT_CAP = 50;
const BYTES_CAP = 500 * 1024 * 1024; // 500 MB

const _memFallback = new Map();

function _memFallbackSet(id, file) {
	if (_memFallback.has(id)) _memFallback.delete(id); // reinsert keeps LRU order
	_memFallback.set(id, file);
	while (_memFallback.size > COUNT_CAP) {
		const oldest = _memFallback.keys().next().value;
		if (oldest === undefined) break;
		_memFallback.delete(oldest);
	}
}

export function set(id, file) {
	if (!id || !file) return;
	_put(id, file).catch((e) => {
		console.warn("audioCache.set failed, falling back to memory", e);
		_memFallbackSet(id, file);
	});
}

export async function get(id) {
	if (!id) return null;
	if (_memFallback.has(id)) return _memFallback.get(id);
	try {
		const db = await openDB();
		return await new Promise((resolve, reject) => {
			const tx = db.transaction(STORE_AUDIO, "readonly");
			const r = tx.objectStore(STORE_AUDIO).get(id);
			r.onsuccess = () => {
				const row = r.result;
				if (!row || !row.blob) {
					resolve(null);
					return;
				}
				const name = row.name || id;
				const mime = row.mime || row.blob.type || "";
				// 复原 File 时一定要带 lastModified —— 否则 File 构造器会默认成 Date.now()，
				// 把"再点一次历史散点重新分析"的 createdAt 洗成现在。
				// row.lastModified 来自原始上传/导入 File 的 mtime（_put 写入）；
				// 缺失时退化为 row.createdAt（IDB 行写入时刻），仍比 Date.now() 接近真值。
				const lastModified =
					Number.isFinite(row.lastModified) && row.lastModified > 0
						? row.lastModified
						: Number.isFinite(row.createdAt) && row.createdAt > 0
							? row.createdAt
							: Date.now();
				const file = new File([row.blob], name, { type: mime, lastModified });
				// 把已经推断出来的录音时间塞回 File 实例，省掉重新 box 解析。
				if (Number.isFinite(row.inferredCreatedAt) && row.inferredCreatedAt > 0) {
					try {
						file.__inferredCreatedAt = row.inferredCreatedAt;
					} catch {}
				}
				resolve(file);
			};
			r.onerror = () => reject(r.error);
		});
	} catch (e) {
		console.warn("audioCache.get failed", e);
		return null;
	}
}

export async function has(id) {
	if (!id) return false;
	if (_memFallback.has(id)) return true;
	try {
		const db = await openDB();
		return await new Promise((resolve, reject) => {
			const tx = db.transaction(STORE_AUDIO, "readonly");
			const r = tx.objectStore(STORE_AUDIO).getKey(id);
			r.onsuccess = () => resolve(r.result !== undefined);
			r.onerror = () => reject(r.error);
		});
	} catch {
		return false;
	}
}

export function remove(id) {
	_memFallback.delete(id);
	_remove(id).catch((e) => console.warn("audioCache.remove failed", e));
}

export function clear() {
	_memFallback.clear();
	_clearAll().catch((e) => console.warn("audioCache.clear failed", e));
}

async function _put(id, file) {
	const db = await openDB();
	const row = {
		id,
		blob: file,
		name: file.name || id,
		mime: file.type || "",
		size: file.size || 0,
		// IDB 行写入时刻——LRU 淘汰用，与下面 lastModified（音频本体的 mtime）含义不同。
		createdAt: Date.now(),
		// 音频本体的 mtime / 录音时间。复原 File 时塞回 lastModified，避免 Date.now() 默认。
		lastModified: Number.isFinite(file.lastModified) && file.lastModified > 0 ? file.lastModified : null,
		// _audioRecordedAt 已经从 MP4 元数据推断过的录音时间——存下来避免下次复原后重解析。
		inferredCreatedAt:
			Number.isFinite(file.__inferredCreatedAt) && file.__inferredCreatedAt > 0 ? file.__inferredCreatedAt : null,
	};
	await new Promise((resolve, reject) => {
		const tx = db.transaction(STORE_AUDIO, "readwrite");
		const store = tx.objectStore(STORE_AUDIO);
		store.put(row);

		// 按 createdAt 升序游标（最老的先被遍历到），只读 id+size 做淘汰决策。
		// IDB 的 Blob 是惰性引用，访问 .size / .type 不会触发磁盘读，内存占用可控。
		const cursorReq = store.index("createdAt").openCursor();
		const entries = [];
		let totalBytes = 0;
		cursorReq.onsuccess = () => {
			const c = cursorReq.result;
			if (c) {
				entries.push({ id: c.value.id, size: c.value.size || 0 });
				totalBytes += c.value.size || 0;
				c.continue();
				return;
			}
			let count = entries.length;
			let i = 0;
			while ((count > COUNT_CAP || totalBytes > BYTES_CAP) && i < entries.length) {
				if (entries[i].id === id) {
					i++;
					continue;
				}
				store.delete(entries[i].id);
				totalBytes -= entries[i].size;
				count--;
				i++;
			}
		};
		cursorReq.onerror = () => reject(cursorReq.error);
		tx.oncomplete = resolve;
		tx.onerror = () => reject(tx.error);
		tx.onabort = () => reject(tx.error ?? new Error("tx aborted"));
	});
}

async function _remove(id) {
	const db = await openDB();
	await new Promise((resolve, reject) => {
		const tx = db.transaction(STORE_AUDIO, "readwrite");
		tx.objectStore(STORE_AUDIO).delete(id);
		tx.oncomplete = resolve;
		tx.onerror = () => reject(tx.error);
	});
}

async function _clearAll() {
	const db = await openDB();
	await new Promise((resolve, reject) => {
		const tx = db.transaction(STORE_AUDIO, "readwrite");
		tx.objectStore(STORE_AUDIO).clear();
		tx.oncomplete = resolve;
		tx.onerror = () => reject(tx.error);
	});
}
