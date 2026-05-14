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

import { encodeWAV } from "./analyzer.js";
import { getLang, t } from "./i18n.js";

export const EXPORT_SCHEMA_VERSION = "1";

// 导入安全边界：覆盖 50 sessions × ~6 MB 内联音频的真实导出，但够紧让恶意/损坏文件
// 不能阻塞 tab。三个上限分别对应：单文件 JSON 体积、单条音频 base64 长度、文件内 session 数。
export const MAX_IMPORT_BYTES = 50 * 1024 * 1024;
export const MAX_AUDIO_B64_BYTES = 12 * 1024 * 1024;
export const MAX_SESSIONS_PER_FILE = 100;

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
 * 中文 / 韩文按字符取前 2，英文按空白切前 2 词，其它字符过滤掉。
 */
export function deriveFileBasename({ summary, filename } = {}) {
	const text = summary?.engine_c?.transcript || summary?.engine_c?.script || filename || "";
	if (text) {
		// CJK ideographs (hanzi) + Hangul precomposed syllables: one-glyph =
		// one semantic unit, just take the first 2.
		const square = text.match(/[一-鿿㐀-䶿가-힣]/g);
		if (square && square.length >= 1) return square.slice(0, 2).join("");
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
	const { summary, analysis, filename, createdAt } = session;
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
	// 历史排序需要原始"音频创建时间"。导出时透传 session.createdAt 和 audio.lastModified，
	// 导入侧才能把散点图的时间轴还原回正确位置（否则全部塞在 "now"）。
	if (Number.isFinite(createdAt) && createdAt > 0) out.created_at = createdAt;
	if (includeAudio && audioFile) {
		out.audio = {
			mime: audioFile.type || "application/octet-stream",
			name: audioFile.name || filename || "",
			base64: await blobToBase64(audioFile),
			size_bytes: audioFile.size || 0,
			last_modified:
				Number.isFinite(audioFile.lastModified) && audioFile.lastModified > 0 ? audioFile.lastModified : undefined,
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

// MIME → 扩展名兜底；audioFile.name 已带扩展名时优先信它，这里只在无名/无扩展时用。
const MIME_EXT = {
	"audio/wav": ".wav",
	"audio/x-wav": ".wav",
	"audio/wave": ".wav",
	"audio/mpeg": ".mp3",
	"audio/mp3": ".mp3",
	"audio/mp4": ".m4a",
	"audio/x-m4a": ".m4a",
	"audio/aac": ".aac",
	"audio/ogg": ".ogg",
	"audio/webm": ".webm",
	"audio/flac": ".flac",
};

function _extFromMime(mime) {
	return MIME_EXT[String(mime || "").toLowerCase()] || ".bin";
}

function _hasExt(name) {
	return /\.[A-Za-z0-9]{1,8}$/.test(name || "");
}

function _safeAudioName(audioFile, session) {
	const raw = audioFile?.name || "";
	if (raw && _hasExt(raw)) return raw;
	const stem = (raw || deriveFileBasename(session) || "recording").replace(/[/\\]+/g, "-");
	return stem + _extFromMime(audioFile?.type);
}

function _dedupeName(name, used) {
	if (!used.has(name)) return name;
	const dot = name.lastIndexOf(".");
	const stem = dot > 0 ? name.slice(0, dot) : name;
	const ext = dot > 0 ? name.slice(dot) : "";
	let i = 2;
	while (used.has(`${stem}-${i}${ext}`)) i++;
	return `${stem}-${i}${ext}`;
}

// 浏览器录音默认产出 webm/opus（或 ogg/opus），Windows 原生播放器 / iOS 相册都打不开。
// 导出时把这些容器解码后重编为 PCM WAV——无损（已经过 opus 解码）、体积变大但人人能播。
const _UNFRIENDLY_MIME = /(?:^|\/)(?:webm|ogg|opus|x-opus)\b/i;
const _UNFRIENDLY_EXT = /\.(webm|ogg|oga|opus)$/i;

function _needsWavConversion(file) {
	if (!file) return false;
	if (_UNFRIENDLY_MIME.test(file.type || "")) return true;
	return _UNFRIENDLY_EXT.test(file.name || "");
}

async function _convertToWav(file) {
	let ctx = null;
	try {
		const buf = await file.arrayBuffer();
		ctx = new (window.AudioContext || window.webkitAudioContext)();
		const audioBuf = await ctx.decodeAudioData(buf);
		const stem = (file.name || "audio").replace(/\.[^.]+$/, "") || "audio";
		const blob = encodeWAV(audioBuf);
		return new File([blob], stem + ".wav", {
			type: "audio/wav",
			lastModified: Number.isFinite(file.lastModified) && file.lastModified > 0 ? file.lastModified : Date.now(),
		});
	} catch (err) {
		console.warn("[VGA export] WAV 转码失败，回落到原文件:", err);
		return file;
	} finally {
		if (ctx)
			try {
				await ctx.close();
			} catch {}
	}
}

/**
 * 单条音频另存。沿用 downloadExport 的 createObjectURL + 隐藏 <a download> 模式。
 * 返回 { filename, size }；audioFile 缺失返回 null。
 */
export function downloadAudioFile(audioFile, suggestedName) {
	if (!audioFile) return null;
	const name = suggestedName || audioFile.name || "audio";
	const url = URL.createObjectURL(audioFile);
	const a = document.createElement("a");
	a.href = url;
	a.download = name;
	document.body.appendChild(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(url), 1000);
	return { filename: name, size: audioFile.size || 0 };
}

/**
 * 多 session 串行下载。Chrome 对 same-origin 连发 a.click() 会弹「该网站正在
 * 下载多个文件」权限请求，这是浏览器原生行为；250ms 间隔只是让事件循环喘口气，
 * 不解决拦截。冷态历史拿不到 audioFile 的算 skipped。
 */
export async function downloadAudioFilesSequential(sessions, { delayMs = 250 } = {}) {
	let downloaded = 0;
	let skipped = 0;
	const used = new Set();
	for (const s of sessions) {
		if (!s?.audioFile) {
			skipped++;
			continue;
		}
		const out = _needsWavConversion(s.audioFile) ? await _convertToWav(s.audioFile) : s.audioFile;
		const name = _dedupeName(_safeAudioName(out, s), used);
		used.add(name);
		downloadAudioFile(out, name);
		downloaded++;
		if (delayMs > 0) await new Promise((r) => setTimeout(r, delayMs));
	}
	return { downloaded, skipped };
}

/**
 * 解析导入文件。校验失败抛带 i18n key 的 Error。
 * 返回 { sessions: [{summary, analysis, filename, audioFile?}] }——
 * audioFile 是从 base64 还原的 File 对象（可塞回 audioCache）。
 */
export async function parseImportFile(file) {
	if (Number.isFinite(file?.size) && file.size > MAX_IMPORT_BYTES) {
		const mb = (file.size / 1024 / 1024).toFixed(1);
		const limit = (MAX_IMPORT_BYTES / 1024 / 1024).toFixed(0);
		const err = new Error(t("import.errTooLarge", { mb, limit }));
		err.i18n = "import.errTooLarge";
		throw err;
	}
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
	if (arr.length > MAX_SESSIONS_PER_FILE) {
		const err = new Error(t("import.errTooManySessions", { n: arr.length, limit: MAX_SESSIONS_PER_FILE }));
		err.i18n = "import.errTooManySessions";
		throw err;
	}
	// Pre-createdAt 导出文件既没顶层 session.created_at 也没 audio.last_modified；
	// wrapper 的 exported_at 自 schema v1 起就存在，是兜底"原始时间"的最后一根稻草——
	// 不一定等于录音时刻，但远比"导入时刻"接近真相。
	const exportedAtMs = (() => {
		const v = obj?.exported_at;
		if (typeof v !== "string") return null;
		const ms = Date.parse(v);
		return Number.isFinite(ms) && ms > 0 ? ms : null;
	})();
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
		// 录音时间 fallback 链：session 顶层 created_at → audio.last_modified → 包级 exported_at。
		// 先把候选值算出来；再把同一个值塞进 audioFile 的 lastModified——否则
		// `new File(..., { lastModified: undefined })` 会被规范默认成 Date.now()，
		// 让 _audioRecordedAt(audioFile) 拿到错误值。
		const audioLm = Number.isFinite(s.audio?.last_modified) && s.audio.last_modified > 0 ? s.audio.last_modified : null;
		let candidate = Number.isFinite(s.created_at) && s.created_at > 0 ? s.created_at : null;
		if (candidate == null && audioLm != null) candidate = audioLm;
		if (candidate == null && exportedAtMs != null) candidate = exportedAtMs;
		if (candidate != null) out.createdAt = candidate;
		if (s.audio?.base64) {
			// 单条音频 base64 超限：跳过音频本体（音色/波形不可还原），但仍保留 summary/analysis。
			// 优雅降级，让用户至少看到分析结果而不是整次导入失败。
			if (s.audio.base64.length > MAX_AUDIO_B64_BYTES) {
				out.audioFile = null;
			} else {
				try {
					const blob = base64ToBlob(s.audio.base64, s.audio.mime);
					const name = s.audio.name || out.filename;
					out.audioFile = new File([blob], name, {
						type: s.audio.mime || blob.type,
						// 优先 audio.last_modified（音频本体的录音时间），再退到上面整条 candidate 链。
						lastModified: audioLm ?? candidate ?? Date.now(),
					});
				} catch {
					out.audioFile = null;
				}
			}
		}
		return out;
	});
	return { sessions };
}
