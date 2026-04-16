from fastapi import HTTPException

INVALID_FILE_EXCEPTION = HTTPException(
    status_code=415,
    detail="文件不是有效的音频",
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


def is_valid_audio_file(header: bytes):
    """通过 magic bytes 校验上传内容是否为真实音频文件"""
    if len(header) < 12 or not is_valid_audio_file_magic(header):
        raise INVALID_FILE_EXCEPTION
