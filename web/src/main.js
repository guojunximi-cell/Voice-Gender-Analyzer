import { analyzeAudio, cancelAnalysis } from "./modules/analyzer.js";
import * as audioCache from "./modules/audio-cache.js";
import { getMode, onModeChange, setMode } from "./modules/classify-mode.js";
import { classifyForMode, hasEngineC } from "./modules/classify.js";
import { buildExportPayload, downloadExport, parseImportFile } from "./modules/export-import.js";
import { isTimelineEnabled } from "./modules/feature-flag.js";
import { applyStaticDom, getLang, onLangChange, setLang, t } from "./modules/i18n.js";
import { clearMetricsPanel } from "./modules/metrics-panel.js";
import { PhoneTimeline } from "./modules/phone-timeline.js";
import { setupRecorder } from "./modules/recorder.js";
import { renderFromSummary } from "./modules/results-render.js";
import { highlightActiveSegment, renderStats, resetResults } from "./modules/results.js";
import {
	addSession,
	clearAllSessions,
	initScatter,
	loadAllSessions,
	redraw as scatterRedraw,
	removeSession as scatterRemoveSession,
	selectSession,
} from "./modules/scatter.js";
import { CUSTOM_SCRIPT_ID, scriptsForLang } from "./modules/scripts.js";
import {
	clearSessions,
	loadSessions,
	saveSession,
	removeSession as storeRemoveSession,
} from "./modules/session-store.js";
import { setupUploader } from "./modules/uploader.js";
import {
	destroyWaveform,
	drawTimeline,
	getWaveSurfer,
	initWaveform,
	togglePlay,
	updateWaveformTheme,
} from "./modules/waveform.js";
import { nextSessionColor, setToneThreshold } from "./utils.js";

// Expose i18n utilities so inline scripts in index.html (feedback modal) and
// other non-ESM consumers can reach t() / setLang without extra plumbing.
window.__vgaI18n = { t, getLang, setLang, onLangChange };

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
// When Engine C is on, script mode skips FunASR and feeds the chosen text
// straight to MFA — same phone alignment, lower CPU/RAM. Disabled and
// forced to "free" when Engine C is off. Upload tab always uses free mode
// since pre-recorded audio rarely matches a script verbatim.
//
// Script source is keyed by id ("custom" sentinel means user-supplied text
// from the textarea, otherwise it's a preset id from scripts.js).
let _recordMode = "script"; // 默认跟读；Engine C 关时强制 "free"
let _scriptId = "";
let _customScriptText = "";
let _engineCEnabled = false;
let _activeInputTab = "record";

function _getScriptList() {
	return scriptsForLang(getLang());
}

function _resolveScriptText() {
	if (_scriptId === CUSTOM_SCRIPT_ID) {
		const trimmed = (_customScriptText || "").trim();
		return trimmed || null;
	}
	const s = _getScriptList().find((it) => it.id === _scriptId);
	return s?.text ?? null;
}

function _getRecordOptions() {
	if (_activeInputTab === "upload") return { mode: "free", script: null };
	if (_recordMode !== "script") return { mode: "free", script: null };
	return { mode: "script", script: _resolveScriptText() };
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
	const isCustom = _scriptId === CUSTOM_SCRIPT_ID;
	const textEl = $("record-script-text");
	const customEl = $("record-script-custom");
	const presetHint = $("record-script-hint");
	const customHint = $("record-script-custom-hint");
	if (textEl) {
		textEl.hidden = isCustom;
		if (!isCustom) {
			const s = _getScriptList().find((it) => it.id === _scriptId);
			textEl.textContent = s?.text ?? "";
		}
	}
	if (customEl) {
		customEl.hidden = !isCustom;
		// Avoid clobbering an in-flight cursor when the value already matches.
		if (isCustom && customEl.value !== _customScriptText) {
			customEl.value = _customScriptText;
		}
	}
	if (presetHint) presetHint.hidden = isCustom;
	if (customHint) customHint.hidden = !isCustom;
	const select = $("record-script-select");
	if (select) select.value = _scriptId;
}

function _populateScriptSelect() {
	const select = $("record-script-select");
	if (!select) return;
	const list = _getScriptList();
	const presetOpts = list.map((s) => {
		const opt = document.createElement("option");
		opt.value = s.id;
		opt.textContent = s.title;
		return opt;
	});
	const customOpt = document.createElement("option");
	customOpt.value = CUSTOM_SCRIPT_ID;
	customOpt.textContent = t("record.scriptCustom");
	select.replaceChildren(...presetOpts, customOpt);
	select.value = _scriptId;
}

function _initInputMethodTabs() {
	const tabs = document.getElementById("input-method-tabs");
	if (!tabs) return;
	const panels = {
		upload: $("upload-tab-upload"),
		record: $("upload-tab-record"),
	};
	const activeBtn = tabs.querySelector(".input-method-tab.is-active");
	if (activeBtn?.dataset.tab) _activeInputTab = activeBtn.dataset.tab;
	_syncRecordModePanelVisibility();
	tabs.addEventListener("click", (e) => {
		const btn = e.target.closest(".input-method-tab");
		if (!btn || btn.classList.contains("is-active")) return;
		const target = btn.dataset.tab;
		tabs.querySelectorAll(".input-method-tab").forEach((b) => {
			const active = b === btn;
			b.classList.toggle("is-active", active);
			b.setAttribute("aria-selected", active ? "true" : "false");
		});
		for (const [name, panel] of Object.entries(panels)) {
			if (panel) panel.hidden = name !== target;
		}
		_activeInputTab = target;
		_syncRecordModePanelVisibility();
	});
}

function _syncRecordModePanelVisibility() {
	const panel = $("record-mode-panel");
	if (!panel) return;
	panel.hidden = !_engineCEnabled || _activeInputTab !== "record";
}

function _initRecordMode(engineCEnabled) {
	const panel = $("record-mode-panel");
	if (!panel) return;
	_engineCEnabled = engineCEnabled;
	if (!engineCEnabled) {
		panel.hidden = true;
		_recordMode = "free";
		return;
	}
	_syncRecordModePanelVisibility();

	const savedMode = localStorage.getItem("record-mode");
	if (savedMode === "free" || savedMode === "script") _recordMode = savedMode;

	_customScriptText = localStorage.getItem("record-custom-script") || "";
	const savedId = localStorage.getItem("record-script-id") || "";
	const list = _getScriptList();
	if (savedId === CUSTOM_SCRIPT_ID || list.find((s) => s.id === savedId)) {
		_scriptId = savedId;
	} else {
		_scriptId = list[0]?.id ?? CUSTOM_SCRIPT_ID;
	}

	_populateScriptSelect();
	_applyRecordMode();
	_renderCurrentScript();

	$("record-mode-switcher")?.addEventListener("click", (e) => {
		const btn = e.target.closest(".classify-mode-btn");
		if (!btn) return;
		_recordMode = btn.dataset.mode === "free" ? "free" : "script";
		localStorage.setItem("record-mode", _recordMode);
		_applyRecordMode();
	});

	$("record-script-select")?.addEventListener("change", (e) => {
		const id = e.target.value;
		if (id !== CUSTOM_SCRIPT_ID && !_getScriptList().find((s) => s.id === id)) return;
		_scriptId = id;
		localStorage.setItem("record-script-id", _scriptId);
		_renderCurrentScript();
	});

	$("record-script-custom")?.addEventListener("input", (e) => {
		_customScriptText = e.target.value;
		localStorage.setItem("record-custom-script", _customScriptText);
	});

	// 切语言时预设列表内容会变 —— 重画 dropdown，并在当前 id 在新列表里没有时
	// 退回到首个预设。"custom" 跨语言保留；用户的自定义文本与语言无关。
	onLangChange(() => {
		const list = _getScriptList();
		if (_scriptId !== CUSTOM_SCRIPT_ID && !list.find((s) => s.id === _scriptId)) {
			_scriptId = list[0]?.id ?? CUSTOM_SCRIPT_ID;
			localStorage.setItem("record-script-id", _scriptId);
		}
		_populateScriptSelect();
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
		btn.title = btn.disabled ? t("stats.lockedTip") : btn.dataset.originalTitle || btn.title;
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
// Fake animation messages (batch mode only). Resolved at render time via t(),
// so flipping language mid-run updates the next tick.
const _DUCK_MESSAGE_KEYS = ["duck.msg1", "duck.msg2", "duck.msg3", "duck.msg4", "duck.msg5", "duck.msg6"];
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
	if (label) label.textContent = t("duck.done");
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
	label.textContent = t(_DUCK_MESSAGE_KEYS[0]);
	_duckMsgTimer = setInterval(() => {
		msgIdx = (msgIdx + 1) % _DUCK_MESSAGE_KEYS.length;
		label.textContent = t(_DUCK_MESSAGE_KEYS[msgIdx]);
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

	// Export button only makes sense once an analysis result exists.
	const exportBtn = $("export-result-btn");
	if (exportBtn) exportBtn.hidden = next !== "results";

	// Hide waveform skeleton whenever we're not in 'loaded' phase (skeleton is shown by onFileSelected)
	if (next !== "loaded") {
		const wl = $("waveform-loading");
		if (wl) wl.style.display = "none";
	}

	const analyzing = next === "analyzing";
	const done = next === "results";
	if ($("analyze-text")) {
		$("analyze-text").textContent = analyzing
			? t("action.analyzing")
			: done
				? t("action.analyzed")
				: t("action.analyze");
	}
	if ($("analyze-spinner")) $("analyze-spinner").hidden = !analyzing;
	if ($("analyze-btn")) {
		$("analyze-btn").hidden = done;
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
		if (err.name !== "AbortError") {
			showToast(t("toast.batchItemFmt", { name: file.name, msg: err.message }), "error");
		}
		return null;
	}
}

async function onMultipleFilesSelected(files) {
	_batchInProgress = true;
	onFileSelected(files[0]); // 加载第一个文件的波形，setPhase('loaded') 但不会停鸭鸭

	// 手动触发处理中状态
	if ($("analyze-text")) $("analyze-text").textContent = t("toast.processing");
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

	showToast(t("toast.batchFmt", { ok, total: files.length }));
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
		if (cfg.tone_threshold != null) setToneThreshold(cfg.tone_threshold);
	} catch (_) {}

	_initRecordMode(engineCEnabled);

	const maxBytes = maxFileSizeMb * 1024 * 1024;

	// 更新上传区提示文字（绑定到 data-i18n 参数，便于语言切换时自动刷新）
	const hint = document.querySelector(".upload-hint");
	if (hint) {
		const params = { mb: maxFileSizeMb, min: Math.floor(maxDurationSec / 60) };
		hint.setAttribute("data-i18n", "upload.hint");
		hint.setAttribute("data-i18n-params", JSON.stringify(params));
		hint.textContent = t("upload.hint", params);
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
		onTabActivate: (tab) => {
			_activeInputTab = tab;
			_syncRecordModePanelVisibility();
		},
	});

	// Import previously exported .vga.json — single-file, JSON only.
	// 走和散点图历史还原一样的路径，把 summary/analysis/audio 灌回 UI。
	$("import-result-btn")?.addEventListener("click", () => {
		$("import-input")?.click();
	});
	$("import-input")?.addEventListener("change", async (e) => {
		const file = e.target.files?.[0];
		e.target.value = "";
		if (!file) return;
		try {
			const { sessions } = await parseImportFile(file);
			// 单 session：自动打开详情（最常见用例）。
			// 多 session：仅追加到历史，让用户在散点图自己选要看哪条。
			if (sessions.length === 1) {
				await _loadImportedSession(sessions[0]);
				showToast(t("import.successFmt", { name: sessions[0].filename }));
			} else {
				for (const s of sessions) _appendImportedToHistory(s);
				showToast(t("import.successMultiFmt", { n: sessions.length }));
			}
		} catch (err) {
			showToast(err.message, "error");
		}
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

	const recordOpts = _getRecordOptions();
	if (recordOpts.mode === "script" && !recordOpts.script) {
		showToast(t("record.scriptCustomEmpty"), "error");
		return;
	}

	setPhase("analyzing");
	resetResults();
	clearMetricsPanel();

	try {
		const data = await analyzeAudio(currentFile, {
			...recordOpts,
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

		// 4 panels: stats / segments / metrics / advice — see results-render.js.
		const segs = renderFromSummary(data);
		// Waveform overlay needs wavesurfer.duration, which is ready in 'analyzing' phase.
		drawTimeline(segs);

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
			showToast(t("toast.cancelled"), "error");
			return;
		}
		showToast(t("toast.failedFmt", { msg: err.message }), "error");
		setPhase("loaded");
	}
});

// ─── Export dialog ───────────────────────────────────────────
// 点击 "导出结果" 打开 dialog 让用户选范围（当前 / 全部历史）和内容
// （含音频 / 含 Engine C）。预估体积在 dialog 打开 + checkbox 切换时刷新。

function _formatBytes(n) {
	if (!Number.isFinite(n) || n <= 0) return "0 B";
	if (n < 1024) return `${n} B`;
	if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
	return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// 获取一个 session 对应的音频 File（若存在）。当前结果优先用 currentFile，
// 否则按 session id 查 audioCache。
async function _resolveAudioFor(session) {
	if (session === analysisData && currentFile) return currentFile;
	if (session?.id) {
		try {
			return await audioCache.get(session.id);
		} catch {
			return null;
		}
	}
	return null;
}

// 取当前 dialog scope/content 选项下涉及的 sessions + 预估音频总大小。
async function _collectSessionsForExport({ scope, includeAudio }) {
	const acc = [];
	let audioBytes = 0;
	let audioCount = 0;
	if (scope === "all") {
		const stored = await loadSessions();
		for (const s of stored) {
			let audioFile = null;
			if (includeAudio) {
				audioFile = await _resolveAudioFor(s);
				if (audioFile) {
					audioBytes += audioFile.size || 0;
					audioCount++;
				}
			}
			acc.push({ ...s, audioFile });
		}
	} else if (analysisData) {
		let audioFile = null;
		if (includeAudio) {
			audioFile = await _resolveAudioFor(analysisData);
			if (audioFile) {
				audioBytes += audioFile.size || 0;
				audioCount++;
			}
		}
		acc.push({ ...analysisData, audioFile });
	}
	return { sessions: acc, audioBytes, audioCount };
}

async function _refreshExportDialogSize() {
	const dialog = $("export-dialog");
	if (!dialog?.open) return;
	const scope = dialog.querySelector('input[name="export-scope"]:checked')?.value || "current";
	const includeAudio = $("export-include-audio")?.checked ?? false;
	const sizeEl = $("export-audio-size");
	if (!sizeEl) return;
	if (!includeAudio) {
		sizeEl.textContent = t("export.audioSizeNone");
		return;
	}
	const { audioBytes, audioCount } = await _collectSessionsForExport({ scope, includeAudio: true });
	if (audioCount === 0) {
		sizeEl.textContent = t("export.audioSizeNone");
	} else if (scope === "all") {
		sizeEl.textContent = t("export.audioSizeMultiFmt", { n: audioCount, size: _formatBytes(audioBytes) });
	} else {
		sizeEl.textContent = t("export.audioSizeFmt", { size: _formatBytes(audioBytes) });
	}
}

async function _openExportDialog() {
	const dialog = $("export-dialog");
	if (!dialog) return;
	if (!analysisData?.summary || !Array.isArray(analysisData?.analysis)) {
		showToast(t("export.errNoData"), "error");
		return;
	}

	// 重置表单 → 当前结果 + 默认勾选 audio + engine_c。
	const scopeCurrent = dialog.querySelector('input[name="export-scope"][value="current"]');
	if (scopeCurrent) scopeCurrent.checked = true;
	const audioCb = $("export-include-audio");
	const ecCb = $("export-include-engine-c");
	if (audioCb) audioCb.checked = true;
	if (ecCb) ecCb.checked = true;

	// 历史条数：散点图 / IDB 当前快照。空历史时禁用 "全部历史"。
	const stored = await loadSessions();
	const countEl = $("export-history-count");
	if (countEl) countEl.textContent = t("export.scopeAllCountFmt", { n: stored.length });
	const scopeAll = dialog.querySelector('input[name="export-scope"][value="all"]');
	if (scopeAll) scopeAll.disabled = stored.length === 0;

	if (typeof dialog.showModal === "function") dialog.showModal();
	else dialog.setAttribute("open", "");

	_refreshExportDialogSize();
}

function _closeExportDialog() {
	const dialog = $("export-dialog");
	if (!dialog) return;
	if (typeof dialog.close === "function") dialog.close();
	else dialog.removeAttribute("open");
}

async function _confirmExport() {
	const dialog = $("export-dialog");
	if (!dialog) return;
	const scope = dialog.querySelector('input[name="export-scope"]:checked')?.value || "current";
	const includeAudio = $("export-include-audio")?.checked ?? true;
	const includeEngineC = $("export-include-engine-c")?.checked ?? true;

	try {
		const { sessions } = await _collectSessionsForExport({ scope, includeAudio });
		if (sessions.length === 0) {
			showToast(t(scope === "all" ? "export.errEmptyHistory" : "export.errNoData"), "error");
			return;
		}
		const exportObj = await buildExportPayload({
			sessions,
			options: { includeAudio, includeEngineC },
		});
		const { filename, size } = downloadExport(exportObj);
		_closeExportDialog();
		showToast(t("export.successFmt", { name: filename, size: _formatBytes(size) }));
	} catch (err) {
		showToast(t("toast.failedFmt", { msg: err.message }), "error");
	}
}

$("export-result-btn")?.addEventListener("click", _openExportDialog);
$("export-dialog-cancel")?.addEventListener("click", _closeExportDialog);
$("export-dialog-confirm")?.addEventListener("click", _confirmExport);
// 切 scope / 切 include-audio 都会改变预估体积——重算一次。
$("export-dialog")?.addEventListener("change", (e) => {
	const tgt = e.target;
	if (tgt?.name === "export-scope" || tgt?.id === "export-include-audio" || tgt?.id === "export-include-engine-c") {
		_refreshExportDialogSize();
	}
});
// ESC / dialog.cancel 事件兜底
$("export-dialog")?.addEventListener("cancel", (e) => {
	e.preventDefault();
	_closeExportDialog();
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
	if ($("analyze-text")) $("analyze-text").textContent = t("action.analyzed");
	// 历史还原不走 setPhase("results")——导出按钮单独显示。
	const exportBtnRestore = $("export-result-btn");
	if (exportBtnRestore) exportBtnRestore.hidden = false;

	_updateClassifyModeSwitcher();
	// 4 panels: stats / segments / metrics / advice — see results-render.js.
	// drawTimeline 留到下面 waveform onReady 里（依赖 wavesurfer.duration）。
	renderFromSummary(session);

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

// 追加单条导入项到历史 + 散点图（不打开详情）。多 session 导入用。
function _appendImportedToHistory({ summary, analysis, filename, audioFile }) {
	if (summary?.overall_f0_median_hz == null) return null;
	const sessionId = Date.now().toString() + Math.random().toString(36).slice(2, 8);
	const session = {
		id: sessionId,
		filename: filename || "imported",
		f0_median: summary.overall_f0_median_hz,
		gender_score: summary.overall_gender_score,
		confidence: summary.overall_confidence,
		label: summary.dominant_label,
		color: nextSessionColor(),
		summary,
		analysis,
	};
	saveSession(session);
	addSession(session);
	if (audioFile) audioCache.set(sessionId, audioFile);
	return session;
}

// ─── Import previously exported result ──────────────────────
// 走和"点散点图历史 dot"几乎一样的还原路径。如果导出文件包含音频，
// 还能完整还原 player + 波形 + 卡拉 OK 同步——用户体验从冷态变成热态。
async function _loadImportedSession({ summary, analysis, filename, audioFile }) {
	if (phase === "analyzing") cancelAnalysis();

	const sessionId = Date.now().toString() + Math.random().toString(36).slice(2, 8);
	const session = {
		id: sessionId,
		filename: filename || "imported",
		f0_median: summary.overall_f0_median_hz,
		gender_score: summary.overall_gender_score,
		confidence: summary.overall_confidence,
		label: summary.dominant_label,
		color: nextSessionColor(),
		summary,
		analysis,
	};

	analysisData = session;
	// 导入的同样按"查看态"处理：锁 analyze-btn，避免误触发再分析。
	currentFile = null;
	_selectedSessionId = sessionId;

	destroyWaveform();
	if (_phoneTimeline) {
		_phoneTimeline.destroy();
		_phoneTimeline = null;
	}

	if ($("file-name")) $("file-name").textContent = session.filename;
	if ($("player-section")) $("player-section").hidden = false;
	if ($("upload-section")) $("upload-section").hidden = true;

	if ($("analyze-btn")) $("analyze-btn").disabled = true;
	if ($("analyze-text")) $("analyze-text").textContent = t("action.analyzed");
	$("delete-session-btn").hidden = false;
	const exportBtn = $("export-result-btn");
	if (exportBtn) exportBtn.hidden = false;

	_updateClassifyModeSwitcher();
	renderFromSummary(session);

	// 入历史：写 IDB session + 散点图新增一个点。导入项正常参与 LRU。
	if (summary.overall_f0_median_hz != null) {
		saveSession(session);
		addSession(session);
		selectSession(session.id);
	}

	const tlRoot = $("phone-timeline-root");
	if (_timelineEnabled && tlRoot) {
		tlRoot.hidden = false;
		_phoneTimeline = new PhoneTimeline({ container: tlRoot, wavesurfer: null });
		_phoneTimeline.setLoading();
		_phoneTimeline.setData(summary?.engine_c ?? null);
	}

	if (audioFile) {
		audioCache.set(sessionId, audioFile);
		setAudioUnavailableHint(false);
		const loading = $("waveform-loading");
		if (loading) loading.style.display = "flex";
		initWaveform(audioFile, {
			onReady: () => {
				drawTimeline(classifyForMode(session, getMode()));
				if ($("analyze-btn")) $("analyze-btn").disabled = true;
				_phoneTimeline?.attachWavesurfer(getWaveSurfer());
			},
			onTimeUpdate: (tm) => {
				if (analysisData) highlightActiveSegment(tm, analysisData.analysis);
			},
		});
	} else {
		setAudioUnavailableHint(true);
	}
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
	if (!confirm(t("toast.confirmClear"))) return;
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
	let activeTab = "metrics";

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

// ─── Language toggle ──────────────────────────────────────────
// 顶部按钮既切 UI 又切管线：同一语言决定 DICT、示例稿件库以及 POST
// /api/analyze-voice 的 `language` 字段（见 analyzer.js）。
function _updateLangToggleLabel() {
	const lbl = $("lang-toggle-label");
	if (!lbl) return;
	// 显示"去切到的语言"的首字——EN 按钮在中文态显示，中 按钮在英文态显示。
	lbl.textContent = getLang() === "zh-CN" ? t("header.langShort.en") : t("header.langShort.zh");
}

$("lang-toggle")?.addEventListener("click", () => {
	setLang(getLang() === "zh-CN" ? "en-US" : "zh-CN");
});

onLangChange(() => {
	_updateLangToggleLabel();
	_updateClassifyModeSwitcher();
	// 切语言后重刷依赖 t() 的动态区块：分段置信度、整段卡片、占比条。
	// analysisData 非空说明已经跑过一次（或从历史还原 / 导入）——都可以安全重绘。
	if (analysisData) {
		renderFromSummary(analysisData);
	}
	scatterRedraw();
});

// ─── Boot ─────────────────────────────────────────────────────
initTheme();
applyStaticDom();
_updateLangToggleLabel();
setPhase("idle");
_initInputMethodTabs();
_initClassifyModeSwitcher();
_updateClassifyModeSwitcher();
initScatterFromStorage();
