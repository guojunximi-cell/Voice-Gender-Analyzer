import { analyzeAudio, cancelAnalysis } from "./modules/analyzer.js";
import * as audioCache from "./modules/audio-cache.js";
import { getMode, onModeChange, setMode } from "./modules/classify-mode.js";
import { classifyForMode, hasEngineC } from "./modules/classify.js";
import { isTimelineEnabled } from "./modules/feature-flag.js";
import { clearMetricsPanel, renderMetricsPanel } from "./modules/metrics-panel.js";
import { PhoneTimeline } from "./modules/phone-timeline.js";
import { setupRecorder } from "./modules/recorder.js";
import { highlightActiveSegment, renderSegments, renderStats, resetResults } from "./modules/results.js";
import {
	addSession,
	clearAllSessions,
	initScatter,
	loadAllSessions,
	redraw as scatterRedraw,
	removeSession as scatterRemoveSession,
	selectSession,
} from "./modules/scatter.js";
import { PRESET_SCRIPTS } from "./modules/scripts.js";
import {
	clearSessions,
	loadSessions,
	saveSession,
	removeSession as storeRemoveSession,
} from "./modules/session-store.js";
import { RESTRICTED_MAX_BYTES, setupUploader, validateFile } from "./modules/uploader.js";
import {
	destroyWaveform,
	drawTimeline,
	getWaveSurfer,
	initWaveform,
	togglePlay,
	updateWaveformTheme,
} from "./modules/waveform.js";
import { nextSessionColor } from "./utils.js";

// ─── State ────────────────────────────────────────────────────
// phases: idle | loaded | analyzing | results
let phase = "idle";
let currentFile = null;
let analysisData = null; // current API response
let _batchInProgress = false; // true while batch multi-file analysis is running

// ─── Phone timeline (Engine C) ───────────────────────────────
const _timelineEnabled = isTimelineEnabled();
let _phoneTimeline = null;

// ─── DOM shortcuts ────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

function setAudioUnavailableHint(show) {
	const el = $("audio-unavailable-hint");
	if (el) el.hidden = !show;
}

// ─── Record mode (free-speech vs. script mode for Engine C) ──────
// When Engine C is on, script mode skips FunASR and feeds the preset text
// straight to MFA — same phone alignment, lower CPU/RAM. Disabled and
// forced to "free" when Engine C is off.
let _recordMode = "script"; // 默认跟读；Engine C 关时强制 "free"
let _scriptIdx = 0;

function _getCurrentScript() {
	return PRESET_SCRIPTS[_scriptIdx % PRESET_SCRIPTS.length];
}

function _getRecordOptions() {
	if (_recordMode !== "script") return { mode: "free", script: null };
	const s = _getCurrentScript();
	return { mode: "script", script: s?.text ?? null };
}

function _applyRecordMode() {
	const switcher = $("record-mode-switcher");
	const scriptPanel = $("record-script-panel");
	if (!switcher) return;
	switcher.querySelectorAll(".classify-mode-btn").forEach((btn) => {
		const active = btn.dataset.mode === _recordMode;
		btn.classList.toggle("is-active", active);
		btn.setAttribute("aria-checked", active ? "true" : "false");
	});
	if (scriptPanel) scriptPanel.hidden = _recordMode !== "script";
}

function _renderCurrentScript() {
	const s = _getCurrentScript();
	const titleEl = $("record-script-title");
	const textEl = $("record-script-text");
	if (titleEl) titleEl.textContent = s?.title ?? "";
	if (textEl) textEl.textContent = s?.text ?? "";
}

function _initRecordMode(engineCEnabled) {
	const panel = $("record-mode-panel");
	if (!panel) return;
	if (!engineCEnabled) {
		panel.hidden = true;
		_recordMode = "free";
		return;
	}
	panel.hidden = false;

	// #upload-section 整块都是点击上传热区（uploader.js:46），面板里的任何
	// 点击都要吞掉，否则切换按钮/换稿/长按选稿都会顺带弹出文件选择框。
	panel.addEventListener("click", (e) => e.stopPropagation());

	const savedMode = localStorage.getItem("record-mode");
	if (savedMode === "free" || savedMode === "script") _recordMode = savedMode;

	const savedIdx = parseInt(localStorage.getItem("record-script-idx") || "0", 10);
	if (Number.isFinite(savedIdx) && savedIdx >= 0 && savedIdx < PRESET_SCRIPTS.length) {
		_scriptIdx = savedIdx;
	}

	_applyRecordMode();
	_renderCurrentScript();

	$("record-mode-switcher")?.addEventListener("click", (e) => {
		const btn = e.target.closest(".classify-mode-btn");
		if (!btn) return;
		_recordMode = btn.dataset.mode === "free" ? "free" : "script";
		localStorage.setItem("record-mode", _recordMode);
		_applyRecordMode();
	});

	$("record-script-next")?.addEventListener("click", () => {
		_scriptIdx = (_scriptIdx + 1) % PRESET_SCRIPTS.length;
		localStorage.setItem("record-script-idx", String(_scriptIdx));
		_renderCurrentScript();
	});
}

// ─── Classify mode (stats bar + waveform overlay + history scatter) ──
// Rebuilds the virtual segments for the currently loaded analysis whenever
// the user flips the switcher, and pushes them to the three display sites.
function _renderClassifiedForCurrent() {
	if (!analysisData) return;
	const mode = getMode();
	const segs = classifyForMode(analysisData, mode);
	// Stats cards (声音占比) + waveform overlay both consume the same shape.
	renderStats(segs);
	drawTimeline(segs);
}

function _updateClassifyModeSwitcher() {
	const switcher = $("classify-mode-switcher");
	if (!switcher) return;
	const mode = getMode();
	const ecAvailable = hasEngineC(analysisData?.summary);
	switcher.querySelectorAll(".classify-mode-btn").forEach((btn) => {
		const m = btn.dataset.mode;
		const isActive = m === mode;
		btn.classList.toggle("is-active", isActive);
		btn.setAttribute("aria-checked", isActive ? "true" : "false");
		// pitch / resonance depend on Engine C phone data — lock them out when absent.
		const needsEC = m === "pitch" || m === "resonance";
		btn.disabled = needsEC && !ecAvailable;
		btn.title = btn.disabled
			? "该文件无 Engine C 音素数据（可能 Engine C 未启用或失败）"
			: btn.dataset.originalTitle || btn.title;
	});
}

function _initClassifyModeSwitcher() {
	const switcher = $("classify-mode-switcher");
	if (!switcher) return;
	switcher.querySelectorAll(".classify-mode-btn").forEach((btn) => {
		btn.dataset.originalTitle = btn.title;
	});
	switcher.addEventListener("click", (e) => {
		const btn = e.target.closest(".classify-mode-btn");
		if (!btn || btn.disabled) return;
		setMode(btn.dataset.mode);
	});
	onModeChange(() => {
		_updateClassifyModeSwitcher();
		_renderClassifiedForCurrent();
		scatterRedraw();
	});
}

// ─── Toast ────────────────────────────────────────────────────
let toastTimer = null;
function showToast(msg, type = "") {
	const toast = $("toast");
	if (!toast) return;
	clearTimeout(toastTimer);
	toast.textContent = msg;
	toast.className = `toast show ${type}`;
	toastTimer = setTimeout(() => toast.classList.remove("show"), 4500);
}

// ─── Theme ────────────────────────────────────────────────────
function initTheme() {
	const saved = localStorage.getItem("theme");
	const preferred = saved || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
	applyTheme(preferred);
}

function applyTheme(theme) {
	document.documentElement.setAttribute("data-theme", theme);
	localStorage.setItem("theme", theme);
	updateWaveformTheme();
	scatterRedraw();
}

$("theme-toggle")?.addEventListener("click", () => {
	const cur = document.documentElement.getAttribute("data-theme");
	applyTheme(cur === "dark" ? "light" : "dark");
});

// ─── Duck progress bar ───────────────────────────────────────
// Fake animation messages (batch mode only)
const _DUCK_MESSAGES = [
	"正在聆听声纹…",
	"鸭鸭努力工作中…",
	"鸭鸭竖起了耳朵…",
	"鸭鸭在分析音高特征…",
	"鸭鸭在计算共振峰…",
	"鸭鸭快好了…",
];
let _duckRaf = null;
let _duckMsgTimer = null;
let _engineAInterp = null;
let _engineCInterp = null;
// High-water mark within a single analysis run — prevents backward motion
// when out-of-order events (e.g. Engine C start after Engine B ramp) would
// otherwise retract the bar. Reset in _finishDuck / _hideDuck.
let _duckPctHighWater = 0;
// Engine C start pct — must match backend `pct=72` in audio_analyser/__init__.py.
const ENGINE_C_START_PCT = 72;
const ENGINE_C_CAP_PCT = 94;

// ── Real progress: set duck bar to exact percentage ──────────
function _setDuckProgress(pct, msg) {
	const bar = $("duck-progress");
	const fill = $("duck-fill");
	const emoji = $("duck-emoji");
	const label = $("duck-label");
	if (!fill) return;

	const clamped = Math.max(0, Math.min(100, pct));
	const display = Math.max(clamped, _duckPctHighWater);
	_duckPctHighWater = display;

	bar.hidden = false;
	fill.style.width = display + "%";
	emoji.style.left = display + "%";
	if (msg && label) label.textContent = msg;
}

// ── Engine A interpolation (slow visual hint while Engine A blocks) ──
function _startEngineAInterp() {
	_stopEngineAInterp();
	const start = Date.now();
	const FROM = 10,
		TO = 45;
	const DURATION_MS = 90_000;

	function tick() {
		const elapsed = Date.now() - start;
		const t = Math.min(1, Math.sqrt(elapsed / DURATION_MS));
		const pct = FROM + t * (TO - FROM);
		_setDuckProgress(pct, null);
		_engineAInterp = requestAnimationFrame(tick);
	}
	_engineAInterp = requestAnimationFrame(tick);
}

function _stopEngineAInterp() {
	if (_engineAInterp) {
		cancelAnimationFrame(_engineAInterp);
		_engineAInterp = null;
	}
}

// ── Engine C interpolation (slow visual hint while sidecar runs ASR/MFA) ──
function _startEngineCInterp() {
	_stopEngineCInterp();
	const start = Date.now();
	const FROM = ENGINE_C_START_PCT,
		TO = ENGINE_C_CAP_PCT;
	// Engine C on CPU typically runs 30-120s (FunASR + MFA + Praat). ease-out
	// sqrt curve moves fast early then creeps — same pattern as Engine A interp.
	const DURATION_MS = 120_000;

	function tick() {
		const elapsed = Date.now() - start;
		const t = Math.min(1, Math.sqrt(elapsed / DURATION_MS));
		const pct = FROM + t * (TO - FROM);
		_setDuckProgress(pct, null);
		_engineCInterp = requestAnimationFrame(tick);
	}
	_engineCInterp = requestAnimationFrame(tick);
}

function _stopEngineCInterp() {
	if (_engineCInterp) {
		cancelAnimationFrame(_engineCInterp);
		_engineCInterp = null;
	}
}

// ── Finish duck: snap to 100% then hide ─────────────────────
function _finishDuck() {
	_stopEngineAInterp();
	_stopEngineCInterp();
	const bar = $("duck-progress");
	const fill = $("duck-fill");
	const emoji = $("duck-emoji");
	const label = $("duck-label");
	if (!fill) return;

	fill.style.width = "100%";
	emoji.style.left = "100%";
	if (label) label.textContent = "分析完成 🎉";
	setTimeout(() => {
		if (bar) bar.hidden = true;
		fill.style.width = "0%";
		emoji.style.left = "0%";
		_duckPctHighWater = 0;
	}, 800);
}

// ── Hide duck immediately (error / cancel) ──────────────────
function _hideDuck() {
	_stopEngineAInterp();
	_stopEngineCInterp();
	// Also cancel fake animation if running
	cancelAnimationFrame(_duckRaf);
	clearInterval(_duckMsgTimer);
	_duckRaf = null;
	const bar = $("duck-progress");
	const fill = $("duck-fill");
	const emoji = $("duck-emoji");
	if (!fill) return;
	if (bar) bar.hidden = true;
	fill.style.width = "0%";
	emoji.style.left = "0%";
	_duckPctHighWater = 0;
}

// ── Fake animation (initial wait + batch mode) ──────────────
function _startDuckFake() {
	// Cancel any previous fake animation before starting a new one
	cancelAnimationFrame(_duckRaf);
	clearInterval(_duckMsgTimer);
	_duckRaf = null;

	const bar = $("duck-progress");
	const fill = $("duck-fill");
	const emoji = $("duck-emoji");
	const label = $("duck-label");
	if (!bar) return;

	bar.hidden = false;
	fill.style.width = "0%";
	emoji.style.left = "0%";
	_duckPctHighWater = 0;

	const start = Date.now();
	const MAX_PCT = 88;
	const DURATION_MS = 100_000;

	function tick() {
		const elapsed = Date.now() - start;
		const pct = Math.min(MAX_PCT, Math.sqrt(elapsed / DURATION_MS) * MAX_PCT);
		fill.style.width = pct + "%";
		emoji.style.left = Math.max(0, Math.min(100, pct)) + "%";
		_duckRaf = requestAnimationFrame(tick);
	}
	_duckRaf = requestAnimationFrame(tick);

	let msgIdx = 0;
	label.textContent = _DUCK_MESSAGES[0];
	_duckMsgTimer = setInterval(() => {
		msgIdx = (msgIdx + 1) % _DUCK_MESSAGES.length;
		label.textContent = _DUCK_MESSAGES[msgIdx];
	}, 4000);
}

function _stopDuckFake(success = true) {
	cancelAnimationFrame(_duckRaf);
	clearInterval(_duckMsgTimer);
	_duckRaf = null;

	if (success) {
		_finishDuck();
	} else {
		_hideDuck();
	}
}

// ─── Phase transitions ────────────────────────────────────────
function setPhase(next) {
	phase = next;

	$("upload-section").hidden = next !== "idle";
	$("player-section").hidden = next === "idle";

	// Hide waveform skeleton whenever we're not in 'loaded' phase (skeleton is shown by onFileSelected)
	if (next !== "loaded") {
		const wl = $("waveform-loading");
		if (wl) wl.style.display = "none";
	}

	const analyzing = next === "analyzing";
	const done = next === "results";
	if ($("analyze-text")) $("analyze-text").textContent = analyzing ? "分析中…" : done ? "已分析" : "开始分析";
	if ($("analyze-spinner")) $("analyze-spinner").hidden = !analyzing;
	if ($("analyze-btn")) {
		$("analyze-btn").disabled = analyzing || done;
		const icon = $("analyze-btn").querySelector("svg");
		if (icon) icon.style.display = analyzing ? "none" : "";
	}

	if (next === "analyzing") {
		_startDuckFake();
		// Show timeline skeleton while analysis is in progress
		if (_timelineEnabled) {
			const root = $("phone-timeline-root");
			if (root) {
				root.hidden = false;
				_phoneTimeline = new PhoneTimeline({ container: root, wavesurfer: getWaveSurfer() });
				_phoneTimeline.setLoading();
			}
		}
	} else if (next === "results") {
		_finishDuck();
	} else if (!_batchInProgress) {
		_hideDuck();
	}
}

// ─── File loaded ──────────────────────────────────────────────
function onFileSelected(file) {
	cancelAnalysis();
	currentFile = file;
	analysisData = null;
	resetResults();
	clearMetricsPanel();
	if (_phoneTimeline) {
		_phoneTimeline.destroy();
		_phoneTimeline = null;
	}
	const tlRoot = $("phone-timeline-root");
	if (tlRoot) tlRoot.hidden = true;

	$("file-name").textContent = file.name;

	setPhase("loaded");
	$("waveform-loading").style.display = "flex";

	initWaveform(file, {
		onReady: (_dur) => {
			/* controls already enabled in waveform.js */
		},
		onTimeUpdate: (t) => {
			if (analysisData) highlightActiveSegment(t, analysisData.analysis);
		},
	});
}

// ─── Batch analyze (multiple files, no waveform preview) ─────
async function _silentAnalyzeAndSave(file) {
	try {
		const data = await analyzeAudio(file, _getRecordOptions());
		if (data.summary?.overall_f0_median_hz != null) {
			const session = {
				id: Date.now().toString() + Math.random().toString(36).slice(2, 8),
				filename: data.filename,
				f0_median: data.summary.overall_f0_median_hz,
				gender_score: data.summary.overall_gender_score,
				confidence: data.summary.overall_confidence,
				label: data.summary.dominant_label,
				color: nextSessionColor(),
				summary: data.summary,
				analysis: data.analysis,
			};
			saveSession(session);
			audioCache.set(session.id, file);
			addSession(session);
		}
		return data;
	} catch (err) {
		if (err.name !== "AbortError") showToast(`${file.name} 失败：${err.message}`, "error");
		return null;
	}
}

async function onMultipleFilesSelected(files) {
	_batchInProgress = true;
	onFileSelected(files[0]); // 加载第一个文件的波形，setPhase('loaded') 但不会停鸭鸭

	// 手动触发处理中状态
	if ($("analyze-text")) $("analyze-text").textContent = "处理中…";
	if ($("analyze-spinner")) $("analyze-spinner").hidden = false;
	if ($("analyze-btn")) {
		$("analyze-btn").disabled = true;
		const icon = $("analyze-btn").querySelector("svg");
		if (icon) icon.style.display = "none";
	}
	_startDuckFake();

	// 分批发送请求（每次最多 2 个），避免同时发出所有请求导致服务器 503
	const BATCH_SIZE = 2;
	let ok = 0;
	for (let i = 0; i < files.length; i += BATCH_SIZE) {
		const batch = files.slice(i, i + BATCH_SIZE);
		const results = await Promise.allSettled(batch.map((f) => _silentAnalyzeAndSave(f)));
		ok += results.filter((r) => r.status === "fulfilled" && r.value).length;
	}

	_batchInProgress = false;
	_stopDuckFake(ok > 0);

	// 批量完成后标记为 results 状态，防止用户重复分析第一个文件
	setPhase("results");

	showToast(`批量分析完成：${ok} / ${files.length} 个成功`);
}

// ─── Uploaders ────────────────────────────────────────────────
async function initUploaders() {
	let allowConcurrent = false;
	let maxFileSizeMb = 5;
	let maxDurationSec = 180;
	let engineCEnabled = false;
	try {
		const cfg = await fetch("/api/config").then((r) => r.json());
		allowConcurrent = cfg.allow_concurrent ?? cfg.max_concurrent > 1;
		maxFileSizeMb = cfg.max_file_size_mb ?? 5;
		maxDurationSec = cfg.max_audio_duration_sec ?? 180;
		engineCEnabled = !!cfg.engine_c_enabled;
	} catch (_) {}

	_initRecordMode(engineCEnabled);

	const maxBytes = maxFileSizeMb * 1024 * 1024;

	// 更新上传区提示文字
	const hint = document.querySelector(".upload-hint");
	if (hint) {
		hint.textContent = `支持 MP3 · WAV · OGG · M4A · FLAC · 最大 ${maxFileSizeMb} MB / ${Math.floor(maxDurationSec / 60)} 分钟`;
	}

	setupUploader({
		onFile: onFileSelected,
		onFiles: allowConcurrent ? onMultipleFilesSelected : null,
		onError: (msg) => showToast(msg, "error"),
		multiple: allowConcurrent,
		maxBytes,
	});

	setupRecorder({
		onFile: onFileSelected,
		onError: (msg) => showToast(msg, "error"),
	});

	// Scatter panel upload button (always available, single file only)
	$("scatter-file-input")?.addEventListener("change", (e) => {
		const file = e.target.files?.[0];
		if (!file) {
			e.target.value = "";
			return;
		}
		const err = validateFile(file, maxBytes);
		if (err) {
			showToast(err, "error");
			e.target.value = "";
			return;
		}
		onFileSelected(file);
		e.target.value = "";
	});
}

initUploaders();

// Change file button in player
$("change-file-btn")?.addEventListener("click", () => {
	cancelAnalysis();
	destroyWaveform();
	resetResults();
	clearMetricsPanel();
	if (_phoneTimeline) {
		_phoneTimeline.destroy();
		_phoneTimeline = null;
	}
	const tlRoot = $("phone-timeline-root");
	if (tlRoot) tlRoot.hidden = true;
	setAudioUnavailableHint(false);
	currentFile = null;
	analysisData = null;
	setPhase("idle");
});

// ─── Play / Pause ─────────────────────────────────────────────
$("play-btn")?.addEventListener("click", togglePlay);

// ─── Analyze ──────────────────────────────────────────────────
$("analyze-btn")?.addEventListener("click", async () => {
	if (!currentFile || phase === "analyzing") return;

	setPhase("analyzing");
	resetResults();
	clearMetricsPanel();

	try {
		const data = await analyzeAudio(currentFile, {
			..._getRecordOptions(),
			onProgress(pct, msg) {
				// First real SSE event: stop fake animation and switch to real progress
				if (_duckRaf !== null) {
					cancelAnimationFrame(_duckRaf);
					clearInterval(_duckMsgTimer);
					_duckRaf = null;
				}

				if (pct > 10) _stopEngineAInterp();
				if (pct > ENGINE_C_START_PCT) _stopEngineCInterp();

				if (pct === 10) {
					_setDuckProgress(10, msg);
					_startEngineAInterp();
				} else if (pct === ENGINE_C_START_PCT) {
					_setDuckProgress(ENGINE_C_START_PCT, msg);
					_startEngineCInterp();
				} else {
					_setDuckProgress(pct, msg);
				}
			},
		});
		analysisData = data;

		// Sync classify mode buttons (lock pitch/resonance when no Engine C)
		_updateClassifyModeSwitcher();

		// Stats cards + waveform overlay both follow the current classify mode.
		const segs = classifyForMode(data, getMode());
		drawTimeline(segs);
		renderStats(segs);

		// Segment list always reflects Engine A — it's the "AI 分段详情" card.
		renderSegments(data.analysis);

		// Whole-file acoustic averages (Engine C + duration-weighted Engine A).
		// Rendered once here — no per-segment updates.
		renderMetricsPanel(data.summary, data.analysis);

		// Feed Engine C data to phone timeline
		if (_phoneTimeline && data.summary?.engine_c) {
			_phoneTimeline.setData(data.summary.engine_c);
		} else if (_phoneTimeline) {
			_phoneTimeline.setData(null);
		}

		setPhase("results");

		// ── Save session & update scatter plot ─────────────────
		if (data.summary.overall_f0_median_hz != null) {
			const session = {
				id: Date.now().toString() + Math.random().toString(36).slice(2, 8),
				filename: data.filename,
				f0_median: data.summary.overall_f0_median_hz,
				gender_score: data.summary.overall_gender_score,
				confidence: data.summary.overall_confidence,
				label: data.summary.dominant_label,
				color: nextSessionColor(),
				summary: data.summary,
				analysis: data.analysis,
			};
			saveSession(session);
			audioCache.set(session.id, currentFile);
			addSession(session);
			selectSession(session.id);
		}
	} catch (err) {
		if (err.name === "AbortError") {
			if (phase === "analyzing") setPhase("loaded");
			showToast("分析超时，请尝试较短的音频文件", "error");
			return;
		}
		showToast(`分析失败：${err.message}`, "error");
		setPhase("loaded");
	}
});

// ─── Scatter dot click → restore session ────────────────────
let _selectedSessionId = null;

async function onScatterDotClick(session) {
	// 若正在分析，先取消——避免与历史还原竞争 _phoneTimeline / 波形的构建
	if (phase === "analyzing") cancelAnalysis();

	_selectedSessionId = session.id;
	$("delete-session-btn").hidden = false;
	analysisData = session;
	// 历史视图只读：不允许对它再次点"开始分析"，避免 analyze-btn 状态混乱
	currentFile = null;

	// 拆旧波形与音素时间线，再按 session 重建——这也让条目之间切换时
	// 音素时间线会正确刷新到目标条目的 engine_c
	destroyWaveform();
	if (_phoneTimeline) {
		_phoneTimeline.destroy();
		_phoneTimeline = null;
	}

	// Player chrome
	if ($("file-name")) $("file-name").textContent = session.filename;
	if ($("player-section")) $("player-section").hidden = false;
	if ($("upload-section")) $("upload-section").hidden = true;

	// 历史是查看态：强制锁 analyze-btn 防 setPhase 残留把它解锁
	if ($("analyze-btn")) $("analyze-btn").disabled = true;
	if ($("analyze-text")) $("analyze-text").textContent = "已分析";

	_updateClassifyModeSwitcher();
	const _segs = classifyForMode(session, getMode());
	renderStats(_segs);
	renderSegments(session.analysis);
	renderMetricsPanel(session.summary, session.analysis);

	const tlRoot = $("phone-timeline-root");
	const cachedFile = await audioCache.get(session.id);
	// 快速连点不同条目时，后发制人：await 期间若选择已被切走就放弃当前还原
	if (_selectedSessionId !== session.id) return;

	// 音素时间线独立于音频加载：先立即渲染（无卡拉 OK 同步），
	// 热路径的 waveform onReady 再补挂 wavesurfer 启用同步。
	// setLoading 必须先于 setData——否则 _rendered=false 会让 setData 静默早返回。
	if (_timelineEnabled && tlRoot) {
		tlRoot.hidden = false;
		_phoneTimeline = new PhoneTimeline({ container: tlRoot, wavesurfer: null });
		_phoneTimeline.setLoading();
		_phoneTimeline.setData(session.summary?.engine_c ?? null);
	}

	if (cachedFile) {
		// Hot：内存/IDB 里还有原文件，完整还原播放器 + 卡拉 OK 同步
		setAudioUnavailableHint(false);
		const loading = $("waveform-loading");
		if (loading) loading.style.display = "flex";
		initWaveform(cachedFile, {
			onReady: () => {
				// 段落 overlay 依赖 waveform 模块内部的 duration，必须在 ready 后画
				drawTimeline(classifyForMode(session, getMode()));
				// waveform.js 的 ready handler 会把 analyze-btn 重新启用，这里再锁回去
				if ($("analyze-btn")) $("analyze-btn").disabled = true;
				_phoneTimeline?.attachWavesurfer(getWaveSurfer());
			},
			onTimeUpdate: (t) => {
				if (analysisData) highlightActiveSegment(t, analysisData.analysis);
			},
		});
	} else {
		// Cold：缓存里没有原文件（首刷被淘汰等），段落用右侧列表承担
		// （段落 overlay 依赖 waveform duration，duration===0 时 drawTimeline 会 no-op）。
		setAudioUnavailableHint(true);
	}
}

function onScatterDeselect() {
	_selectedSessionId = null;
	$("delete-session-btn").hidden = true;
}

// ─── Delete single session ────────────────────────────────────
$("delete-session-btn")?.addEventListener("click", () => {
	if (!_selectedSessionId) return;
	audioCache.remove(_selectedSessionId);
	storeRemoveSession(_selectedSessionId);
	scatterRemoveSession(_selectedSessionId);
	_selectedSessionId = null;
	$("delete-session-btn").hidden = true;
});

// ─── Clear sessions ───────────────────────────────────────────
$("clear-sessions-btn")?.addEventListener("click", () => {
	if (!confirm("清空所有历史分析记录？")) return;
	clearSessions();
	audioCache.clear();
	clearAllSessions();
	_selectedSessionId = null;
	analysisData = null;
	$("delete-session-btn").hidden = true;
	resetResults();
	clearMetricsPanel();
	if (phase === "results") setPhase(currentFile ? "loaded" : "idle");
});

// ─── Init scatter with stored sessions ───────────────────────
async function initScatterFromStorage() {
	initScatter($("scatter-canvas"), {
		onDotClick: onScatterDotClick,
		onDeselect: onScatterDeselect,
	});
	const stored = await loadSessions();
	if (stored.length) loadAllSessions(stored);
}

// ─── Mobile: collapsible left panel ──────────────────────────
(function initMobilePanel() {
	const mq = matchMedia("(max-width: 780px)");
	const leftPanel = document.querySelector(".panel-left");
	const leftHeader = leftPanel?.querySelector(".panel-header");
	if (!leftPanel || !leftHeader) return;

	// Start expanded on mobile so the chart is visible by default
	if (mq.matches) leftPanel.classList.add("panel-expanded");

	leftHeader.addEventListener("click", () => {
		if (!mq.matches) return;
		leftPanel.classList.toggle("panel-expanded");
	});

	// Reset on resize to desktop; expand when entering mobile
	mq.addEventListener("change", (e) => {
		if (!e.matches) leftPanel.classList.remove("panel-expanded");
		else leftPanel.classList.add("panel-expanded");
	});
})();

// ─── Mobile: tabs for segments / metrics ─────────────────────
(function initMobileTabs() {
	const mq = matchMedia("(max-width: 780px)");
	const tabBar = $("mobile-tabs");
	const segSection = $("segments-section");
	const rightPanel = document.querySelector(".panel-right");
	if (!tabBar || !rightPanel) return;

	const tabs = tabBar.querySelectorAll(".mobile-tab");
	let activeTab = "segments";

	function applyTab(tab) {
		activeTab = tab;
		tabs.forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
		if (!mq.matches) {
			// Desktop: show everything
			segSection?.classList.remove("mobile-hidden");
			rightPanel.classList.remove("mobile-hidden");
			return;
		}
		if (tab === "segments") {
			segSection?.classList.remove("mobile-hidden");
			rightPanel.classList.add("mobile-hidden");
		} else {
			segSection?.classList.add("mobile-hidden");
			rightPanel.classList.remove("mobile-hidden");
		}
	}

	tabBar.addEventListener("click", (e) => {
		const btn = e.target.closest(".mobile-tab");
		if (!btn) return;
		applyTab(btn.dataset.tab);
	});

	// Show tab bar when stats are visible (results phase)
	const observer = new MutationObserver(() => {
		const statsVisible = !$("stats-section")?.hidden;
		tabBar.hidden = !statsVisible;
		if (statsVisible && mq.matches) applyTab(activeTab);
	});
	const statsEl = $("stats-section");
	if (statsEl) observer.observe(statsEl, { attributes: true, attributeFilter: ["hidden"] });

	// Auto-switch to metrics when a segment is clicked on mobile
	document.addEventListener("segment-select", () => {
		if (mq.matches) {
			applyTab("metrics");
		}
	});

	// Reset on resize to desktop
	mq.addEventListener("change", (e) => {
		if (!e.matches) {
			segSection?.classList.remove("mobile-hidden");
			rightPanel.classList.remove("mobile-hidden");
		} else {
			applyTab(activeTab);
		}
	});
})();

// ─── Boot ─────────────────────────────────────────────────────
initTheme();
setPhase("idle");
_initClassifyModeSwitcher();
_updateClassifyModeSwitcher();
initScatterFromStorage();
