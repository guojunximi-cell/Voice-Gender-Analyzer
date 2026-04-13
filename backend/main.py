# NOTE: Engine B (声学分析 / inaSpeechSegmenter acoustic gender_score) 已于 2026-04-07 永久下线。
#       UI 层已移除相关展示，后端分析逻辑暂时保留但结果不再对外呈现。


import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import routers
from backend.config import CFG
from backend.services.audio_analyser.seg import load_seg

logging.basicConfig(
    level=CFG.log_level,
    format="[%(levelname)s] %(name)s - %(message)s",
)

logger = logging.getLogger("voiceya")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await load_seg()

    yield


app = FastAPI(title=CFG.app_name, version="2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
)

app.include_router(routers.router)
