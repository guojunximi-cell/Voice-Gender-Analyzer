export function setupRecorder({ onFile, onError }) {
	if (!navigator.mediaDevices?.getUserMedia) {
		document.getElementById("recorder-idle-ui")?.remove();
		document.querySelector(".upload-divider")?.remove();
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
		_secs = 0;

	async function _start() {
		try {
			_stream = await navigator.mediaDevices.getUserMedia({ audio: true });
		} catch (err) {
			const msg =
				err.name === "NotAllowedError"
					? "请允许麦克风权限后重试"
					: err.name === "NotFoundError"
						? "未找到麦克风设备"
						: "无法访问麦克风";
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
		_mr.addEventListener("error", (e) => _cleanup("录制出错：" + (e.error?.message ?? "")));
		_mr.start(200);

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
		const file = new File(_chunks, `录音-${ts}${ext}`, { type: mime });
		_mr = null;
		_chunks = [];
		if (file.size === 0) {
			onError("录音内容为空，请重新录制");
			return;
		}
		onFile(file);
	}

	function _cleanup(errMsg) {
		clearInterval(_timer);
		_timer = null;
		_stream?.getTracks().forEach((t) => t.stop());
		_stream = null;
		_mr = null;
		_chunks = [];
		idleUI.hidden = false;
		activeUI.hidden = true;
		timerEl.textContent = "0:00";
		if (errMsg) onError(errMsg);
	}
}
