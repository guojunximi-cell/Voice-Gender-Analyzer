const ACCEPTED_TYPES = [
	"audio/mpeg",
	"audio/wav",
	"audio/ogg",
	"audio/mp4",
	"audio/x-m4a",
	"audio/m4a",
	"audio/flac",
	"audio/aac",
	"audio/webm",
];
const ACCEPTED_EXTS = [".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".opus", ".aiff", ".au", ".caf", ".webm"];
export const DEFAULT_MAX_BYTES = 5 * 1024 * 1024; // 5 MB
export const RESTRICTED_MAX_BYTES = 5 * 1024 * 1024; // 5 MB（非并发模式）

export function validateFile(file, maxBytes = DEFAULT_MAX_BYTES) {
	if (!file) return "No file selected";
	if (file.size === 0) return "文件内容为空，请重新选择。";

	const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
	const isAudio = file.type.startsWith("audio/") || ACCEPTED_TYPES.includes(file.type) || ACCEPTED_EXTS.includes(ext);
	if (!isAudio) return `不支持的格式：${file.type || ext || "未知"}。请上传音频文件。`;

	if (file.size > maxBytes) {
		const mb = (file.size / 1024 / 1024).toFixed(1);
		const limitMb = (maxBytes / 1024 / 1024).toFixed(0);
		return `文件过大（${mb} MB），当前模式最大支持 ${limitMb} MB。`;
	}

	return null; // valid
}

export function setupUploader({ onFile, onFiles, onError, multiple = false, maxBytes = DEFAULT_MAX_BYTES }) {
	const section = document.getElementById("upload-section");
	const fileInput = document.getElementById("file-input");
	const browseBtn = document.getElementById("browse-btn");

	if (fileInput) fileInput.multiple = multiple;

	// Click to browse
	browseBtn?.addEventListener("click", (e) => {
		e.stopPropagation();
		fileInput.click();
	});

	section?.addEventListener("click", () => fileInput.click());

	fileInput?.addEventListener("change", () => {
		_handleFiles([...fileInput.files], multiple, onFile, onFiles, onError, maxBytes);
		fileInput.value = "";
	});

	// Drag & drop
	section?.addEventListener("dragover", (e) => {
		e.preventDefault();
		section.classList.add("drag-over");
	});

	section?.addEventListener("dragleave", (e) => {
		if (!section.contains(e.relatedTarget)) {
			section.classList.remove("drag-over");
		}
	});

	section?.addEventListener("drop", (e) => {
		e.preventDefault();
		section.classList.remove("drag-over");
		_handleFiles([...e.dataTransfer.files], multiple, onFile, onFiles, onError, maxBytes);
	});
}

function _handleFiles(files, multiple, onFile, onFiles, onError, maxBytes) {
	if (!multiple) {
		// Single mode: ignore extra files, take only the first
		const err = validateFile(files[0], maxBytes);
		if (err) {
			onError?.(err);
			return;
		}
		onFile?.(files[0]);
		return;
	}

	// Multiple mode: validate all, report first error encountered
	const valid = [];
	for (const file of files) {
		const err = validateFile(file, maxBytes);
		if (err) {
			onError?.(err);
			continue;
		}
		valid.push(file);
	}
	if (valid.length === 0) return;

	if (valid.length === 1) {
		onFile?.(valid[0]);
	} else {
		onFiles?.(valid);
	}
}
