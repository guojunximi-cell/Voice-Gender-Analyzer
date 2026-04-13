from fastapi import APIRouter
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from voiceya.config import CFG
from voiceya.routers import api

router = APIRouter()

router.include_router(api.router, prefix="/api")

if CFG.web_dir.is_dir:
    router.mount("/assets", StaticFiles(directory=CFG.web_dir / "assets"), name="assets")

    @router.get("/", include_in_schema=False)
    def static_root():
        return FileResponse(CFG.web_dir / "index.html")

else:

    @router.get("/")
    def root():
        return {"status": "ok", "name": "VFP Voice Analysis API", "version": "2.0"}
