from __future__ import annotations

import pandas as pd

from ashare_indicator_monitor.indicators import score_bucket
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

