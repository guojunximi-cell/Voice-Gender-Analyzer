// 读取音频文件里嵌入的录音时间戳。当前只解析 MP4 / M4A 容器
// （iPhone Voice Memos / 微信语音 / 安卓录音的主流格式）：
//   1. moov/mvhd.creation_time  —— Mac epoch 1904 秒，所有 MP4 都有
//   2. moov/udta/meta/{keys,ilst}  com.apple.quicktime.creationdate
//      —— iOS 录音/录像写入，带时区的 ISO 8601，比 mvhd 更"真"
//
// 设计要点：
//   - 走 File.slice + arrayBuffer，只读文件头 1 MiB（fast-start MP4 的 moov 都在前面）；
//     非 fast-start 的少数情况退化为再读尾部 1 MiB。
//   - 不调用 AudioContext / decodeAudioData —— analyzer.js 里的 _stripMetadata
//     已经走过一次 decode，本模块只摸 box 头不解码，CPU 几乎为零。
//   - 任何异常（非 MP4 / box 损坏 / slice 失败）都吞掉，返回
//     `{ createdAt: null, source: null }`，调用方走 lastModified fallback。

const SCAN_HEAD_BYTES = 1 * 1024 * 1024;
const SCAN_TAIL_BYTES = 1 * 1024 * 1024;
// Mac epoch (1904-01-01 UTC) 到 Unix epoch (1970-01-01 UTC) 的偏移（秒）。
const MAC_EPOCH_OFFSET_SEC = 2_082_844_800;

function _u32(view, offset) {
	return view.getUint32(offset, false);
}
function _u64(view, offset) {
	// JS Number 安全整数到 2^53，音频文件的时间戳/大小不会撞到上限。
	const high = view.getUint32(offset, false);
	const low = view.getUint32(offset + 4, false);
	return high * 4294967296 + low;
}
function _typeStr(view, offset) {
	return String.fromCharCode(
		view.getUint8(offset),
		view.getUint8(offset + 1),
		view.getUint8(offset + 2),
		view.getUint8(offset + 3),
	);
}

// 遍历 [start, end) 区间内的 box，对每个 box 调用 cb(type, payloadStart, payloadEnd)。
// payload 不含 8/16 字节的 box 头。cb 返回 false 提前停止。
function _walkBoxes(view, start, end, cb) {
	let off = start;
	while (off + 8 <= end) {
		let size = _u32(view, off);
		const type = _typeStr(view, off + 4);
		let headerSize = 8;
		if (size === 1) {
			if (off + 16 > end) return;
			size = _u64(view, off + 8);
			headerSize = 16;
		} else if (size === 0) {
			size = end - off;
		}
		if (size < headerSize || off + size > end) return;
		if (cb(type, off + headerSize, off + size) === false) return;
		off += size;
	}
}

function _findBox(view, start, end, target) {
	let payload = null;
	_walkBoxes(view, start, end, (type, ps, pe) => {
		if (type === target) {
			payload = { start: ps, end: pe };
			return false;
		}
	});
	return payload;
}

function _parseMvhd(view, start, end) {
	if (start + 4 > end) return null;
	const version = view.getUint8(start);
	let creationSec;
	if (version === 1) {
		if (start + 4 + 8 > end) return null;
		creationSec = _u64(view, start + 4);
	} else {
		if (start + 4 + 4 > end) return null;
		creationSec = _u32(view, start + 4);
	}
	// Apple 偶有把 mvhd.creation_time 写成 0（早期版本 / 转码工具）。
	// 也提防 < MAC_EPOCH_OFFSET（解析为 1970 之前）的诡异值。
	if (!creationSec || creationSec <= MAC_EPOCH_OFFSET_SEC) return null;
	return (creationSec - MAC_EPOCH_OFFSET_SEC) * 1000;
}

// QuickTime metadata：moov/udta/meta/{hdlr,keys,ilst}
//   keys 列出所有 key 名（"com.apple.quicktime.creationdate" 等），entry 1-indexed。
//   ilst 的每个 item，header 的 4-byte "type" 字段不是 ASCII 而是 keys 的 1-based 索引。
//   item 内有一个 "data" sub-box，前 8 字节是 type/locale，余下是 ISO 8601 字符串。
function _parseQtCreationDate(view, metaStart, metaEnd) {
	// iTunes-style meta 头部多 4 字节 version+flags；QuickTime-style 没有。
	// 启发式：如果 metaStart+4..+8 拼出来是 "hdlr"，没前缀；否则跳过 4 字节再试。
	let cursor = metaStart;
	if (cursor + 8 <= metaEnd) {
		const t = _typeStr(view, cursor + 4);
		if (t !== "hdlr") cursor += 4;
	}
	let keysBox = null;
	let ilstBox = null;
	_walkBoxes(view, cursor, metaEnd, (type, ps, pe) => {
		if (type === "keys") keysBox = { start: ps, end: pe };
		else if (type === "ilst") ilstBox = { start: ps, end: pe };
	});
	if (!keysBox || !ilstBox) return null;

	// keys box: 4-byte version/flags + 4-byte entry_count + entries[]，
	// entry = [4 size][4 namespace][size-8 name bytes (UTF-8)]
	let kc = keysBox.start;
	if (kc + 8 > keysBox.end) return null;
	kc += 4;
	const entryCount = _u32(view, kc);
	kc += 4;
	const keyNames = [];
	for (let i = 0; i < entryCount; i++) {
		if (kc + 8 > keysBox.end) return null;
		const eSize = _u32(view, kc);
		if (eSize < 8 || kc + eSize > keysBox.end) return null;
		const nameLen = eSize - 8;
		let name = "";
		for (let j = 0; j < nameLen; j++) {
			name += String.fromCharCode(view.getUint8(kc + 8 + j));
		}
		keyNames.push(name);
		kc += eSize;
	}
	const idx = keyNames.indexOf("com.apple.quicktime.creationdate");
	if (idx < 0) return null;
	const target1Based = idx + 1;

	// ilst：每个 item 的 4-byte "type" 字段就是 keys 的 1-based 索引。
	// _walkBoxes 把 type 解析成 string，所以这里通过 ps-4 重新读 uint32。
	let result = null;
	_walkBoxes(view, ilstBox.start, ilstBox.end, (_type, ps, pe) => {
		const itemKeyIdx = _u32(view, ps - 4);
		if (itemKeyIdx !== target1Based) return;
		const data = _findBox(view, ps, pe, "data");
		if (!data) return;
		if (data.start + 8 > data.end) return;
		let str = "";
		for (let j = data.start + 8; j < data.end; j++) {
			str += String.fromCharCode(view.getUint8(j));
		}
		const ms = Date.parse(str);
		if (Number.isFinite(ms) && ms > 0) result = ms;
		return false;
	});
	return result;
}

function _scanMoov(view) {
	const moov = _findBox(view, 0, view.byteLength, "moov");
	if (!moov) return { createdAt: null, source: null };

	let mvhdMs = null;
	let qtMs = null;
	_walkBoxes(view, moov.start, moov.end, (type, ps, pe) => {
		if (type === "mvhd" && mvhdMs == null) {
			mvhdMs = _parseMvhd(view, ps, pe);
		} else if (type === "udta") {
			const meta = _findBox(view, ps, pe, "meta");
			if (meta) qtMs = _parseQtCreationDate(view, meta.start, meta.end);
		}
	});
	// QT creationdate 带时区（iOS 写入），优先于 UTC mvhd。
	if (qtMs) return { createdAt: qtMs, source: "qt-creationdate" };
	if (mvhdMs) return { createdAt: mvhdMs, source: "mvhd" };
	return { createdAt: null, source: null };
}

function _isLikelyMp4(view) {
	if (view.byteLength < 8) return false;
	const t = _typeStr(view, 4);
	// MP4/QuickTime 顶级 box 类型白名单。mdat 在前是 non-faststart 文件的常见情形。
	return t === "ftyp" || t === "moov" || t === "free" || t === "skip" || t === "wide" || t === "mdat" || t === "styp";
}

/**
 * 从 MP4 / M4A 文件读取嵌入的录音时间戳。读不到（非 MP4 / 无 metadata / 解析异常）
 * 一律返回 `{ createdAt: null, source: null }`。
 *
 * @param {File|Blob} file
 * @returns {Promise<{createdAt: number|null, source: "mvhd"|"qt-creationdate"|null}>}
 */
export async function readEmbeddedCreatedAt(file) {
	if (!file || !file.size || typeof file.slice !== "function") {
		return { createdAt: null, source: null };
	}
	// Head pass：fast-start MP4 的 moov 都在前面。
	const headLen = Math.min(file.size, SCAN_HEAD_BYTES);
	let buf;
	try {
		buf = await file.slice(0, headLen).arrayBuffer();
	} catch {
		return { createdAt: null, source: null };
	}
	let view = new DataView(buf);
	if (!_isLikelyMp4(view)) return { createdAt: null, source: null };
	let result;
	try {
		result = _scanMoov(view);
	} catch {
		return { createdAt: null, source: null };
	}
	if (result.createdAt) return result;

	// moov 在尾部（非 fast-start mux）。再扫最后 1 MiB。
	if (file.size > SCAN_HEAD_BYTES) {
		const tailLen = Math.min(file.size, SCAN_TAIL_BYTES);
		try {
			buf = await file.slice(file.size - tailLen, file.size).arrayBuffer();
		} catch {
			return result;
		}
		view = new DataView(buf);
		try {
			result = _scanMoov(view);
		} catch {
			return result;
		}
	}
	return result;
}
