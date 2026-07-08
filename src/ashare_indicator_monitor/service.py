from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from .config import API_CACHE_TTL_SECONDS, DEFAULT_HISTORY_DAYS, INDICES
from .indicators import IndicatorInput, compute_dashboard_indicators, score_bucket
from .models import DashboardPayload, SourceQuality, now_iso
from .providers import PublicDataProvider, SourceFrame


def summarize_source_confidence(qualities: list[SourceQuality]) -> dict[str, Any]:
    """把多数据源质量标签折算成前端可读的数据置信度。"""

    status_score = {
        "ok": 100,
        "fresh_cache": 90,
        "stale": 65,
        "stale_cache": 45,
        "not_available": 35,
        "error": 20,
    }
    core = [q for q in qualities if "xtquant" not in q.name.lower() and "qmt" not in q.name.lower()]
    scored = [status_score.get(q.status, 50) for q in core]
    score = round(sum(scored) / len(scored), 1) if scored else 0.0
    if score >= 90:
        label = "高"
    elif score >= 75:
        label = "较高"
    elif score >= 60:
        label = "中等"
    else:
        label = "偏低"
    degraded = [q.name for q in core if q.status not in {"ok", "fresh_cache"}]
    if degraded:
        detail = "需关注：" + "、".join(degraded[:3])
    else:
        detail = "核心数据源正常或使用有效缓存"
    return {
        "data_confidence_score": score,
        "data_confidence_label": label,
        "data_confidence_detail": detail,
    }


class DashboardService:
    """看板服务：采集数据、计算指标、合并质量标签。"""

    def __init__(self, provider: PublicDataProvider | None = None):
        self.provider = provider or PublicDataProvider()
        self._cached_payload: dict[str, Any] | None = None
        self._cached_at = 0.0

    def get_dashboard(self, force: bool = False) -> dict[str, Any]:
        """获取看板 JSON，默认使用短周期内存缓存。"""

        if not force and self._cached_payload and time.time() - self._cached_at < API_CACHE_TTL_SECONDS:
            return self._cached_payload
        payload = self._build_dashboard().to_dict()
        self._cached_payload = payload
        self._cached_at = time.time()
        return payload

    def _date_range(self) -> tuple[str, str]:
        end = date.today()
        start = end - timedelta(days=DEFAULT_HISTORY_DAYS)
        return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    def _mark_staleness(self, quality: SourceQuality, max_days: int) -> SourceQuality:
        """根据 as_of 统一标注数据新鲜度。"""

        if not quality.as_of:
            return quality
        try:
            as_of = datetime.fromisoformat(quality.as_of).date()
        except ValueError:
            return quality
        lag = (date.today() - as_of).days
        if lag > max_days and quality.status in {"ok", "fresh_cache"}:
            quality.status = "stale"
            quality.message = f"数据日期距离今天 {lag} 天，超过阈值 {max_days} 天，请确认是否遇到休市或数据源延迟。"
        return quality

    def _require(self, name: str, frame: SourceFrame | None) -> pd.DataFrame:
        if frame is None or frame.data.empty:
            raise RuntimeError(f"缺少必要数据：{name}")
        return frame.data

    def _fetch_bond_yield_window(self, start: str, end: str) -> SourceFrame:
        """中债收益率接口单次不宜超过一年，这里按 330 天分段拉取。"""

        start_dt = datetime.strptime(start, "%Y%m%d").date()
        end_dt = datetime.strptime(end, "%Y%m%d").date()
        frames: list[pd.DataFrame] = []
        qualities: list[SourceQuality] = []
        cursor = start_dt
        while cursor <= end_dt:
            chunk_end = min(cursor + timedelta(days=330), end_dt)
            frame = self.provider.fetch_bond_yield(cursor.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d"))
            frames.append(frame.data)
            qualities.append(frame.quality)
            cursor = chunk_end + timedelta(days=1)
        data = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["曲线名称", "日期"]).sort_values(["日期", "曲线名称"])
        status_rank = {"ok": 0, "fresh_cache": 1, "stale": 2, "stale_cache": 3, "error": 4}
        worst = max(qualities, key=lambda q: status_rank.get(q.status, 9))
        combined_quality = SourceQuality(
            name="中国债券信息网收益率曲线（分段）",
            url=worst.url,
            as_of=max(q.as_of for q in qualities if q.as_of),
            fetched_at=now_iso(),
            status=worst.status,
            message="按不超过一年窗口分段拉取后合并；" + worst.message,
            from_cache=any(q.from_cache for q in qualities),
            row_count=len(data),
        )
        return SourceFrame(data=data, quality=combined_quality)

    def _build_dashboard(self) -> DashboardPayload:
        start, end = self._date_range()
        qualities: list[SourceQuality] = []
        warnings: list[str] = []

        index_histories: dict[str, pd.DataFrame] = {}
        for key, symbol in INDICES.items():
            try:
                frame = self.provider.fetch_index_history(symbol.symbol, start, end)
                qualities.append(self._mark_staleness(frame.quality, max_days=7))
                index_histories[key] = frame.data
            except Exception as exc:  # noqa: BLE001 - 单个非关键指数失败时降级
                message = f"{symbol.name} 行情获取失败：{exc}"
                if symbol.required:
                    warnings.append(message)
                else:
                    warnings.append(message)

        csindex = self.provider.fetch_csindex_valuation("000300")
        qualities.append(self._mark_staleness(csindex.quality, max_days=10))
        pe = self.provider.fetch_legulegu_hs300_pe()
        qualities.append(self._mark_staleness(pe.quality, max_days=10))
        pb = self.provider.fetch_legulegu_hs300_pb()
        qualities.append(self._mark_staleness(pb.quality, max_days=10))
        bond_yield = self._fetch_bond_yield_window(start, end)
        qualities.append(self._mark_staleness(bond_yield.quality, max_days=10))
        bond_wealth = self.provider.fetch_treasury_wealth_index("0-10Y")
        qualities.append(self._mark_staleness(bond_wealth.quality, max_days=10))
        margin = self.provider.fetch_margin()
        if "金十" in margin.quality.name or "jin10" in margin.quality.url.lower():
            margin.quality.message += "；该链路为第三方聚合源，生产环境建议接入上交所/深交所或 Tushare Pro 官方链路。"
        qualities.append(self._mark_staleness(margin.quality, max_days=10))
        snapshot = self.provider.fetch_a_share_snapshot()
        qualities.append(self._mark_staleness(snapshot.quality, max_days=3))
        qualities.append(self.provider.xtquant_health())

        # 中证指数官方近期估值与乐咕乐股长序列做粗略交叉校验。
        try:
            latest_official_pe = float(csindex.data.sort_values("日期").iloc[-1]["市盈率2"])
            latest_lgl_pe = float(pe.data.sort_values("日期").iloc[-1]["滚动市盈率"])
            diff = abs(latest_official_pe - latest_lgl_pe) / latest_official_pe
            if diff > 0.15:
                warnings.append(f"沪深300 PE 官方值与长序列值差异 {diff:.1%}，请核对估值口径（总股本/计算用股本/TTM）。")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"估值交叉校验失败：{exc}")

        required_keys = ["csi_all", "hs300", "chinext", "star50", "csi1000"]
        missing = [key for key in required_keys if key not in index_histories]
        if missing:
            raise RuntimeError(f"必要指数行情缺失：{missing}")

        data = IndicatorInput(
            index_histories=index_histories,
            csindex_valuation=self._require("中证指数估值", csindex),
            hs300_pe=self._require("沪深300 PE 长序列", pe),
            hs300_pb=self._require("沪深300 PB 长序列", pb),
            bond_yield=self._require("中债收益率曲线", bond_yield),
            bond_wealth=self._require("中债国债财富指数", bond_wealth),
            margin=self._require("两融", margin),
            a_snapshot=self._require("全A快照", snapshot),
        )
        modules, computed, calc_warnings = compute_dashboard_indicators(data)
        warnings.extend(calc_warnings)

        total_score = round(sum(module.contribution for module in modules), 2)
        status, status_detail = score_bucket(total_score)
        all_as_of = [q.as_of for q in qualities if q.as_of]
        as_of = max(all_as_of) if all_as_of else None
        headline = computed["headline"]
        headline.update(
            {
                "score": total_score,
                "status": status,
                "status_detail": status_detail,
            }
        )
        headline.update(summarize_source_confidence(qualities))

        return DashboardPayload(
            generated_at=now_iso(),
            as_of=as_of,
            total_score=total_score,
            status=status,
            status_detail=status_detail,
            modules=modules,
            headline=headline,
            charts=computed["charts"],
            source_quality=qualities,
            warnings=warnings,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="A股指标检测服务命令行")
    parser.add_argument("--once", action="store_true", help="拉取一次并输出摘要 JSON")
    args = parser.parse_args()
    service = DashboardService()
    if args.once:
        payload = service.get_dashboard(force=True)
        print(json.dumps({"score": payload["total_score"], "status": payload["status"], "as_of": payload["as_of"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
