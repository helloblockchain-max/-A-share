from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO
from pathlib import Path
from typing import Callable

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import CACHE_DIR, SOURCE_CACHE_TTL_SECONDS
from .models import SourceQuality, now_iso
from .utils import ensure_dir, normalize_date, read_json, write_json


@dataclass
class SourceFrame:
    """带质量标签的数据表。"""

    data: pd.DataFrame
    quality: SourceQuality


class PublicDataProvider:
    """公开数据源提供器：负责超时、重试、缓存和质量标记。"""

    def __init__(self, cache_dir: Path = CACHE_DIR, ttl_seconds: int = SOURCE_CACHE_TTL_SECONDS):
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Referer": "https://quote.eastmoney.com/",
            }
        )
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=12, pool_maxsize=12)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _cache_paths(self, key: str) -> tuple[Path, Path]:
        safe = key.replace("/", "_").replace(":", "_").replace("?", "_")
        return self.cache_dir / f"{safe}.json", self.cache_dir / f"{safe}.meta.json"

    def _read_cache(self, key: str) -> tuple[pd.DataFrame, dict] | None:
        data_path, meta_path = self._cache_paths(key)
        if not data_path.exists() or not meta_path.exists():
            return None
        df = pd.read_json(data_path, orient="table")
        meta = read_json(meta_path)
        return df, meta

    def _write_cache(self, key: str, df: pd.DataFrame, meta: dict) -> None:
        data_path, meta_path = self._cache_paths(key)
        ensure_dir(data_path.parent)
        df.to_json(data_path, orient="table", force_ascii=False, date_format="iso")
        write_json(meta_path, meta)

    def _with_cache(
        self,
        key: str,
        fetcher: Callable[[], pd.DataFrame],
        source_name: str,
        url: str,
        as_of_column: str | None,
        ttl_seconds: int | None = None,
    ) -> SourceFrame:
        """读取数据；接口失败时退回缓存并明确标注。"""

        ttl = self.ttl_seconds if ttl_seconds is None else ttl_seconds
        cached = self._read_cache(key)
        if cached:
            cached_df, cached_meta = cached
            cached_at = datetime.fromisoformat(cached_meta["fetched_at"])
            if (datetime.now().astimezone() - cached_at).total_seconds() < ttl:
                quality = SourceQuality(
                    name=source_name,
                    url=url,
                    as_of=cached_meta.get("as_of"),
                    fetched_at=cached_meta["fetched_at"],
                    status="fresh_cache",
                    message="使用有效期内缓存，避免重复请求数据源。",
                    from_cache=True,
                    row_count=len(cached_df),
                )
                return SourceFrame(cached_df, quality)

        try:
            df = fetcher()
            if df.empty:
                raise RuntimeError("数据源返回空表")
            as_of = normalize_date(df[as_of_column].max()) if as_of_column and as_of_column in df else None
            fetched_at = now_iso()
            self._write_cache(key, df, {"as_of": as_of, "fetched_at": fetched_at})
            quality = SourceQuality(
                name=source_name,
                url=url,
                as_of=as_of,
                fetched_at=fetched_at,
                status="ok",
                message="已从数据源实时拉取。",
                from_cache=False,
                row_count=len(df),
            )
            return SourceFrame(df, quality)
        except Exception as exc:  # noqa: BLE001 - 这里需要把任意数据源异常降级为质量标签
            if cached:
                cached_df, cached_meta = cached
                quality = SourceQuality(
                    name=source_name,
                    url=url,
                    as_of=cached_meta.get("as_of"),
                    fetched_at=cached_meta["fetched_at"],
                    status="stale_cache",
                    message=f"实时请求失败，使用缓存：{exc}",
                    from_cache=True,
                    row_count=len(cached_df),
                )
                return SourceFrame(cached_df, quality)
            raise

    def fetch_index_history(self, symbol: str, start_date: str, end_date: str) -> SourceFrame:
        """东方财富指数日线。symbol 示例：sh000300、sz399006。"""

        market_map = {"sz": "0", "sh": "1", "csi": "2", "bj": "0"}
        prefix = symbol[:2]
        if prefix not in market_map:
            raise ValueError(f"不支持的指数代码前缀：{symbol}")
        secid = f"{market_map[prefix]}.{symbol[2:]}"
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

        def fetcher() -> pd.DataFrame:
            params = {
                "secid": secid,
                "fields1": "f1,f2,f3,f4,f5",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                "klt": "101",
                "fqt": "0",
                "beg": start_date,
                "end": end_date,
            }
            resp = self.session.get(url, params=params, timeout=12)
            resp.raise_for_status()
            payload = resp.json()
            data = payload.get("data") or {}
            rows = data.get("klines") or []
            if not rows:
                raise RuntimeError(f"东方财富无指数日线：{symbol}")
            df = pd.DataFrame([row.split(",") for row in rows])
            df.columns = ["date", "open", "close", "high", "low", "volume", "amount", "amplitude"]
            for col in ["open", "close", "high", "low", "volume", "amount", "amplitude"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
            df["symbol"] = symbol
            df["name"] = data.get("name") or symbol
            return df

        return self._with_cache(
            key=f"index_history_{symbol}_{start_date}_{end_date}",
            fetcher=fetcher,
            source_name=f"东方财富指数行情 {symbol}",
            url=url,
            as_of_column="date",
        )

    def fetch_csindex_valuation(self, symbol: str = "000300") -> SourceFrame:
        """中证指数估值文件，近期官方估值。"""

        url = f"https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/{symbol}indicator.xls"

        def fetcher() -> pd.DataFrame:
            resp = self.session.get(url, timeout=18)
            resp.raise_for_status()
            df = pd.read_excel(BytesIO(resp.content))
            df.columns = [
                "日期",
                "指数代码",
                "指数中文全称",
                "指数中文简称",
                "指数英文全称",
                "指数英文简称",
                "市盈率1",
                "市盈率2",
                "股息率1",
                "股息率2",
            ]
            df["日期"] = pd.to_datetime(df["日期"], format="%Y%m%d", errors="coerce").dt.date
            for col in ["市盈率1", "市盈率2", "股息率1", "股息率2"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            return df.sort_values("日期")

        return self._with_cache(
            key=f"csindex_valuation_{symbol}",
            fetcher=fetcher,
            source_name=f"中证指数估值 {symbol}",
            url=url,
            as_of_column="日期",
            ttl_seconds=3600,
        )

    def fetch_legulegu_hs300_pe(self) -> SourceFrame:
        """乐咕乐股沪深300 PE 长序列，用于历史分位。"""

        import akshare as ak

        def fetcher() -> pd.DataFrame:
            df = ak.stock_index_pe_lg(symbol="沪深300")
            df["日期"] = pd.to_datetime(df["日期"], errors="coerce").dt.date
            return df.sort_values("日期")

        return self._with_cache(
            key="legulegu_hs300_pe",
            fetcher=fetcher,
            source_name="乐咕乐股沪深300PE长序列",
            url="https://legulegu.com/stockdata/hs300-ttm-lyr",
            as_of_column="日期",
            ttl_seconds=3600,
        )

    def fetch_legulegu_hs300_pb(self) -> SourceFrame:
        """乐咕乐股沪深300 PB 长序列，用于历史分位。"""

        import akshare as ak

        def fetcher() -> pd.DataFrame:
            df = ak.stock_index_pb_lg(symbol="沪深300")
            df["日期"] = pd.to_datetime(df["日期"], errors="coerce").dt.date
            return df.sort_values("日期")

        return self._with_cache(
            key="legulegu_hs300_pb",
            fetcher=fetcher,
            source_name="乐咕乐股沪深300PB长序列",
            url="https://legulegu.com/stockdata/hs300-pb",
            as_of_column="日期",
            ttl_seconds=3600,
        )

    def fetch_bond_yield(self, start_date: str, end_date: str) -> SourceFrame:
        """中国债券信息网收益率曲线。"""

        url = "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/historyQuery"

        def fetcher() -> pd.DataFrame:
            params = {
                "startDate": f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}",
                "endDate": f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}",
                "gjqx": "0",
                "qxId": "ycqx",
                "locale": "cn_ZH",
            }
            resp = self.session.get(url, params=params, timeout=20)
            resp.raise_for_status()
            text = resp.text.replace("&nbsp", "")
            tables = pd.read_html(StringIO(text), header=0)
            df = tables[1]
            df["日期"] = pd.to_datetime(df["日期"], errors="coerce").dt.date
            for col in ["3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            return df.sort_values(["日期", "曲线名称"]).reset_index(drop=True)

        return self._with_cache(
            key=f"bond_yield_{start_date}_{end_date}",
            fetcher=fetcher,
            source_name="中国债券信息网收益率曲线",
            url=url,
            as_of_column="日期",
            ttl_seconds=3600,
        )

    def fetch_treasury_wealth_index(self, period: str = "0-10Y") -> SourceFrame:
        """中债国债财富指数。"""

        indicator_mapping = {"财富": "CFZS"}
        mapping = {
            "0-10Y": "8a8b2cef7832f8920178350801470014",
            "5Y": "8a8b2ca03a3feea1013a44b98fc533f5",
            "7-10Y": "8a8b2c8f5a492a01015a4ac986480043",
        }
        if period not in mapping:
            raise ValueError(f"暂不支持的中债国债指数期限：{period}")
        url = "https://yield.chinabond.com.cn/cbweb-mn/indices/singleIndexQueryResult"

        def fetcher() -> pd.DataFrame:
            params = {
                "indexid": mapping[period],
                "qxlxt": "00",
                "ltcslx": "",
                "zslxt": indicator_mapping["财富"],
                "zslxt1": indicator_mapping["财富"],
                "lx": "1",
                "locale": "zh_CN",
            }
            resp = self.session.post(url, params=params, timeout=20)
            resp.raise_for_status()
            raw = resp.json()
            key_col_map = {f"{indicator_mapping['财富']}_{p_code}": freq_col for p_code, freq_col in raw["dqcName"].items()}
            data_json = {key: raw[key] for key in key_col_map}
            df = pd.DataFrame.from_dict(data_json, orient="columns")
            df.index = pd.to_datetime(pd.to_numeric(df.index), unit="ms", utc=True).tz_convert("Asia/Shanghai")
            df.index.name = "date"
            df.rename(columns=key_col_map, inplace=True)
            df.reset_index(inplace=True)
            df.columns = ["date", "value"]
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            return df.sort_values("date")

        return self._with_cache(
            key=f"treasury_wealth_{period}",
            fetcher=fetcher,
            source_name=f"中债国债财富指数 {period}",
            url=url,
            as_of_column="date",
            ttl_seconds=3600,
        )

    def fetch_margin(self) -> SourceFrame:
        """沪深两市两融数据。注意：当前使用第三方聚合源。"""

        urls = {
            "sh": "https://cdn.jin10.com/data_center/reports/fs_1.json",
            "sz": "https://cdn.jin10.com/data_center/reports/fs_2.json",
        }

        def one_market(market: str) -> pd.DataFrame:
            resp = self.session.get(urls[market], params={"_": time.time()}, timeout=18)
            resp.raise_for_status()
            payload = resp.json()["values"]
            df = pd.DataFrame(payload).T
            if market == "sh":
                df.reset_index(inplace=True)
                df.columns = ["日期", "融资买入额", "融资余额", "融券卖出量", "融券余量", "融券余额", "融资融券余额"]
            else:
                df.columns = ["融资买入额", "融资余额", "融券卖出量", "融券余量", "融券余额", "融资融券余额"]
                df.sort_index(inplace=True)
                df.reset_index(inplace=True)
                df.rename(columns={"index": "日期"}, inplace=True)
            df["市场"] = market
            df["日期"] = pd.to_datetime(df["日期"], errors="coerce").dt.date
            for col in ["融资买入额", "融资余额", "融券卖出量", "融券余量", "融券余额", "融资融券余额"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            return df

        def fetcher() -> pd.DataFrame:
            df = pd.concat([one_market("sh"), one_market("sz")], ignore_index=True)
            grouped = (
                df.groupby("日期", as_index=False)[["融资买入额", "融资余额", "融券余额", "融资融券余额"]]
                .sum(min_count=1)
                .sort_values("日期")
            )
            return grouped

        return self._with_cache(
            key="margin_jin10_hs",
            fetcher=fetcher,
            source_name="沪深两融（金十聚合）",
            url="https://datacenter.jin10.com/reportType/dc_market_margin_sse",
            as_of_column="日期",
            ttl_seconds=3600,
        )

    def fetch_a_share_snapshot(self) -> SourceFrame:
        """东方财富全 A 实时快照，用于市场宽度与成交。"""

        url = "https://82.push2.eastmoney.com/api/qt/clist/get"

        def fetcher() -> pd.DataFrame:
            fields = (
                "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,"
                "f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152"
            )
            fs = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048"
            rows: list[dict] = []
            page = 1
            page_size = 500
            while True:
                params = {
                    "pn": str(page),
                    "pz": str(page_size),
                    "po": "1",
                    "np": "1",
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                    "fltt": "2",
                    "invt": "2",
                    "fid": "f12",
                    "fs": fs,
                    "fields": fields,
                }
                resp = self.session.get(url, params=params, timeout=15)
                resp.raise_for_status()
                payload = resp.json()
                diff = ((payload.get("data") or {}).get("diff") or [])
                rows.extend(diff)
                if len(diff) < page_size:
                    break
                page += 1
                if page > 20:
                    break
                time.sleep(0.12)
            if not rows:
                raise RuntimeError("东方财富全A快照返回空")
            df = pd.DataFrame(rows)
            rename = {
                "f2": "最新价",
                "f3": "涨跌幅",
                "f5": "成交量",
                "f6": "成交额",
                "f8": "换手率",
                "f12": "代码",
                "f14": "名称",
                "f20": "总市值",
                "f21": "流通市值",
                "f24": "60日涨跌幅",
                "f25": "年初至今涨跌幅",
            }
            df.rename(columns=rename, inplace=True)
            keep = list(rename.values())
            df = df[keep]
            for col in ["最新价", "涨跌幅", "成交量", "成交额", "换手率", "总市值", "流通市值", "60日涨跌幅", "年初至今涨跌幅"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["date"] = date.today().isoformat()
            return df

        return self._with_cache(
            key="a_share_snapshot_em",
            fetcher=fetcher,
            source_name="东方财富全A实时快照",
            url=url,
            as_of_column="date",
            ttl_seconds=300,
        )

    def xtquant_health(self) -> SourceQuality:
        """仅做 QMT/xtquant 可用性探测，不依赖其作为默认数据源。"""

        ports = [int(p) for p in os.getenv("XTQUANT_PORTS", "58610,58670").split(",") if p.strip().isdigit()]
        open_ports: list[int] = []
        for port in ports:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    open_ports.append(port)
            except OSError:
                continue
        status = "ok" if open_ports else "not_available"
        message = f"检测到 QMT 行情端口：{open_ports}" if open_ports else "未检测到 58610/58670，本次使用公开行情源。"
        return SourceQuality(
            name="xtquant/QMT 行情探测",
            url="local://xtquant",
            as_of=None,
            fetched_at=now_iso(),
            status=status,
            message=message,
            from_cache=False,
            row_count=0,
        )

