from __future__ import annotations

import pandas as pd

from ashare_indicator_monitor.indicators import score_bucket, select_float_market_cap, select_market_amount
from ashare_indicator_monitor.utils import bp_change, clamp, percentile_rank, zscore_latest


def test_score_bucket() -> None:
    assert score_bucket(35)[0] == "健康上涨"
    assert score_bucket(65)[0] == "顶部预警"
    assert score_bucket(88)[0] == "顶部确认概率高"


def test_percentile_rank() -> None:
    series = pd.Series([1, 2, 3, 4])
    assert percentile_rank(series, 3) == 75


def test_zscore_latest_positive() -> None:
    series = pd.Series(list(range(1, 260)))
    assert zscore_latest(series, 250) > 1


def test_bp_change() -> None:
    series = pd.Series([1.0] * 61 + [1.35])
    assert round(bp_change(series, 60), 1) == 35.0


def test_clamp_handles_nan() -> None:
    assert clamp(float("nan")) == 0
    assert clamp(120) == 100


def test_select_market_amount_falls_back_when_snapshot_incomplete() -> None:
    amount, source = select_market_amount(snapshot_amount=3.9e9, snapshot_count=100, index_amount=1.7e12)
    assert amount == 1.7e12
    assert "兜底" in source


def test_select_market_amount_uses_complete_snapshot() -> None:
    amount, source = select_market_amount(snapshot_amount=2.4e12, snapshot_count=5200, index_amount=1.7e12)
    assert amount == 2.4e12
    assert "全A快照" in source


def test_select_float_market_cap_requires_complete_snapshot() -> None:
    cap, source = select_float_market_cap(snapshot_float_cap=9.0e11, snapshot_count=100)
    assert cap is None
    assert "不完整" in source


def test_select_float_market_cap_uses_complete_snapshot() -> None:
    cap, source = select_float_market_cap(snapshot_float_cap=8.0e13, snapshot_count=5200)
    assert cap == 8.0e13
    assert "流通市值" in source
