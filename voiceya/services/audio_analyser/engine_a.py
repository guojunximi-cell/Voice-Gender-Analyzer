from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from io import BytesIO

from fastapi import HTTPException

from voiceya.services.audio_analyser import seg as _seg


logger = logging.getLogger(__file__)


def _run_seg_on_bytesio(sample: BytesIO):
    """在临时 wav 文件上跑 inaSpeechSegmenter。

    为什么必须落盘：
    - `Segmenter.__call__` 内部走 `media2sig16kmono(medianame, ...)`。
    - `ffmpeg=None` 分支里第一步就是 `medianame.startswith("http://")`，BytesIO 没有
      `startswith`，直接 AttributeError；之后的 `sf.read` 虽然能吃 file-like，但走不到。
    - `ffmpeg="ffmpeg"` 分支则会把 `medianame` 塞进 subprocess argv，更不认 BytesIO。
    故唯一干净的做法是：把已规范化好的 16 kHz mono wav 写到磁盘，把路径交给 SEG。
    """
    # 从头读，调用方可能在之前的步骤里移动了游标
    sample.seek(0)

    # delete=False：Windows/部分 Linux 下打开着的临时文件不能被第三方库再次打开；
    # 我们在 finally 里手动清理。
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        tmp.write(sample.getvalue())
        tmp.flush()
        tmp.close()
        return _seg.SEG(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            # 临时文件清理失败不应影响分析结果，记一条 warning 就好
            logger.warning("清理临时文件失败: %s", tmp.name)

        # Engine B 还要复用同一个 BytesIO 做 librosa.load，这里复位游标，
        # 避免 SEG 消费后的位置污染下一步。
        sample.seek(0)


async def do_segmentation(sample: BytesIO):
    try:
        return await asyncio.to_thread(_run_seg_on_bytesio, sample)

    except Exception as e:
        logger.exception("Engine A 分析失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
