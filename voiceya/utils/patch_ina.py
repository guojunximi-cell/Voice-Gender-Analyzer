from pathlib import Path


def patch_ina_submodule(submodule_root: Path) -> None:
    """给 k3-cat/inaSpeechSegmenter@7568394 的类型注解兜底。

    该提交把多处 Any/Callable/npt 挪进了 TYPE_CHECKING，但类体和函数签名里的
    注解仍是裸名字——没有 `from __future__ import annotations` 会在首次 import
    就 NameError。这里直接在源文件顶部补上 __future__，保持 submodule 仅内容
    层面"脏"（gitlink 不变），并且幂等（第二次调用无副作用）。
    """

    for name in ("segmenter.py", "features_vbx.py", "vbx_segmenter.py", "thread_returning.py"):
        src = submodule_root / name
        if not src.exists():
            continue

        text = src.read_text()
        if text.startswith("from __future__ import annotations"):
            continue

        src.write_text("from __future__ import annotations\n" + text)
