import asyncio
import gc
import logging
import sys

import numpy as np

from inaSpeechSegmenter.segmenter import Segmenter

logger = logging.getLogger(__name__)

SEG: Segmenter = None  # type: ignore

_PATCHED = False


def _patch_segmenter_for_frame_confidence():
    """透出 inaSpeechSegmenter 的逐帧性别置信度。

    上游 DnnSegmenter.__call__ 在 viterbi 解码后丢弃了 NN 的逐帧 softmax，
    这里替换 __call__ 让它把预测类别的逐帧概率 + 段级均值附在返回元组后面；
    同时替换 Segmenter.segment_feats 用 `*rest` 透传这些附加字段通过时间换算。
    VAD → Gender 两段都走同一个 DnnSegmenter.__call__，所以入参解包也兼容 5-tuple。
    """
    global _PATCHED
    if _PATCHED:
        return

    from inaSpeechSegmenter.segmenter import (
        DnnSegmenter,
        _binidx2seglist,
        _energy_activity,
        _get_patches,
        diag_trans_exp,
        viterbi_decoding,
    )

    def dnn_call(self, mspec, lseg, difflen=0):
        if self.nmel < 24:
            mspec = mspec[:, : self.nmel].copy()

        patches, finite = _get_patches(mspec, 68, 2)
        if difflen > 0:
            patches = patches[: -int(difflen / 2), :, :]
            finite = finite[: -int(difflen / 2)]

        assert len(finite) == len(patches), (len(patches), len(finite))

        batch = []
        for lab, start, stop, *_ in lseg:
            if lab == self.inlabel:
                batch.append(patches[start:stop, :])

        if not batch:
            return []

        batch = np.expand_dims(np.concatenate(batch), 3)
        rawpred = self.nn.predict(batch, batch_size=self.batch_size, verbose=2)
        gc.collect()

        ret = []
        for lab, start, stop, *_ in lseg:
            if lab != self.inlabel:
                ret.append((lab, start, stop))
                continue

            length = stop - start
            r = rawpred[:length]
            rawpred = rawpred[length:]
            r[~finite[start:stop], :] = 0.5
            pred = viterbi_decoding(
                np.log(r), diag_trans_exp(self.viterbi_arg, len(self.outlabels))
            )
            for lab2, start2, stop2 in _binidx2seglist(pred):
                idx = int(lab2)
                frame_conf = r[start2:stop2, idx]
                conf_mean = float(frame_conf.mean()) if len(frame_conf) else None
                ret.append((
                    self.outlabels[idx],
                    start2 + start,
                    stop2 + start,
                    conf_mean,
                    frame_conf.astype(float).tolist(),
                ))

        return ret

    def segment_feats(self, mspec, loge, difflen, start_sec):
        lseg = []
        for lab, start, stop in _binidx2seglist(_energy_activity(loge, self.energy_ratio)[::2]):
            lseg.append(("noEnergy" if lab == 0 else "energy", start, stop))

        lseg = self.vad(mspec, lseg, difflen)
        if self.detect_gender:
            lseg = self.gender(mspec, lseg, difflen)

        return [
            (lab, start_sec + s * 0.02, start_sec + e * 0.02, *rest)
            for lab, s, e, *rest in lseg
        ]

    DnnSegmenter.__call__ = dnn_call
    Segmenter.segment_feats = segment_feats
    _PATCHED = True
    logger.info("已对 inaSpeechSegmenter 打上逐帧置信度补丁")


async def load_seg():
    if SEG:
        return

    logger.info("正在载入 AI 模型…")

    try:
        _patch_segmenter_for_frame_confidence()
        seg = await asyncio.to_thread(Segmenter, detect_gender=True, ffmpeg=None)

    except Exception as e:
        logger.fatal("Engine A 加载失败: %s", e)
        sys.exit(-1)

    # ── logit 模型诊断 ──
    logger.info("Engine A (inaSpeechSegmenter) 加载完毕")
    if hasattr(seg, "gender"):
        _g = seg.gender
        logger.info(
            "[Gender诊断] 最后3层: %s",
            [(type(layer).__name__, getattr(layer, "name", "?")) for layer in _g.nn.layers[-3:]],
        )
        logger.info(
            "[Gender诊断] logit_model=%s  pen_model=%s  dense_W=%s",
            getattr(_g, "_logit_model", "MISSING"),
            getattr(_g, "_pen_model", "MISSING"),
            _dense_W.shape if (_dense_W := getattr(_g, "_dense_W", None)) else None,
        )

    global SEG

    SEG = seg
