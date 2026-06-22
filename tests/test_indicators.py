from __future__ import annotations

import pandas as pd

from ashare_indicator_monitor.indicators import (
    build_confirmation_matrix,
    build_key_signals,
    classify_market_phase,
    score_bucket,
    select_float_market_cap,
    select_market_amount,
)
from ashare_indicator_monitor.models import ModuleScore, Signal
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


def _module(key: str, name: str, score: float) -> ModuleScore:
    return ModuleScore(
        key=key,
        name=name,
        weight=0.1,
        raw_score=score,
        contribution=score * 0.1,
        signals=[Signal(f"{name}信号", score, "分", score, "高危" if score >= 75 else "观察", "测试信号", "测试源")],
    )


def test_confirmation_matrix_uses_heat_pressure_fragility_and_trend() -> None:
    modules = [
        _module("valuation_erp", "估值与ERP", 70),
        _module("bond_pressure", "债券压制", 50),
        _module("stock_bond_rs", "股债相对强弱", 80),
        _module("breadth", "市场宽度", 40),
        _module("leverage_turnover", "杠杆与成交", 65),
        _module("trend", "趋势确认", 30),
    ]

    matrix = build_confirmation_matrix(modules)

    assert [item["key"] for item in matrix] == ["heat", "pressure", "fragility", "confirmation"]
    assert matrix[0]["score"] == 70
    assert matrix[2]["score"] == 62.0


def test_classify_market_phase_detects_defensive_stage() -> None:
    modules = [
        _module("valuation_erp", "估值与ERP", 80),
        _module("bond_pressure", "债券压制", 65),
        _module("stock_bond_rs", "股债相对强弱", 70),
        _module("breadth", "市场宽度", 60),
        _module("leverage_turnover", "杠杆与成交", 70),
        _module("trend", "趋势确认", 70),
    ]

    phase = classify_market_phase(modules, total_score=78)

    assert phase["market_phase"] == "顶部确认/防守阶段"
    assert "降低 Beta" in phase["action_hint"]


def test_build_key_signals_returns_high_risk_first() -> None:
    modules = [_module("valuation_erp", "估值与ERP", 82), _module("trend", "趋势确认", 35)]

    flags = build_key_signals(modules)

    assert flags[0].startswith("估值与ERP")
    assert "风险分 82.0" in flags[0]
