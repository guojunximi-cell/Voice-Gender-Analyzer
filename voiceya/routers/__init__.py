from fastapi import APIRouter
from fastapi.responses import FileResponse

from voiceya.config import CFG
from voiceya.routers import api

router = APIRouter()

router.include_router(api.router, prefix="/api")

# NOTE: 静态资源 mount 在 main.py 直接挂到 app。
# 原因：FastAPI 0.135 的 APIRouter.include_router() 只搬运 APIRoute/Route/WebSocket 几种，
# Mount 实例会被静默丢弃，导致 /assets/* 全部 404（生产 Docker 才暴露——dev 下 vite 自己服务）。
if (CFG.web_dir / "assets").is_dir():

    @router.get("/", include_in_schema=False)
    def static_root():
        return FileResponse(CFG.web_dir / "index.html")

else:

    @router.get("/")
    def root():
        return {"status": "ok", "name": "VFP Voice Analysis API", "version": "2.0"}
