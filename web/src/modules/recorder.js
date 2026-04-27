import { t } from "./i18n.js";

export function setupRecorder({ onFile, onError, onTabActivate }) {
	if (!navigator.mediaDevices?.getUserMedia) {
		// No mic API: hide the record tab and force the upload tab to be active
		// (record is the default for users with mics; without a mic we silently
		// fall back so the visible UI is never empty).
		document.getElementById("upload-tab-record")?.setAttribute("hidden", "");
		const recordTabBtn = document.querySelector('.input-method-tab[data-tab="record"]');
		recordTabBtn?.setAttribute("hidden", "");
		recordTabBtn?.classList.remove("is-active");
		recordTabBtn?.setAttribute("aria-selected", "false");
		const uploadPanel = document.getElementById("upload-tab-upload");
		uploadPanel?.removeAttribute("hidden");
		const uploadTabBtn = document.querySelector('.input-method-tab[data-tab="upload"]');
		uploadTabBtn?.classList.add("is-active");
		uploadTabBtn?.setAttribute("aria-selected", "true");
		onTabActivate?.("upload");
		return;
	}

	const idleUI = document.getElementById("recorder-idle-ui");
	const activeUI = document.getElementById("recorder-active-ui");
	const micBtn = document.getElementById("recorder-mic-btn");
	const stopBtn = document.getElementById("recorder-stop-btn");
	const timerEl = document.getElementById("recorder-timer");

	micBtn.addEventListener("click", (e) => {
		e.stopPropagation();
		_start();
	});
	stopBtn.addEventListener("click", (e) => {
		e.stopPropagation();
		_stop();
	});

	const MAX_RECORD_SEC = 180; // 最多录制 3 分钟
	let _mr = null,
		_chunks = [],
		_stream = null,
		_timer = null,
		_secs = 0,
		_vizCtx = null,
		_analyser = null,
		_raf = null;

	async function _start() {
		try {
			_stream = await navigator.mediaDevices.getUserMedia({ audio: true });
		} catch (err) {
			const msg =
				err.name === "NotAllowedError"
					? t("recorder.noPermission")
					: err.name === "NotFoundError"
						? t("recorder.noDevice")
						: t("recorder.noAccess");
			onError(msg);
			return;
		}

		const mime =
			["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/ogg"].find((m) =>
				MediaRecorder.isTypeSupported(m),
			) ?? "";
		_mr = new MediaRecorder(_stream, mime ? { mimeType: mime } : {});
		_chunks = [];

		_mr.addEventListener("dataavailable", (e) => {
			if (e.data.size > 0) _chunks.push(e.data);
		});
		_mr.addEventListener("stop", _finish);
		_mr.addEventListener("error", (e) => _cleanup(t("recorder.recordError", { msg: e.error?.message ?? "" })));
		_mr.start(200);
		_startViz(_stream);

		idleUI.hidden = true;
		activeUI.hidden = false;
		_secs = 0;
		timerEl.textContent = "0:00";
		_timer = setInterval(() => {
			_secs++;
			timerEl.textContent = `${Math.floor(_secs / 60)}:${String(_secs % 60).padStart(2, "0")}`;
			if (_secs >= MAX_RECORD_SEC) _stop();
		}, 1000);
	}

	function _stop() {
		if (!_mr || _mr.state === "inactive") return;
		clearInterval(_timer);
		_timer = null;
		_stopViz();
		_stream.getTracks().forEach((t) => t.stop());
		_stream = null;
		_mr.stop();
		idleUI.hidden = false;
		activeUI.hidden = true;
		timerEl.textContent = "0:00";
	}

	function _finish() {
		const mime = _mr?.mimeType || "audio/webm";
		const ext = mime.includes("ogg") ? ".ogg" : ".webm";
		const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
		const file = new File(_chunks, `${t("recorder.filenamePrefix")}-${ts}${ext}`, { type: mime });
		_mr = null;
		_chunks = [];
		if (file.size === 0) {
			onError(t("recorder.empty"));
			return;
		}
		onFile(file);
	}

	function _cleanup(errMsg) {
		clearInterval(_timer);
		_timer = null;
		_stopViz();
		_stream?.getTracks().forEach((t) => t.stop());
		_stream = null;
		_mr = null;
		_chunks = [];
		idleUI.hidden = false;
		activeUI.hidden = true;
		timerEl.textContent = "0:00";
		if (errMsg) onError(errMsg);
	}

	function _startViz(stream) {
		const canvas = document.getElementById("recorder-waveform");
		if (!canvas) return;
		try {
			_vizCtx = new (window.AudioContext || window.webkitAudioContext)();
			_analyser = _vizCtx.createAnalyser();
			_analyser.fftSize = 256;
			_analyser.smoothingTimeConstant = 0.75;
			_vizCtx.createMediaStreamSource(stream).connect(_analyser);
		} catch (_) {
			return;
		}

		const dpr = Math.min(window.devicePixelRatio || 1, 2);
		const BAR_COUNT = 30;
		const freqData = new Uint8Array(_analyser.frequencyBinCount);
		const smoothed = new Float32Array(BAR_COUNT);
		const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#c96442";
		let lastW = 0, lastH = 0;

		function draw() {
			_raf = requestAnimationFrame(draw);
			const cssW = canvas.clientWidth;
			const cssH = canvas.clientHeight;
			if (cssW !== lastW || cssH !== lastH) {
				canvas.width = Math.round(cssW * dpr);
				canvas.height = Math.round(cssH * dpr);
				lastW = cssW;
				lastH = cssH;
			}
			const cw = canvas.width, ch = canvas.height;
			if (cw === 0 || ch === 0) return;

			_analyser.getByteFrequencyData(freqData);
			const c2d = canvas.getContext("2d");
			c2d.clearRect(0, 0, cw, ch);

			const gap = 2 * dpr;
			const barW = (cw - gap * (BAR_COUNT - 1)) / BAR_COUNT;

			for (let i = 0; i < BAR_COUNT; i++) {
				const idx = Math.floor((i / BAR_COUNT) * freqData.length * 0.6);
				const raw = freqData[idx] / 255;
				smoothed[i] += (raw - smoothed[i]) * 0.3;
				const barH = Math.max(2 * dpr, smoothed[i] * ch * 0.88);
				const x = i * (barW + gap);
				const y = (ch - barH) / 2;
				const r = Math.min(3 * dpr, barW / 2, barH / 2);
				c2d.globalAlpha = 0.3 + smoothed[i] * 0.7;
				c2d.fillStyle = accent;
				c2d.beginPath();
				if (c2d.roundRect) c2d.roundRect(x, y, barW, barH, r);
				else c2d.rect(x, y, barW, barH);
				c2d.fill();
			}
			c2d.globalAlpha = 1;
		}
		draw();
	}

	function _stopViz() {
		if (_raf) { cancelAnimationFrame(_raf); _raf = null; }
		if (_vizCtx) { _vizCtx.close().catch(() => {}); _vizCtx = null; }
		_analyser = null;
		const canvas = document.getElementById("recorder-waveform");
		if (canvas) canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
	}
}
