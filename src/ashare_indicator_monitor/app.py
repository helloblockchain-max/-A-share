from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT_DIR
from .models import now_iso
from .service import DashboardService

WEB_DIR = ROOT_DIR / "web"

app = FastAPI(title="A股指标检测实时看板", version="0.1.0")
service = DashboardService()

app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    """返回网页入口。"""

    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/dashboard")
def dashboard(force: bool = Query(default=False, description="是否强制刷新底层数据")) -> dict:
    """看板数据接口。"""

    return service.get_dashboard(force=force)


@app.get("/api/health")
def health() -> dict:
    """健康检查接口。"""

    return {"status": "ok", "time": now_iso()}

