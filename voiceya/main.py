# NOTE: Engine B (声学分析 / inaSpeechSegmenter acoustic gender_score) 已于 2026-04-07 永久下线。
#       UI 层已移除相关展示，后端分析逻辑暂时保留但结果不再对外呈现。


import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from voiceya import routers
from voiceya.config import CFG
from voiceya.services.audio_analyser.seg import load_seg
from voiceya.services.redis import init_redis
from voiceya.taskiq import broker

logging.basicConfig(
    level=CFG.log_level,
    format="[%(levelname)s] %(name)s - %(message)s",
)

logger = logging.getLogger("voiceya")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_redis()

    # worker 进程：需要 Segmenter 跑分析（taskiq WORKER_STARTUP 会走这里）
    # api 进程：只做请求分发 + SSE，不加载 TF 模型（省 ~500 MB），
    #          也不调 broker.startup —— 不参与 consumer group 管理，kick 由
    #          BlockingConnectionPool 的 lazy connection 承担即可。
    if broker.is_worker_process:
        await load_seg()

    yield


app = FastAPI(title=CFG.app_name, version="2.0", lifespan=lifespan)

if CFG.redirect_to:
    _REDIRECT_BASE = CFG.redirect_to.rstrip("/")

    @app.middleware("http")
    async def _redirect_all(request: Request, _call_next):
        target = _REDIRECT_BASE + request.url.path
        if request.url.query:
            target += "?" + request.url.query
        # 308 保留 method+body，浏览器+API 调用统一迁移；浏览器会缓存。
        return RedirectResponse(url=target, status_code=308)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
)

app.include_router(routers.router)

# /assets 必须挂在 app 上——APIRouter.include_router 会丢 Mount 实例，见 routers/__init__.py 注释
if (CFG.web_dir / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=CFG.web_dir / "assets"), name="assets")
