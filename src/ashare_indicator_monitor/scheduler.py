from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)


def parse_schedule_times(raw: str) -> tuple[time, ...]:
    """解析“HH:MM,HH:MM”格式的每日更新时间。"""

    items: list[time] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            hour_text, minute_text = value.split(":", 1)
            items.append(time(hour=int(hour_text), minute=int(minute_text)))
        except ValueError as exc:
            raise ValueError(f"无效的定时更新时间：{value}，请使用 HH:MM 格式") from exc
    if not items:
        raise ValueError("至少需要配置一个定时更新时间")
    return tuple(sorted(set(items)))


def next_scheduled_at(now: datetime, schedule_times: tuple[time, ...], timezone: ZoneInfo) -> datetime:
    """计算下一次定时刷新时间。"""

    local_now = now.astimezone(timezone)
    for item in schedule_times:
        candidate = datetime.combine(local_now.date(), item, tzinfo=timezone)
        if candidate > local_now:
            return candidate
    return datetime.combine(local_now.date() + timedelta(days=1), schedule_times[0], tzinfo=timezone)


class ScheduledRefresher:
    """后台定时刷新器：每天在指定时间强制刷新看板缓存。"""

    def __init__(
        self,
        refresh: Callable[[], object],
        raw_times: str,
        timezone_name: str = "Asia/Shanghai",
    ) -> None:
        self.refresh = refresh
        self.timezone = ZoneInfo(timezone_name)
        self.schedule_times = parse_schedule_times(raw_times)
        self.task: asyncio.Task | None = None
        self.state: dict[str, object] = {
            "enabled": False,
            "timezone": timezone_name,
            "times": [item.strftime("%H:%M") for item in self.schedule_times],
            "last_run": None,
            "last_status": "not_started",
            "last_error": None,
            "next_run": None,
        }

    async def _run_once(self, run_at: datetime) -> None:
        """在线程池中执行同步数据刷新，避免阻塞事件循环。"""

        self.state.update({"last_run": datetime.now(self.timezone).isoformat(timespec="seconds"), "last_status": "running", "last_error": None})
        try:
            await asyncio.to_thread(self.refresh)
            self.state.update({"last_status": "ok", "last_error": None})
            LOGGER.info("定时刷新完成：%s", run_at.isoformat(timespec="seconds"))
        except Exception as exc:  # noqa: BLE001 - 定时任务不能让服务退出
            self.state.update({"last_status": "error", "last_error": str(exc)})
            LOGGER.exception("定时刷新失败：%s", run_at.isoformat(timespec="seconds"))

    async def _loop(self) -> None:
        self.state["enabled"] = True
        while True:
            now = datetime.now(self.timezone)
            run_at = next_scheduled_at(now, self.schedule_times, self.timezone)
            self.state["next_run"] = run_at.isoformat(timespec="seconds")
            await asyncio.sleep(max((run_at - now).total_seconds(), 1))
            await self._run_once(run_at)

    def start(self) -> None:
        """启动后台定时刷新。"""

        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop(), name="ashare-scheduled-refresher")

    async def stop(self) -> None:
        """停止后台定时刷新。"""

        self.state["enabled"] = False
        if self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
