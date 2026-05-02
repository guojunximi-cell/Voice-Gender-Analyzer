// 结果导出 / 导入：把一次或多次分析的 summary + analysis（可选含原音频）打包成
// 单个 .vga.json 文件，导入时还原到历史。完全跑在浏览器，不走后端。
//
// 数据形态：
//   { export_schema_version: "1", exported_at, ui_locale, app_version,
//     payload: { sessions: [ {filename, summary, analysis, audio?} ] } }
//   audio = { mime, name, base64, size_bytes } 可选——用户在导出对话框里
//   勾掉"包含原音频"或冷态历史项无音频可取时，就跳过。
//   单/多 session 都用同一个 sessions 数组形态（长度 1 也是数组）。
//
// i18n：导出时 advice 字段保留 i18n key + params（advice_v2 输出格式），
// 导入按当前 UI locale 重渲染——切换语言后导入旧文件自动跟随。

import { getLang, t } from "./i18n.js";

export const EXPORT_SCHEMA_VERSION = "1";

// vite define 注入；非 build 环境兜底成 0.0.0。
const APP_VERSION = typeof __APP_VERSION__ !== "undefined" ? __APP_VERSION__ : "0.0.0";

function blobToBase64(blob) {
	return new Promise((resolve, reject) => {
		const r = new FileReader();
		r.onload = () => {
			const s = String(r.result || "");
			const i = s.indexOf(",");
			resolve(i >= 0 ? s.slice(i + 1) : s);
		};
		r.onerror = () => reject(r.error);
		r.readAsDataURL(blob);
	});
}

function base64ToBlob(b64, mime) {
	const bin = atob(b64);
	const u8 = new Uint8Array(bin.length);
	for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
	return new Blob([u8], { type: mime || "application/octet-stream" });
}

/**
 * 从 transcript / script / filename 推一个文件名词缀。
 * 中文按字符取前 2，英文按空白切前 2 词，其它字符过滤掉。
 */
export function deriveFileBasename({ summary, filename } = {}) {
	const text = summary?.engine_c?.transcript || summary?.engine_c?.script || filename || "";
	if (text) {
		const cjk = text.match(/[一-鿿㐀-䶿]/g);
		if (cjk && cjk.length >= 1) return cjk.slice(0, 2).join("");
		const tokens = text
			.replace(/\.[a-zA-Z0-9]{1,8}$/, "")
			.split(/[\s\-_]+/)
			.map((s) => s.replace(/[^A-Za-z0-9]/g, ""))
			.filter(Boolean);
		if (tokens.length) return tokens.slice(0, 2).join("-");
	}
	return "recording";
}

function buildExportFilename(basename, date = new Date()) {
	const pad = (n) => String(n).padStart(2, "0");
	const stamp =
		date.getFullYear().toString() +
		pad(date.getMonth() + 1) +
		pad(date.getDate()) +
		"-" +
		pad(date.getHours()) +
		pad(date.getMinutes());
	const safe =
		(basename || "recording")
			.replace(/[^\w一-鿿㐀-䶿-]+/g, "-")
			.replace(/^-+|-+$/g, "")
			.slice(0, 40) || "recording";
	return `vga-${safe}-${stamp}.vga.json`;
}

/**
 * 把单个 session 转成导出格式。可选剥除 engine_c 音素数据 / 内联音频。
 * 注意：confidence_frames 无论如何都丢弃（前端不消费，体积可观）。
 */
async function _serializeSession(session, { includeAudio, includeEngineC, audioFile }) {
	const { summary, analysis, filename } = session;
	const slimAnalysis = (Array.isArray(analysis) ? analysis : []).map((seg) => {
		const { confidence_frames: _drop, ...rest } = seg ?? {};
		return rest;
	});
	let slimSummary = summary;
	if (!includeEngineC && summary && "engine_c" in summary) {
		const { engine_c: _drop, ...rest } = summary;
		slimSummary = rest;
	}
	const out = {
		filename: filename || "",
		summary: slimSummary,
		analysis: slimAnalysis,
	};
	if (includeAudio && audioFile) {
		out.audio = {
			mime: audioFile.type || "application/octet-stream",
			name: audioFile.name || filename || "",
			base64: await blobToBase64(audioFile),
			size_bytes: audioFile.size || 0,
		};
	}
	return out;
}

/**
 * 构造导出 payload。
 * @param sessions [{summary, analysis, filename, audioFile?}]
 * @param options {includeAudio, includeEngineC}
 */
export async function buildExportPayload({ sessions, options = {} }) {
	if (!Array.isArray(sessions) || sessions.length === 0) {
		throw new Error("buildExportPayload: empty sessions");
	}
	const opts = {
		includeAudio: options.includeAudio !== false,
		includeEngineC: options.includeEngineC !== false,
	};
	const serialized = [];
	for (const s of sessions) {
		serialized.push(
			await _serializeSession(s, {
				includeAudio: opts.includeAudio,
				includeEngineC: opts.includeEngineC,
				audioFile: s.audioFile,
			}),
		);
	}
	return {
		export_schema_version: EXPORT_SCHEMA_VERSION,
		exported_at: new Date().toISOString(),
		ui_locale: getLang(),
		app_version: APP_VERSION,
		source: "vga",
		payload: { sessions: serialized },
	};
}

/**
 * 触发浏览器下载。文件名根据 sessions 数量选不同策略：
 * 单 session：vga-<前2token>-<stamp>.vga.json
 * 多 session：vga-history-<N>-<stamp>.vga.json
 */
export function downloadExport(exportObj) {
	const sessions = exportObj?.payload?.sessions || [];
	const basename = sessions.length === 1 ? deriveFileBasename(sessions[0]) : `history-${sessions.length}`;
	const filename = buildExportFilename(basename);
	const blob = new Blob([JSON.stringify(exportObj, null, 2)], { type: "application/json" });
	const url = URL.createObjectURL(blob);
	const a = document.createElement("a");
	a.href = url;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(url), 1000);
	return { filename, size: blob.size };
}

/**
 * 解析导入文件。校验失败抛带 i18n key 的 Error。
 * 返回 { sessions: [{summary, analysis, filename, audioFile?}] }——
 * audioFile 是从 base64 还原的 File 对象（可塞回 audioCache）。
 */
export async function parseImportFile(file) {
	let text;
	try {
		text = await file.text();
	} catch {
		const err = new Error(t("import.errParse"));
		err.i18n = "import.errParse";
		throw err;
	}
	let obj;
	try {
		obj = JSON.parse(text);
	} catch {
		const err = new Error(t("import.errParse"));
		err.i18n = "import.errParse";
		throw err;
	}
	const ver = obj?.export_schema_version;
	if (ver !== EXPORT_SCHEMA_VERSION) {
		const err = new Error(t("import.errSchemaFmt", { version: String(ver ?? "?") }));
		err.i18n = "import.errSchemaFmt";
		throw err;
	}
	const arr = obj?.payload?.sessions;
	if (!Array.isArray(arr) || arr.length === 0) {
		const err = new Error(t("import.errMalformed"));
		err.i18n = "import.errMalformed";
		throw err;
	}
	const sessions = arr.map((s) => {
		if (!s?.summary || !Array.isArray(s.analysis)) {
			const err = new Error(t("import.errMalformed"));
			err.i18n = "import.errMalformed";
			throw err;
		}
		const out = {
			filename: s.filename || file.name.replace(/\.vga\.json$/i, "") || "imported",
			summary: s.summary,
			analysis: s.analysis,
		};
		if (s.audio?.base64) {
			try {
				const blob = base64ToBlob(s.audio.base64, s.audio.mime);
				const name = s.audio.name || out.filename;
				out.audioFile = new File([blob], name, { type: s.audio.mime || blob.type });
			} catch {
				out.audioFile = null;
			}
		}
		return out;
	});
	return { sessions };
}
