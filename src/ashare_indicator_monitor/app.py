from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT_DIR, SCHEDULED_REFRESH_ENABLED, SCHEDULED_REFRESH_TIMEZONE, SCHEDULED_REFRESH_TIMES
from .models import now_iso
from .scheduler import ScheduledRefresher
from .service import DashboardService

WEB_DIR = ROOT_DIR / "web"

service = DashboardService()
refresher = ScheduledRefresher(
    refresh=lambda: service.get_dashboard(force=True),
    raw_times=SCHEDULED_REFRESH_TIMES,
    timezone_name=SCHEDULED_REFRESH_TIMEZONE,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：按配置启动每日定时刷新。"""

    if SCHEDULED_REFRESH_ENABLED:
        refresher.start()
    try:
        yield
    finally:
        await refresher.stop()


app = FastAPI(title="A股指标检测实时看板", version="0.1.0", lifespan=lifespan)

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

    return {"status": "ok", "time": now_iso(), "scheduled_refresh": refresher.state}
