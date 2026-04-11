import io
from typing import TYPE_CHECKING

import av
from av import AudioStream

if TYPE_CHECKING:
    from av.container import InputContainer


def get_duraton_sec(s: InputContainer) -> int:
    i_stm = s.streams.best("audio")
    assert isinstance(i_stm, AudioStream)

    return i_stm.duration // i_stm.sample_rate  # type: ignore


def normalize_to_pcm(s: InputContainer) -> io.BytesIO:
    i_stm = s.streams.best("audio")
    assert isinstance(i_stm, AudioStream)
    i_stm.codec_context.thread_type = "AUTO"

    mp3 = io.BytesIO()
    with av.open(mp3, "w") as t:
        o_stm = t.add_stream("pcm_s16le", rate=22050)
        assert isinstance(o_stm, AudioStream)
        o_stm.codec_context.thread_type = "AUTO"
        o_stm.codec_context.layout = "mono"
        o_stm.codec_context.bit_rate = 16_000

        for frame in s.decode(i_stm):
            for packet in o_stm.codec_context.encode_lazy(frame):
                t.mux_one(packet)

        t.mux(o_stm.encode())

    return mp3
