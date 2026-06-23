from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ashare_indicator_monitor.scheduler import next_scheduled_at, parse_schedule_times


def test_parse_schedule_times_sorts_and_deduplicates() -> None:
    times = parse_schedule_times("09:15,08:45,09:15")

    assert [item.strftime("%H:%M") for item in times] == ["08:45", "09:15"]


def test_parse_schedule_times_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        parse_schedule_times("8点45")


def test_next_scheduled_at_uses_same_day_when_time_not_passed() -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 6, 23, 8, 40, tzinfo=timezone)

    next_run = next_scheduled_at(now, parse_schedule_times("08:45,09:15"), timezone)

    assert next_run.isoformat(timespec="minutes") == "2026-06-23T08:45+08:00"


def test_next_scheduled_at_rolls_to_next_day_after_last_time() -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 6, 23, 9, 20, tzinfo=timezone)

    next_run = next_scheduled_at(now, parse_schedule_times("08:45,09:15"), timezone)

    assert next_run.isoformat(timespec="minutes") == "2026-06-24T08:45+08:00"
