from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .config import SCORE_BUCKETS, WEIGHTS
from .models import ModuleScore, Signal
from .utils import bp_change, clamp, ma, percentile_rank, safe_float, zscore_latest


@dataclass
class IndicatorInput:
    """指标计算所需数据。"""

    index_histories: dict[str, pd.DataFrame]
    csindex_valuation: pd.DataFrame
    hs300_pe: pd.DataFrame
    hs300_pb: pd.DataFrame
    bond_yield: pd.DataFrame
    bond_wealth: pd.DataFrame
    margin: pd.DataFrame
    a_snapshot: pd.DataFrame


def score_bucket(total_score: float) -> tuple[str, str]:
    """根据总分返回状态标签。"""

    for upper, label, detail in SCORE_BUCKETS:
        if total_score < upper:
            return label, detail
    return SCORE_BUCKETS[-1][1], SCORE_BUCKETS[-1][2]


def _signal(
    name: str,
    value: float | str | None,
    unit: str,
    score: float,
    detail: str,
    source: str,
) -> Signal:
    """创建信号并自动给出简短状态。"""

    bounded = clamp(score)
    if bounded >= 80:
        status = "高危"
    elif bounded >= 60:
        status = "预警"
    elif bounded >= 40:
        status = "观察"
    else:
        status = "正常"
    return Signal(name=name, value=value, unit=unit, score=round(bounded, 2), status=status, detail=detail, source=source)


def _weighted_average(items: list[tuple[float, float]]) -> float:
    """计算带权平均，自动跳过 NaN。"""

    valid = [(score, weight) for score, weight in items if score is not None and not np.isnan(score)]
    if not valid:
        return 0.0
    total_weight = sum(weight for _, weight in valid)
    return float(sum(score * weight for score, weight in valid) / total_weight)


def _latest(df: pd.DataFrame, date_col: str) -> pd.Series:
    if df.empty:
        raise ValueError("空数据表无法取最新值")
    ordered = df.sort_values(date_col)
    return ordered.iloc[-1]


def _treasury_curve(bond_yield: pd.DataFrame) -> pd.DataFrame:
    """筛出中债国债收益率曲线。"""

    mask = bond_yield["曲线名称"].astype(str).str.contains("国债收益率曲线", na=False)
    curve = bond_yield.loc[mask].sort_values("日期").copy()
    if curve.empty:
        raise ValueError("缺少中债国债收益率曲线")
    return curve


def _merge_erp(pe_df: pd.DataFrame, curve: pd.DataFrame) -> pd.DataFrame:
    """合并 PE 与 10Y 国债收益率并计算 ERP（百分比）。"""

    pe = pe_df[["日期", "滚动市盈率"]].copy()
    pe["日期"] = pd.to_datetime(pe["日期"], errors="coerce")
    curve2 = curve[["日期", "10年"]].copy()
    curve2["日期"] = pd.to_datetime(curve2["日期"], errors="coerce")
    merged = pd.merge_asof(
        pe.sort_values("日期"),
        curve2.sort_values("日期"),
        on="日期",
        direction="backward",
        tolerance=pd.Timedelta(days=10),
    ).dropna(subset=["滚动市盈率", "10年"])
    merged["erp"] = 100 / merged["滚动市盈率"] - merged["10年"]
    return merged


def valuation_erp_module(data: IndicatorInput) -> tuple[ModuleScore, dict[str, Any]]:
    """估值与 ERP 模块。"""

    curve = _treasury_curve(data.bond_yield)
    latest_curve = _latest(curve, "日期")
    latest_val = _latest(data.csindex_valuation, "日期")
    pe_series = pd.to_numeric(data.hs300_pe["滚动市盈率"], errors="coerce")
    pb_series = pd.to_numeric(data.hs300_pb["市净率"], errors="coerce")

    latest_pe_official = safe_float(latest_val.get("市盈率2")) or safe_float(pe_series.iloc[-1])
    latest_dividend = safe_float(latest_val.get("股息率2"))
    latest_pe_history = safe_float(pe_series.iloc[-1])
    ten_y = safe_float(latest_curve.get("10年")) or float("nan")

    pe_pct = percentile_rank(pe_series, latest_pe_history)
    pb_pct = percentile_rank(pb_series)
    erp_hist = _merge_erp(data.hs300_pe, curve)
    latest_erp = 100 / latest_pe_official - ten_y if latest_pe_official and ten_y == ten_y else float("nan")
    erp_pct = percentile_rank(erp_hist["erp"], latest_erp)
    erp_risk = 100 - erp_pct
    div_ratio = (latest_dividend / ten_y) if latest_dividend and ten_y else float("nan")
    div_score = clamp((1.20 - div_ratio) / 0.70 * 100) if div_ratio == div_ratio else float("nan")

    signals = [
        _signal("沪深300 PE_TTM历史分位", round(pe_pct, 2), "%", pe_pct, "PE 分位越高，估值顶部压力越大。", "乐咕乐股/中证指数"),
        _signal("沪深300 PB历史分位", round(pb_pct, 2), "%", pb_pct, "PB 分位用于补充验证估值扩张。", "乐咕乐股"),
        _signal("沪深300 ERP风险", round(latest_erp, 2), "%", erp_risk, "ERP 越低，股票相对债券越贵；风险分=100-ERP分位。", "中证指数+中国债券信息网"),
        _signal("股息率/10Y国债收益率", round(div_ratio, 2) if div_ratio == div_ratio else None, "倍", div_score, "股息率相对无风险利率越低，估值容错越低。", "中证指数+中国债券信息网"),
    ]
    raw = _weighted_average([(pe_pct, 0.30), (pb_pct, 0.20), (erp_risk, 0.35), (div_score, 0.15)])
    module = ModuleScore(
        key="valuation_erp",
        name="估值与ERP",
        weight=WEIGHTS["valuation_erp"],
        raw_score=round(raw, 2),
        contribution=round(raw * WEIGHTS["valuation_erp"], 2),
        signals=signals,
    )
    extra = {
        "latest_pe": latest_pe_official,
        "latest_pb": safe_float(pb_series.iloc[-1]),
        "latest_erp": latest_erp,
        "ten_year_yield": ten_y,
        "erp_series": erp_hist.tail(360)[["日期", "erp"]].assign(日期=lambda x: x["日期"].dt.date.astype(str)).to_dict("records"),
    }
    return module, extra


def bond_pressure_module(data: IndicatorInput) -> tuple[ModuleScore, dict[str, Any]]:
    """债券压制模块。"""

    curve = _treasury_curve(data.bond_yield)
    ten_bp60 = bp_change(curve["10年"], 60)
    one_bp60 = bp_change(curve["1年"], 60)
    spread = pd.to_numeric(curve["10年"], errors="coerce") - pd.to_numeric(curve["1年"], errors="coerce")
    spread_bp60 = bp_change(spread, 60)
    wealth = data.bond_wealth.sort_values("date")
    wealth_series = pd.to_numeric(wealth["value"], errors="coerce")
    latest_wealth = safe_float(wealth_series.iloc[-1])
    wealth_ma120 = ma(wealth_series, 120)
    wealth_ret60 = (wealth_series.iloc[-1] / wealth_series.iloc[-61] - 1) * 100 if len(wealth_series.dropna()) > 60 else float("nan")

    ten_score = clamp((ten_bp60 or 0) / 35 * 100) if ten_bp60 == ten_bp60 else float("nan")
    one_faster = (one_bp60 - ten_bp60) if one_bp60 == one_bp60 and ten_bp60 == ten_bp60 else float("nan")
    short_score = clamp(one_faster / 20 * 100) if one_faster == one_faster else float("nan")
    spread_score = clamp((-spread_bp60) / 30 * 100) if spread_bp60 == spread_bp60 else float("nan")
    wealth_score = 0.0
    if latest_wealth and latest_wealth < wealth_ma120:
        wealth_score += 65
    if wealth_ret60 == wealth_ret60 and wealth_ret60 < 0:
        wealth_score += 35
    wealth_score = clamp(wealth_score)

    signals = [
        _signal("10Y国债收益率60日变化", round(ten_bp60, 1) if ten_bp60 == ten_bp60 else None, "bp", ten_score, "60日上行25-35bp开始压制高估值。", "中国债券信息网"),
        _signal("1Y相对10Y上行", round(one_faster, 1) if one_faster == one_faster else None, "bp", short_score, "短端上行更快代表流动性收紧压力。", "中国债券信息网"),
        _signal("10Y-1Y期限利差收窄", round(spread_bp60, 1) if spread_bp60 == spread_bp60 else None, "bp", spread_score, "期限利差快速收窄是牛市后段风险信号。", "中国债券信息网"),
        _signal("中债国债财富指数趋势", round(wealth_ret60, 2) if wealth_ret60 == wealth_ret60 else None, "%", wealth_score, "财富指数跌破120日均线或60日走弱代表债券端不再配合。", "中国债券信息网"),
    ]
    raw = _weighted_average([(ten_score, 0.35), (short_score, 0.25), (spread_score, 0.20), (wealth_score, 0.20)])
    module = ModuleScore("bond_pressure", "债券压制", WEIGHTS["bond_pressure"], round(raw, 2), round(raw * WEIGHTS["bond_pressure"], 2), signals)
    return module, {"bond_wealth": wealth.tail(360).assign(date=lambda x: x["date"].astype(str)).to_dict("records")}


def _aligned_ratio(stock_df: pd.DataFrame, bond_df: pd.DataFrame) -> pd.DataFrame:
    stock = stock_df[["date", "close"]].copy()
    bond = bond_df[["date", "value"]].copy()
    stock["date"] = pd.to_datetime(stock["date"], errors="coerce")
    bond["date"] = pd.to_datetime(bond["date"], errors="coerce")
    merged = pd.merge_asof(stock.sort_values("date"), bond.sort_values("date"), on="date", direction="backward", tolerance=pd.Timedelta(days=10))
    merged = merged.dropna(subset=["close", "value"])
    merged["ratio"] = merged["close"] / merged["value"]
    return merged


def stock_bond_rs_module(data: IndicatorInput) -> tuple[ModuleScore, dict[str, Any]]:
    """股债相对强弱模块。"""

    ratio_df = _aligned_ratio(data.index_histories["hs300"], data.bond_wealth)
    ratio = ratio_df["ratio"]
    z = zscore_latest(ratio, 250)
    z_score = clamp(z / 2 * 100) if z == z else float("nan")
    latest = safe_float(ratio.iloc[-1])
    ma20 = ma(ratio, 20)
    ma60 = ma(ratio, 60)
    break_score = 0.0
    if latest and latest < ma20:
        break_score += 45
    if latest and latest < ma60:
        break_score += 55
    break_score = clamp(break_score)
    ret120 = (ratio.iloc[-1] / ratio.iloc[-121] - 1) * 100 if len(ratio.dropna()) > 120 else float("nan")
    heat_score = clamp((ret120 or 0) / 20 * 100) if ret120 == ret120 else float("nan")

    signals = [
        _signal("股债相对强弱Z-score", round(z, 2) if z == z else None, "Z", z_score, "Z-score>2 代表股票相对中债国债财富指数明显过热。", "东方财富+中国债券信息网"),
        _signal("相对强弱均线跌破", round(latest, 4) if latest else None, "比值", break_score, "过热后跌破20/60日均线会显著提高顶部概率。", "东方财富+中国债券信息网"),
        _signal("股债相对强弱120日涨幅", round(ret120, 2) if ret120 == ret120 else None, "%", heat_score, "相对债券快速上涨后更容易进入脆弱状态。", "东方财富+中国债券信息网"),
    ]
    raw = _weighted_average([(z_score, 0.45), (break_score, 0.35), (heat_score, 0.20)])
    module = ModuleScore("stock_bond_rs", "股债相对强弱", WEIGHTS["stock_bond_rs"], round(raw, 2), round(raw * WEIGHTS["stock_bond_rs"], 2), signals)
    chart = ratio_df.tail(360).copy()
    chart["ma20"] = chart["ratio"].rolling(20, min_periods=1).mean()
    chart["ma60"] = chart["ratio"].rolling(60, min_periods=1).mean()
    chart["date"] = chart["date"].dt.date.astype(str)
    return module, {"relative_strength": chart[["date", "ratio", "ma20", "ma60"]].to_dict("records")}


def breadth_module(data: IndicatorInput) -> tuple[ModuleScore, dict[str, Any]]:
    """市场宽度模块。"""

    snap = data.a_snapshot.copy()
    valid_ret = pd.to_numeric(snap["涨跌幅"], errors="coerce").dropna()
    advance_ratio = float((valid_ret > 0).mean()) if not valid_ret.empty else float("nan")
    decline_ratio = float((valid_ret < 0).mean()) if not valid_ret.empty else float("nan")
    pos60 = pd.to_numeric(snap["60日涨跌幅"], errors="coerce").dropna()
    pos60_ratio = float((pos60 > 0).mean()) if not pos60.empty else float("nan")

    hs300 = data.index_histories["hs300"].sort_values("date")
    close = pd.to_numeric(hs300["close"], errors="coerce")
    near_high = bool(close.iloc[-1] >= close.tail(252).max() * 0.97) if len(close.dropna()) >= 60 else False
    divergence_score = clamp((0.55 - advance_ratio) / 0.25 * 100) if advance_ratio == advance_ratio and near_high else 0.0
    pos60_score = clamp((0.55 - pos60_ratio) / 0.35 * 100) if pos60_ratio == pos60_ratio and near_high else clamp((0.45 - pos60_ratio) / 0.35 * 50) if pos60_ratio == pos60_ratio else float("nan")

    def return_n(key: str, n: int = 60) -> float:
        frame = data.index_histories[key].sort_values("date")
        series = pd.to_numeric(frame["close"], errors="coerce").dropna()
        if len(series) <= n:
            return float("nan")
        return float((series.iloc[-1] / series.iloc[-n - 1] - 1) * 100)

    hs_ret = return_n("hs300")
    style_returns = [return_n(key) for key in ["chinext", "star50", "csi1000"] if key in data.index_histories]
    under = np.nanmean([ret - hs_ret for ret in style_returns]) if style_returns and hs_ret == hs_ret else float("nan")
    style_score = clamp((-under) / 8 * 100) if under == under and near_high else clamp((-under) / 12 * 70) if under == under else float("nan")

    signals = [
        _signal("全A上涨家数占比", round(advance_ratio * 100, 2) if advance_ratio == advance_ratio else None, "%", divergence_score, "指数接近阶段高位但上涨家数不足，属于宽度背离。", "东方财富全A快照"),
        _signal("60日涨幅为正占比", round(pos60_ratio * 100, 2) if pos60_ratio == pos60_ratio else None, "%", pos60_score, "中期赚钱效应收缩会削弱顶部后段承接。", "东方财富全A快照"),
        _signal("成长/小盘相对沪深300", round(under, 2) if under == under else None, "百分点", style_score, "创业板、科创、小盘若弱于沪深300，说明风险偏好收缩。", "东方财富指数行情"),
    ]
    raw = _weighted_average([(divergence_score, 0.40), (pos60_score, 0.35), (style_score, 0.25)])
    module = ModuleScore("breadth", "市场宽度", WEIGHTS["breadth"], round(raw, 2), round(raw * WEIGHTS["breadth"], 2), signals)
    extra = {
        "advance_ratio": advance_ratio,
        "decline_ratio": decline_ratio,
        "positive_60d_ratio": pos60_ratio,
        "a_share_count": int(len(snap)),
        "a_share_amount": float(pd.to_numeric(snap["成交额"], errors="coerce").sum(skipna=True)),
        "a_share_float_market_cap": float(pd.to_numeric(snap["流通市值"], errors="coerce").sum(skipna=True)),
    }
    return module, extra


def select_market_amount(snapshot_amount: float | None, snapshot_count: int | None, index_amount: float | None) -> tuple[float | None, str]:
    """选择融资买入占比的成交额分母，并避免不完整快照造成异常放大。

    东方财富全 A 快照若分页失败可能只有 100 行，此时成交额会被低估两个数量级。
    规则：
    - 快照股票数足够多且成交额不显著低于中证全指成交额时，使用全 A 快照成交额；
    - 否则退回中证全指成交额。
    """

    snapshot_amount = safe_float(snapshot_amount)
    index_amount = safe_float(index_amount)
    snapshot_count = int(snapshot_count or 0)
    if snapshot_amount and snapshot_count >= 3500:
        if not index_amount or snapshot_amount >= index_amount * 0.75:
            return snapshot_amount, "东方财富全A快照成交额"
    if index_amount:
        return index_amount, "中证全指成交额（快照不完整时兜底）"
    return snapshot_amount, "东方财富全A快照成交额（未能校验完整性）"


def select_float_market_cap(snapshot_float_cap: float | None, snapshot_count: int | None) -> tuple[float | None, str]:
    """选择全 A 流通市值，并避免不完整快照造成融资余额占比失真。"""

    snapshot_float_cap = safe_float(snapshot_float_cap)
    snapshot_count = int(snapshot_count or 0)
    if snapshot_float_cap and snapshot_count >= 3500:
        return snapshot_float_cap, "东方财富全A快照流通市值"
    return None, "全A快照不完整，未计算流通市值分母"


def leverage_turnover_module(data: IndicatorInput, breadth_extra: dict[str, Any]) -> tuple[ModuleScore, dict[str, Any]]:
    """杠杆与成交模块。"""

    margin = data.margin.sort_values("日期").copy()
    financing_balance = pd.to_numeric(margin["融资余额"], errors="coerce")
    margin_balance = pd.to_numeric(margin["融资融券余额"], errors="coerce")
    buy_amount = pd.to_numeric(margin["融资买入额"], errors="coerce")
    latest_financing_balance = safe_float(financing_balance.iloc[-1])
    balance_pct = percentile_rank(financing_balance)
    change20 = (financing_balance.iloc[-1] / financing_balance.iloc[-21] - 1) * 100 if len(financing_balance.dropna()) > 20 else float("nan")
    change_score = 80.0 if balance_pct > 80 and change20 == change20 and change20 < 0 else clamp((change20 or 0) / 12 * 100) if change20 == change20 else float("nan")

    csi_all = data.index_histories["csi_all"].sort_values("date")
    amount = pd.to_numeric(csi_all["amount"], errors="coerce")
    amount_pct = percentile_rank(amount)
    float_market_cap, float_market_cap_source = select_float_market_cap(
        breadth_extra.get("a_share_float_market_cap"),
        breadth_extra.get("a_share_count"),
    )
    financing_float_mcap_ratio = safe_float(latest_financing_balance / float_market_cap * 100) if latest_financing_balance and float_market_cap else None
    financing_float_mcap_score = clamp(((financing_float_mcap_ratio or 0) - 2.0) / 4.0 * 100) if financing_float_mcap_ratio is not None else float("nan")
    latest_amount, amount_source = select_market_amount(
        breadth_extra.get("a_share_amount"),
        breadth_extra.get("a_share_count"),
        safe_float(amount.iloc[-1]),
    )
    buy_ratio = safe_float(buy_amount.iloc[-1] / latest_amount * 100) if latest_amount else None
    buy_ratio_score = clamp(((buy_ratio or 0) - 8) / 12 * 100) if buy_ratio is not None else float("nan")

    signals = [
        _signal("融资余额/流通市值", round(financing_float_mcap_ratio, 2) if financing_float_mcap_ratio is not None else None, "%", financing_float_mcap_score, f"融资余额相对全A流通市值越高，杠杆拥挤度越高；分母使用：{float_market_cap_source}。", "金十聚合+东方财富全A快照"),
        _signal("融资余额历史分位", round(balance_pct, 2), "%", balance_pct, "融资余额处于高分位说明杠杆交易拥挤。", "金十聚合/交易所披露口径"),
        _signal("融资余额20日变化", round(change20, 2) if change20 == change20 else None, "%", change_score, "高位扩张代表过热；高位转负代表增量杠杆失速。", "金十聚合/交易所披露口径"),
        _signal("成交额历史分位", round(amount_pct, 2), "%", amount_pct, "成交额极端放大后萎缩是交易顶部的重要线索。", "东方财富指数行情"),
        _signal("融资买入额/成交额", round(buy_ratio, 2) if buy_ratio is not None else None, "%", buy_ratio_score, f"融资买入占比快速上升代表杠杆资金主导度提高；分母使用：{amount_source}。", "金十聚合+东方财富"),
    ]
    raw = _weighted_average([(financing_float_mcap_score, 0.35), (balance_pct, 0.20), (change_score, 0.20), (amount_pct, 0.15), (buy_ratio_score, 0.10)])
    module = ModuleScore("leverage_turnover", "杠杆与成交", WEIGHTS["leverage_turnover"], round(raw, 2), round(raw * WEIGHTS["leverage_turnover"], 2), signals)
    margin_chart = margin.tail(360).copy()
    margin_chart["日期"] = margin_chart["日期"].astype(str)
    margin_chart["融资融券余额_亿元"] = pd.to_numeric(margin_chart["融资融券余额"], errors="coerce") / 1e8
    margin_chart["融资买入额_亿元"] = pd.to_numeric(margin_chart["融资买入额"], errors="coerce") / 1e8
    return module, {
        "margin_balance": safe_float(margin_balance.iloc[-1]),
        "financing_balance": latest_financing_balance,
        "financing_balance_float_mcap_ratio": financing_float_mcap_ratio,
        "float_market_cap_used": float_market_cap,
        "float_market_cap_source": float_market_cap_source,
        "financing_buy_ratio": buy_ratio,
        "market_amount_used": latest_amount,
        "market_amount_source": amount_source,
        "margin_chart": margin_chart[["日期", "融资融券余额_亿元", "融资买入额_亿元"]].rename(columns={"日期": "date"}).to_dict("records"),
    }


def trend_module(data: IndicatorInput) -> tuple[ModuleScore, dict[str, Any]]:
    """趋势确认模块。"""

    def one_index(key: str) -> tuple[float, str]:
        frame = data.index_histories[key].sort_values("date")
        close = pd.to_numeric(frame["close"], errors="coerce").dropna()
        latest = close.iloc[-1]
        score = 0.0
        parts: list[str] = []
        for window, add in [(20, 30), (60, 30), (120, 40)]:
            avg = ma(close, window)
            if latest < avg:
                score += add
                parts.append(f"跌破{window}日线")
        return clamp(score), "、".join(parts) if parts else "仍在主要均线上方"

    hs_score, hs_detail = one_index("hs300")
    all_score, all_detail = one_index("csi_all")
    signals = [
        _signal("沪深300趋势破位", hs_detail, "", hs_score, "趋势破位是顶部从预警走向确认的条件。", "东方财富指数行情"),
        _signal("中证全指趋势破位", all_detail, "", all_score, "全市场指数破位比单一宽基更能确认风险扩散。", "东方财富指数行情"),
    ]
    raw = _weighted_average([(hs_score, 0.55), (all_score, 0.45)])
    module = ModuleScore("trend", "趋势确认", WEIGHTS["trend"], round(raw, 2), round(raw * WEIGHTS["trend"], 2), signals)

    hs = data.index_histories["hs300"].sort_values("date").tail(360).copy()
    hs["ma20"] = pd.to_numeric(hs["close"], errors="coerce").rolling(20, min_periods=1).mean()
    hs["ma60"] = pd.to_numeric(hs["close"], errors="coerce").rolling(60, min_periods=1).mean()
    hs["date"] = hs["date"].astype(str)
    return module, {"hs300_trend": hs[["date", "close", "ma20", "ma60"]].to_dict("records")}


def compute_dashboard_indicators(data: IndicatorInput) -> tuple[list[ModuleScore], dict[str, Any], list[str]]:
    """计算全部模块、图表数据与提示。"""

    warnings: list[str] = []
    modules: list[ModuleScore] = []
    charts: dict[str, Any] = {}
    headline: dict[str, Any] = {}

    valuation, valuation_extra = valuation_erp_module(data)
    modules.append(valuation)
    charts["erp"] = valuation_extra.pop("erp_series")
    headline.update(valuation_extra)

    bond, bond_extra = bond_pressure_module(data)
    modules.append(bond)
    charts.update(bond_extra)

    rs, rs_extra = stock_bond_rs_module(data)
    modules.append(rs)
    charts.update(rs_extra)

    breadth, breadth_extra = breadth_module(data)
    modules.append(breadth)
    headline.update(breadth_extra)
    if breadth_extra.get("a_share_count", 0) < 3500:
        warnings.append("全A实时快照股票数不足，融资余额/流通市值无法可靠计算；融资买入/成交额已自动退回中证全指成交额作为分母。")

    leverage, leverage_extra = leverage_turnover_module(data, breadth_extra)
    modules.append(leverage)
    charts["margin"] = leverage_extra.pop("margin_chart")
    headline.update(leverage_extra)

    trend, trend_extra = trend_module(data)
    modules.append(trend)
    charts.update(trend_extra)

    charts["module_scores"] = [{"name": module.name, "score": module.raw_score, "contribution": module.contribution} for module in modules]
    total = sum(module.contribution for module in modules)
    headline["total_score"] = round(total, 2)
    red_flags = [
        f"{module.name}：{signal.name} {signal.value}{signal.unit}（{signal.status}）"
        for module in modules
        for signal in module.signals
        if signal.score >= 75
    ]
    if not red_flags:
        red_flags = ["暂无单项高危信号，重点观察估值、股债相对强弱和趋势是否进一步恶化。"]
    headline["red_flags"] = red_flags[:6]

    if valuation.raw_score >= 65 and trend.raw_score < 40:
        warnings.append("估值/ERP已偏热，但趋势尚未确认破位；按顶部预警处理，不宜直接判定顶部完成。")
    if leverage.raw_score >= 75:
        warnings.append("杠杆成交模块处于高位，请重点核对两融源与成交额是否同步更新。")
    return modules, {"headline": headline, "charts": charts}, warnings
