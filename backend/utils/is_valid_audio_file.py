import uuid

from fastapi import HTTPException

ALLOWED_EXTENSIONS = {
    "wav",
    "mp3",
    "flac",
    "ogg",
    "opus",
    "m4a",
    "aac",
    "aiff",
    "au",
    "caf",
    "webm",
}

UNSUPPORTED_FILE_EXCEPTION = HTTPException(
    status_code=415,
    detail=f"上传的文件格式不受支持，仅接受: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
)

INVALID_FILE_EXCEPTION = HTTPException(
    status_code=415, detail="文件内容与声称的格式不符，请检查文件是否为有效音频"
)


def is_valid_audio_file_magic(header: bytes) -> bool:
    # WAV:  RIFF????WAVE
    if header[0:4] == b"RIFF" and header[8:12] == b"WAVE":
        return True
    # FLAC
    if header[0:4] == b"fLaC":
        return True
    # OGG (Vorbis / Opus)
    if header[0:4] == b"OggS":
        return True
    # MP3 with ID3 tag
    if header[0:3] == b"ID3":
        return True
    # MP3 MPEG sync word (0xFF E2–FF)
    if header[0] == 0xFF and header[1] in (0xFB, 0xFA, 0xF3, 0xF2, 0xF1, 0xE3, 0xE2):
        return True
    # AIFF / AIFF-C:  FORM????AIFF|AIFC
    if header[0:4] == b"FORM" and header[8:12] in (b"AIFF", b"AIFC"):
        return True
    # M4A / AAC / MP4 audio:  ????ftyp
    if header[4:8] == b"ftyp":
        return True
    # CAF (Core Audio Format)
    if header[0:4] == b"caff":
        return True
    # AU / SND
    if header[0:4] == b".snd":
        return True
    # WebM / Matroska (EBML header)
    if header[0:4] == b"\x1a\x45\xdf\xa3":
        return True

    return False


def is_valid_audio_file(name: str | None, header: bytes) -> str:
    """通过 magic bytes 校验上传内容是否为真实音频文件（防止伪装扩展名攻击）"""
    if not name:
        return str(uuid.uuid4())

    name_segs = name.split(".")
    if name_segs[-1] not in ALLOWED_EXTENSIONS:
        raise UNSUPPORTED_FILE_EXCEPTION

    if len(header) < 12 or not is_valid_audio_file_magic(header):
        raise INVALID_FILE_EXCEPTION

    return ".".join(name_segs[:-1])
