from __future__ import annotations

import atexit
import contextlib
import io
import os
import sys
from argparse import Namespace
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

from .config import DEFAULT_HISTORY_DAYS, ROOT_DIR
from .models import SourceQuality, now_iso
from .providers import PublicDataProvider, SourceFrame


class XingyaoSdkProvider(PublicDataProvider):
    """本地星耀数智 SDK 优先的数据源。

    说明：
    - 指数日线、全 A 宽度和两融汇总优先走本地 SDK；
    - 中证全指、估值、债券等 SDK 未覆盖或公开口径更权威的数据，继续回退公开源；
    - 凭据只从本机环境变量或本地说明文件读取，不写入仓库。
    """

    DAILY_PERIOD_VALUE = 10008
    DAILY_BEGIN_TIME = 900
    DAILY_END_TIME = 1500

    INDEX_VENDOR_MAP = {
        "sh000300": "000300.SH",
        "sz399006": "399006.SZ",
        "sh000688": "000688.SH",
        "sh000852": "000852.SH",
        "sz399975": "399975.SZ",
        "sh000922": "000922.SH",
        "sh000918": "000918.SH",
    }

    INDEX_NAMES = {
        "sh000985": "中证全指",
        "sh000300": "沪深300",
        "sz399006": "创业板指",
        "sh000688": "科创50",
        "sh000852": "中证1000",
        "sz399975": "证券公司",
        "sh000922": "中证红利",
        "sh000918": "300成长",
    }

    def __init__(
        self,
        sdk_dir: Path | None = None,
        credential_file: Path | None = None,
        stock_batch_size: int | None = None,
    ):
        super().__init__()
        self.sdk_dir = sdk_dir or Path(os.getenv("XINGYAO_SDK_DIR", ROOT_DIR.parent / "本地数据" / "星耀数智"))
        self.credential_file = credential_file or Path(
            os.getenv("XINGYAO_CREDENTIAL_FILE", self.sdk_dir / "说明.txt.txt")
        )
        self.stock_batch_size = stock_batch_size or int(os.getenv("XINGYAO_STOCK_BATCH_SIZE", "400"))
        self._username: str | None = None
        self._logout_session = None
        self._base_data = None
        self._market_data = None
        self._info_data = None
        self._closed = False

    def _ensure_sdk_path(self) -> None:
        if not self.sdk_dir.exists():
            raise FileNotFoundError(f"未找到星耀数智 SDK 目录：{self.sdk_dir}")
        sdk_path = str(self.sdk_dir)
        if sdk_path not in sys.path:
            sys.path.insert(0, sdk_path)

    def _ensure_login(self) -> None:
        if self._username:
            return
        self._ensure_sdk_path()
        from batch_star_downloader import resolve_credentials  # type: ignore
        from star_downloader import DEFAULT_HOSTS, DEFAULT_PORT, login_with_host_fallback, logout_session  # type: ignore

        username, password = resolve_credentials(
            Namespace(username=None, password=None, credential_file=str(self.credential_file))
        )
        host_list = [host.strip() for host in os.getenv("XINGYAO_HOSTS", ",".join(DEFAULT_HOSTS)).split(",") if host.strip()]
        port = int(os.getenv("XINGYAO_PORT", str(DEFAULT_PORT)))
        # SDK 登录会输出包含 token 的诊断信息；本地构建时必须吞掉，避免凭据进入日志。
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            login_with_host_fallback(username, password, host_list, port)
        self._username = username
        self._logout_session = logout_session
        atexit.register(self.close)

    def _clients(self):
        self._ensure_login()
        import AmazingData as ad  # type: ignore

        if self._base_data is None:
            self._base_data = ad.BaseData()
        if self._market_data is None:
            calendar = self._base_data.get_calendar()
            self._market_data = ad.MarketData(calendar)
        if self._info_data is None:
            self._info_data = ad.InfoData()
        return self._base_data, self._market_data, self._info_data

    def close(self) -> None:
        """释放 SDK 登录会话。"""

        if self._closed or not self._username or not self._logout_session:
            return
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self._logout_session(self._username)
        finally:
            self._closed = True

    @staticmethod
    def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
        for start in range(0, len(items), size):
            yield items[start : start + size]

    @staticmethod
    def _as_quality(name: str, url: str, as_of: str | None, row_count: int, message: str) -> SourceQuality:
        return SourceQuality(
            name=name,
            url=url,
            as_of=as_of,
            fetched_at=now_iso(),
            status="ok",
            message=message,
            from_cache=False,
            row_count=row_count,
        )

    def fetch_index_history(self, symbol: str, start_date: str, end_date: str) -> SourceFrame:
        """优先使用 SDK 日线；SDK 无覆盖的指数回退公开源。"""

        vendor_code = self.INDEX_VENDOR_MAP.get(symbol.lower())
        if not vendor_code:
            return super().fetch_index_history(symbol, start_date, end_date)
        try:
            _, market_data, _ = self._clients()
            payload = market_data.query_kline(
                [vendor_code],
                begin_date=int(start_date),
                end_date=int(end_date),
                period=self.DAILY_PERIOD_VALUE,
                begin_time=self.DAILY_BEGIN_TIME,
                end_time=self.DAILY_END_TIME,
            )
            raw = payload.get(vendor_code) if isinstance(payload, dict) else None
            if raw is None or raw.empty:
                raise RuntimeError(f"星耀数智 SDK 未返回指数日线：{vendor_code}")
            df = raw.copy()
            df["date"] = pd.to_datetime(df["kline_time"], errors="coerce").dt.date
            for column in ["open", "close", "high", "low", "volume", "amount"]:
                df[column] = pd.to_numeric(df[column], errors="coerce")
            df["amplitude"] = (df["high"] - df["low"]) / df["close"].replace(0, pd.NA) * 100
            df["symbol"] = symbol
            df["name"] = self.INDEX_NAMES.get(symbol.lower(), symbol)
            df = df[["date", "open", "close", "high", "low", "volume", "amount", "amplitude", "symbol", "name"]]
            as_of = df["date"].max().isoformat() if not df.empty else None
            return SourceFrame(
                data=df.sort_values("date").reset_index(drop=True),
                quality=self._as_quality(
                    name=f"星耀数智SDK指数行情 {symbol}",
                    url="local://xingyao/MarketData.query_kline",
                    as_of=as_of,
                    row_count=len(df),
                    message="已从本地星耀数智 SDK 拉取日线行情。",
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 本地 SDK 失败时保留公开源兜底，避免页面中断。
            frame = super().fetch_index_history(symbol, start_date, end_date)
            frame.quality.message = f"星耀数智 SDK 指数链路失败，已回退公开源：{exc}；{frame.quality.message}"
            return frame

    def fetch_margin(self) -> SourceFrame:
        """使用 SDK 交易所两融汇总，替代第三方聚合源。"""

        try:
            _, _, info_data = self._clients()
            begin = int((date.today() - timedelta(days=DEFAULT_HISTORY_DAYS + 30)).strftime("%Y%m%d"))
            end = int(date.today().strftime("%Y%m%d"))
            raw = info_data.get_margin_summary(is_local=False, begin_date=begin, end_date=end)
            if raw is None or raw.empty:
                raise RuntimeError("星耀数智 SDK 两融汇总为空")
            df = raw.loc[raw["EXCHANGE"].isin(["SSE", "SZSE"])].copy()
            numeric_columns = [
                "SUM_BORROW_MONEY_BALANCE",
                "SUM_PURCH_WITH_BORROW_MONEY",
                "SUM_SEC_LENDING_BALANCE",
                "SUM_SALES_OF_BORROWED_SEC",
                "SUM_MARGIN_TRADE_BALANCE",
            ]
            for column in numeric_columns:
                df[column] = pd.to_numeric(df[column], errors="coerce")
            grouped = (
                df.groupby("TRADE_DATE", as_index=False)[numeric_columns]
                .sum(min_count=1)
                .sort_values("TRADE_DATE")
                .reset_index(drop=True)
            )
            out = pd.DataFrame(
                {
                    "日期": pd.to_datetime(grouped["TRADE_DATE"].astype(str), format="%Y%m%d", errors="coerce").dt.date,
                    "融资买入额": grouped["SUM_PURCH_WITH_BORROW_MONEY"],
                    "融资余额": grouped["SUM_BORROW_MONEY_BALANCE"],
                    "融券卖出量": grouped["SUM_SALES_OF_BORROWED_SEC"],
                    "融券余量": 0.0,
                    "融券余额": grouped["SUM_SEC_LENDING_BALANCE"],
                    "融资融券余额": grouped["SUM_MARGIN_TRADE_BALANCE"],
                }
            ).dropna(subset=["日期"])
            as_of = out["日期"].max().isoformat() if not out.empty else None
            return SourceFrame(
                data=out,
                quality=self._as_quality(
                    name="星耀数智SDK沪深两融汇总",
                    url="local://xingyao/InfoData.get_margin_summary",
                    as_of=as_of,
                    row_count=len(out),
                    message="已从本地星耀数智 SDK 拉取沪深交易所两融汇总。",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            frame = super().fetch_margin()
            frame.quality.message = f"星耀数智 SDK 两融链路失败，已回退公开聚合源：{exc}；{frame.quality.message}"
            return frame

    def fetch_a_share_snapshot(self) -> SourceFrame:
        """用 SDK 日线生成全 A 宽度快照，并用公开快照补充市值字段。"""

        try:
            base_data, market_data, _ = self._clients()
            codes = list(base_data.get_code_list("EXTRA_STOCK_A_SH_SZ"))
            begin = int((date.today() - timedelta(days=140)).strftime("%Y%m%d"))
            end = int(date.today().strftime("%Y%m%d"))
            rows: list[dict] = []
            for chunk in self._chunks(codes, self.stock_batch_size):
                payload = market_data.query_kline(
                    chunk,
                    begin_date=begin,
                    end_date=end,
                    period=self.DAILY_PERIOD_VALUE,
                    begin_time=self.DAILY_BEGIN_TIME,
                    end_time=self.DAILY_END_TIME,
                )
                if not isinstance(payload, dict):
                    continue
                for vendor_code, raw in payload.items():
                    if raw is None or raw.empty:
                        continue
                    kline = raw.sort_values("kline_time").copy()
                    for column in ["open", "close", "high", "low", "volume", "amount"]:
                        kline[column] = pd.to_numeric(kline[column], errors="coerce")
                    latest = kline.iloc[-1]
                    close = float(latest["close"]) if pd.notna(latest["close"]) else None
                    pre_close = float(kline.iloc[-2]["close"]) if len(kline) >= 2 and pd.notna(kline.iloc[-2]["close"]) else None
                    close_60 = float(kline.iloc[-61]["close"]) if len(kline) >= 61 and pd.notna(kline.iloc[-61]["close"]) else None
                    pct = (close / pre_close - 1) * 100 if close and pre_close else None
                    pct_60 = (close / close_60 - 1) * 100 if close and close_60 else None
                    rows.append(
                        {
                            "代码": str(vendor_code).split(".", 1)[0],
                            "名称": str(vendor_code),
                            "最新价": close,
                            "涨跌幅": pct,
                            "成交量": latest["volume"],
                            "成交额": latest["amount"],
                            "换手率": pd.NA,
                            "总市值": pd.NA,
                            "流通市值": pd.NA,
                            "60日涨跌幅": pct_60,
                            "年初至今涨跌幅": pd.NA,
                            "date": pd.to_datetime(latest["kline_time"], errors="coerce").date().isoformat(),
                        }
                    )
            if not rows:
                raise RuntimeError("星耀数智 SDK 全 A 日线快照为空")
            df = pd.DataFrame(rows)
            # 东方财富市值字段可用时只补充名称/市值，不再依赖其涨跌幅和成交额。
            cap_message = "市值字段未能补充，融资余额/流通市值可能为空。"
            try:
                public_snapshot = super().fetch_a_share_snapshot().data
                cap_cols = public_snapshot[["代码", "名称", "总市值", "流通市值"]].drop_duplicates("代码")
                df = df.drop(columns=["名称", "总市值", "流通市值"]).merge(cap_cols, on="代码", how="left")
                cap_message = "名称/市值字段由东方财富全 A 快照补充，行情宽度和成交额由本地 SDK 日线生成。"
            except Exception as cap_exc:  # noqa: BLE001
                cap_message = f"东方财富市值补充失败，仅使用本地 SDK 日线字段：{cap_exc}"
            ordered_columns = [
                "最新价",
                "涨跌幅",
                "成交量",
                "成交额",
                "换手率",
                "代码",
                "名称",
                "总市值",
                "流通市值",
                "60日涨跌幅",
                "年初至今涨跌幅",
                "date",
            ]
            df = df[ordered_columns]
            for column in ["最新价", "涨跌幅", "成交量", "成交额", "换手率", "总市值", "流通市值", "60日涨跌幅", "年初至今涨跌幅"]:
                df[column] = pd.to_numeric(df[column], errors="coerce")
            as_of = str(df["date"].max()) if not df.empty else None
            return SourceFrame(
                data=df,
                quality=self._as_quality(
                    name="星耀数智SDK全A日线宽度快照",
                    url="local://xingyao/MarketData.query_kline",
                    as_of=as_of,
                    row_count=len(df),
                    message=f"已从本地星耀数智 SDK 拉取沪深 A 股日线快照；{cap_message}",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            frame = super().fetch_a_share_snapshot()
            frame.quality.message = f"星耀数智 SDK 全 A 快照失败，已回退东方财富全 A 快照：{exc}；{frame.quality.message}"
            return frame
