from __future__ import annotations

from ashare_indicator_monitor.models import SourceQuality
from ashare_indicator_monitor.service import summarize_source_confidence


def _quality(name: str, status: str) -> SourceQuality:
    return SourceQuality(
        name=name,
        url="local://test",
        as_of="2026-06-22",
        fetched_at="2026-06-22T15:00:00+08:00",
        status=status,
        row_count=10,
    )


def test_summarize_source_confidence_ignores_optional_xtquant_probe() -> None:
    result = summarize_source_confidence(
        [
            _quality("东方财富指数行情", "ok"),
            _quality("中证指数估值", "fresh_cache"),
            _quality("xtquant/QMT 行情探测", "not_available"),
        ]
    )

    assert result["data_confidence_score"] == 95.0
    assert result["data_confidence_label"] == "高"


def test_summarize_source_confidence_surfaces_degraded_sources() -> None:
    result = summarize_source_confidence(
        [
            _quality("东方财富全A实时快照", "stale_cache"),
            _quality("中国债券信息网收益率曲线", "ok"),
        ]
    )

    assert result["data_confidence_score"] == 72.5
    assert result["data_confidence_label"] == "中等"
    assert "东方财富全A实时快照" in result["data_confidence_detail"]
