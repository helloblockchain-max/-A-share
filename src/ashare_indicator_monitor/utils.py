from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """把分数限制在 0-100 区间。"""

    if value is None or math.isnan(float(value)):
        return 0.0
    return float(max(low, min(high, value)))


def percentile_rank(series: pd.Series, value: float | None = None) -> float:
    """计算 value 在历史序列中的百分位，返回 0-100。"""

    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return float("nan")
    target = clean.iloc[-1] if value is None else value
    return float((clean <= target).mean() * 100)


def zscore_latest(series: pd.Series, window: int = 250) -> float:
    """计算最新值相对滚动窗口的 Z-score。"""

    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) < 5:
        return float("nan")
    recent = clean.tail(window)
    std = recent.std(ddof=0)
    if std == 0 or np.isnan(std):
        return 0.0
    return float((recent.iloc[-1] - recent.mean()) / std)


def ma(series: pd.Series, window: int) -> float:
    """计算移动平均，样本不足时使用已有样本。"""

    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return float("nan")
    return float(clean.tail(window).mean())


def bp_change(series: pd.Series, days: int) -> float:
    """收益率变化，单位 bp。输入收益率单位为百分比。"""

    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) <= days:
        return float("nan")
    return float((clean.iloc[-1] - clean.iloc[-days - 1]) * 100)


def safe_float(value: Any) -> float | None:
    """把任意输入转成 float，失败返回 None。"""

    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_date(value: Any) -> str | None:
    """统一把 date/datetime/字符串转成 YYYY-MM-DD。"""

    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.date().isoformat()

