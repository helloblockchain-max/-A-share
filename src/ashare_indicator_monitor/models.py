from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SourceQuality:
    """数据源质量信息，用于网页展示可靠性。"""

    name: str
    url: str
    as_of: str | None
    fetched_at: str
    status: str
    message: str = ""
    from_cache: bool = False
    row_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Signal:
    """单条指标信号。"""

    name: str
    value: float | str | None
    unit: str
    score: float
    status: str
    detail: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModuleScore:
    """评分模块。"""

    key: str
    name: str
    weight: float
    raw_score: float
    contribution: float
    signals: list[Signal] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["signals"] = [signal.to_dict() for signal in self.signals]
        return data


@dataclass
class DashboardPayload:
    """前端看板载荷。"""

    generated_at: str
    as_of: str | None
    total_score: float
    status: str
    status_detail: str
    modules: list[ModuleScore]
    headline: dict[str, Any]
    charts: dict[str, Any]
    source_quality: list[SourceQuality]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "as_of": self.as_of,
            "total_score": self.total_score,
            "status": self.status,
            "status_detail": self.status_detail,
            "modules": [module.to_dict() for module in self.modules],
            "headline": self.headline,
            "charts": self.charts,
            "source_quality": [quality.to_dict() for quality in self.source_quality],
            "warnings": self.warnings,
        }


def now_iso() -> str:
    """返回本地时间 ISO 字符串。"""

    return datetime.now().astimezone().isoformat(timespec="seconds")

