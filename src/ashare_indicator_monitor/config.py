from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IndexSymbol:
    """指数配置，symbol 使用东方财富 secid 前缀格式。"""

    key: str
    name: str
    symbol: str
    role: str
    required: bool = True


ROOT_DIR = Path(__file__).resolve().parents[2]
CACHE_DIR = Path(os.getenv("ASHARE_MONITOR_CACHE_DIR", ROOT_DIR / ".cache"))

# 看板核心指数。中证2000在不同数据源映射不稳定，默认不作为必需项。
INDICES: dict[str, IndexSymbol] = {
    "csi_all": IndexSymbol("csi_all", "中证全指", "sh000985", "全市场风险偏好"),
    "hs300": IndexSymbol("hs300", "沪深300", "sh000300", "机构核心资产"),
    "chinext": IndexSymbol("chinext", "创业板指", "sz399006", "成长风格/弹性"),
    "star50": IndexSymbol("star50", "科创50", "sh000688", "科技弹性"),
    "csi1000": IndexSymbol("csi1000", "中证1000", "sh000852", "小盘风险偏好"),
    "securities": IndexSymbol("securities", "证券公司", "sz399975", "风险偏好杠杆"),
    "dividend": IndexSymbol("dividend", "中证红利", "sh000922", "防御风格"),
    "growth300": IndexSymbol("growth300", "300成长", "sh000918", "成长风格"),
}

WEIGHTS = {
    "valuation_erp": 0.25,
    "bond_pressure": 0.20,
    "stock_bond_rs": 0.20,
    "breadth": 0.15,
    "leverage_turnover": 0.10,
    "trend": 0.10,
}

SCORE_BUCKETS = [
    (40, "健康上涨", "顶部概率低，重点跟踪趋势延续与估值变化。"),
    (60, "估值偏热", "不宜追高加杠杆，开始检查结构分化。"),
    (75, "顶部预警", "降低高弹性仓位，关注流动性和趋势破位。"),
    (85, "高危顶部区", "分批降 Beta，准备对冲或防守切换。"),
    (101, "顶部确认概率高", "以保本金和锁利润为主，避免等待反弹回本。"),
]

DEFAULT_HISTORY_DAYS = int(os.getenv("ASHARE_MONITOR_HISTORY_DAYS", "900"))
API_CACHE_TTL_SECONDS = int(os.getenv("ASHARE_MONITOR_CACHE_TTL_SECONDS", "600"))
SOURCE_CACHE_TTL_SECONDS = int(os.getenv("ASHARE_MONITOR_SOURCE_CACHE_TTL_SECONDS", "1800"))
SCHEDULED_REFRESH_ENABLED = os.getenv("ASHARE_MONITOR_SCHEDULE_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
SCHEDULED_REFRESH_TIMES = os.getenv("ASHARE_MONITOR_SCHEDULE_TIMES", "08:45,09:15")
SCHEDULED_REFRESH_TIMEZONE = os.getenv("ASHARE_MONITOR_SCHEDULE_TIMEZONE", "Asia/Shanghai")
