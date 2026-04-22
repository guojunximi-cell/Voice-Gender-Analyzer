// POST /api/analyze-voice
// Body: multipart/form-data — audio (file) + mode ("free" | "script") + script (optional string)
// Response: { status, filename, summary, analysis: [{label, start_time, end_time, duration}] }

const _controllers = new Set();

const TIMEOUT_MS = 360_000; // 6 minutes (Railway CPU is slower than local)
const STRIP_MAX_BYTES = 5 * 1024 * 1024; // skip stripping for files > 5 MB

// ─── Metadata stripping ──────────────────────────────────────
// Decode audio with AudioContext, re-encode as bare 16-bit PCM WAV.
// This removes all ID3/EXIF metadata (device model, location, author, etc.)
// before the audio leaves the browser.  Falls back to the original file
// if the file is too large or the browser cannot decode the format.

function _writeStr(view, off, str) {
	for (let i = 0; i < str.length; i++) view.setUint8(off + i, str.charCodeAt(i));
}

function _encodeWAV(ab) {
	const numCh = ab.numberOfChannels;
	const sr = ab.sampleRate;
	const frames = ab.length;
	const data = frames * numCh * 2; // 16-bit PCM
	const buf = new ArrayBuffer(44 + data);
	const v = new DataView(buf);

	_writeStr(v, 0, "RIFF");
	v.setUint32(4, 36 + data, true);
	_writeStr(v, 8, "WAVE");
	_writeStr(v, 12, "fmt ");
	v.setUint32(16, 16, true);
	v.setUint16(20, 1, true); // PCM
	v.setUint16(22, numCh, true);
	v.setUint32(24, sr, true);
	v.setUint32(28, sr * numCh * 2, true); // byte rate
	v.setUint16(32, numCh * 2, true); // block align
	v.setUint16(34, 16, true); // bits/sample
	_writeStr(v, 36, "data");
	v.setUint32(40, data, true);

	let off = 44;
	for (let i = 0; i < frames; i++) {
		for (let ch = 0; ch < numCh; ch++) {
			const s = ab.getChannelData(ch)[i];
			v.setInt16(off, Math.max(-32768, Math.min(32767, Math.round(s * 32767))), true);
			off += 2;
		}
	}
	return new Blob([buf], { type: "audio/wav" });
}

async function _stripMetadata(file) {
	if (file.size > STRIP_MAX_BYTES) {
		console.info("[声音分析鸭] 文件较大，跳过元数据剥离:", file.name);
		return file;
	}
	let ctx = null;
	try {
		const arrayBuf = await file.arrayBuffer();
		ctx = new (window.AudioContext || window.webkitAudioContext)();
		const audioBuf = await ctx.decodeAudioData(arrayBuf);

		// 压缩格式解码为 PCM WAV 后体积会暴增（10-20 倍），
		// 如果解码后超过原始大小的 5 倍就放弃剥离，直接用原始文件。
		const estimatedBytes = 44 + audioBuf.length * audioBuf.numberOfChannels * 2;
		if (estimatedBytes > file.size * 5) {
			console.info(
				"[声音分析鸭] 解码后体积过大（%s MB → %s MB），跳过元数据剥离",
				(file.size / 1024 / 1024).toFixed(1),
				(estimatedBytes / 1024 / 1024).toFixed(1),
			);
			return file;
		}

		const strippedName = file.name.replace(/\.[^.]+$/, "") + ".wav";
		return new File([_encodeWAV(audioBuf)], strippedName, { type: "audio/wav" });
	} catch (err) {
		console.warn("[声音分析鸭] 元数据剥离失败，使用原始文件:", err);
		return file;
	} finally {
		if (ctx)
			try {
				await ctx.close();
			} catch (_) {}
	}
}

// ─── SSE stream reader ───────────────────────────────────────

async function _readSSEStream(response, onProgress) {
	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = "";
	let resultData = null;

	try {
		while (true) {
			const { done, value } = await reader.read();
			if (done) break;

			buffer += decoder.decode(value, { stream: true });

			let boundary;
			while ((boundary = buffer.indexOf("\n\n")) !== -1) {
				const eventText = buffer.slice(0, boundary);
				buffer = buffer.slice(boundary + 2);

				for (const line of eventText.split("\n")) {
					if (!line.startsWith("data: ")) continue;
					const payload = JSON.parse(line.slice(6));

					if (payload.type === "progress") {
						onProgress(payload.pct, payload.msg);
					} else if (payload.type === "result") {
						onProgress(100, "分析完成 🎉");
						resultData = payload.data;
					} else if (payload.type === "error") {
						throw new Error(payload.msg || "后端分析出错");
					}
				}
			}
		}
	} finally {
		reader.releaseLock();
	}

	if (!resultData) throw new Error("未收到分析结果");
	if (resultData.status === "error") throw new Error(resultData.message || "后端分析出错");
	return resultData;
}

// ─────────────────────────────────────────────────────────────

export async function analyzeAudio(file, { onProgress, mode = "free", script = null } = {}) {
	const controller = new AbortController();
	_controllers.add(controller);

	const strippedFile = await _stripMetadata(file);
	// 超时从 fetch 开始计时，不包含元数据剥离耗时
	const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);

	// 两步调用：
	//   1) POST /api/analyze-voice —— 上传音频、拿到 task_id（后端把任务压进
	//      taskiq 队列就立刻返回，不等分析完成）
	//   2) GET  /api/status/{task_id} (Accept: text/event-stream) —— 订阅
	//      worker 推到 Redis Stream 的进度/结果事件。
	// 以前是一个 POST 配 303 让浏览器自动跟随，但 POST→303→GET 这条链在
	// fetch / 代理 / curl 下各踩各的坑，拆成两步后定位问题就清爽了。

	const fd = new FormData();
	fd.append("audio", strippedFile);
	fd.append("mode", mode === "script" ? "script" : "free");
	if (mode === "script" && script) fd.append("script", script);

	try {
		const submitResp = await fetch("/api/analyze-voice", {
			method: "POST",
			body: fd,
			signal: controller.signal,
			// multipart boundary: 让浏览器自动加，手动写 Content-Type 会少 boundary
		});

		if (!submitResp.ok) {
			let msg = `请求失败 (${submitResp.status})`;
			try {
				const err = await submitResp.json();
				msg = err.detail || err.message || msg;
			} catch (_) {}
			throw new Error(msg);
		}

		const { task_id } = await submitResp.json();
		if (!task_id) throw new Error("后端未返回 task_id");

		// 有 onProgress 才走 SSE；否则降级轮询不在当前场景要求之内，抛错更明确
		if (!onProgress) {
			throw new Error("analyzeAudio 需要 onProgress 回调才能订阅进度流");
		}

		const streamResp = await fetch(`/api/status/${encodeURIComponent(task_id)}`, {
			method: "GET",
			signal: controller.signal,
			headers: { Accept: "text/event-stream" },
		});

		clearTimeout(timeoutId);

		if (!streamResp.ok) {
			throw new Error(`订阅进度失败 (${streamResp.status})`);
		}

		return await _readSSEStream(streamResp, onProgress);
	} catch (err) {
		clearTimeout(timeoutId);
		throw err;
	} finally {
		_controllers.delete(controller);
	}
}

export function cancelAnalysis() {
	for (const c of _controllers) c.abort();
	_controllers.clear();
}
