"""TuShare Pro client wrapper.

Adds a token boundary, a sliding-window rate limiter (200 calls/min, the
TuShare Pro free tier limit), and (for the calendar) disk caching.
Methods return pandas DataFrames, matching upstream.

Tests inject a fake ``pro`` object via the ``_pro`` parameter so they
don't need network or a real token.

Note: TuShare's ``moneyflow_hsgt`` returns numeric columns as STRINGS,
not floats. Callers must convert as needed.
"""
from __future__ import annotations

import collections
import time
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.cache import trade_cal_path, write_json_atomic


_RATE_LIMIT_CALLS = 200
_RATE_LIMIT_WINDOW_SEC = 60.0


class TuShareClient:
    def __init__(
        self,
        token: str,
        cache_root: Path,
        *,
        _pro: Any = None,
    ) -> None:
        if not token and _pro is None:
            raise ValueError(
                "TUSHARE_TOKEN is required (set in .env or pass token=...)"
            )
        self.cache_root = Path(cache_root)
        self._call_log: collections.deque[float] = collections.deque()
        if _pro is not None:
            self._pro = _pro
        else:
            import tushare as ts  # local import keeps tests light

            ts.set_token(token)
            self._pro = ts.pro_api()

    def _throttle(self) -> None:
        now = time.monotonic()
        cutoff = now - _RATE_LIMIT_WINDOW_SEC
        while self._call_log and self._call_log[0] < cutoff:
            self._call_log.popleft()
        if len(self._call_log) >= _RATE_LIMIT_CALLS:
            sleep_for = _RATE_LIMIT_WINDOW_SEC - (now - self._call_log[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
        self._call_log.append(time.monotonic())

    # ---- trading calendar ----

    def trade_cal(self, *, start_date: str, end_date: str) -> pd.DataFrame:
        self._throttle()
        return self._pro.trade_cal(
            exchange="SSE", start_date=start_date, end_date=end_date
        )

    def trade_cal_refresh(self, *, start_date: str, end_date: str) -> None:
        df = self.trade_cal(start_date=start_date, end_date=end_date)
        payload = {
            "start_date": start_date,
            "end_date": end_date,
            "days": [
                {"cal_date": row["cal_date"], "is_open": int(row["is_open"])}
                for _, row in df.iterrows()
            ],
        }
        write_json_atomic(trade_cal_path(self.cache_root), payload)

    # ---- market data ----

    def index_daily(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        self._throttle()
        return self._pro.index_daily(
            ts_code=ts_code, start_date=start_date, end_date=end_date
        )

    def daily(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        self._throttle()
        return self._pro.daily(
            ts_code=ts_code, start_date=start_date, end_date=end_date
        )

    def stock_basic(self) -> pd.DataFrame:
        self._throttle()
        return self._pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market",
        )

    def fund_basic(self) -> pd.DataFrame:
        """Listed exchange-traded funds (ETFs, LOFs)."""
        self._throttle()
        return self._pro.fund_basic(market="E", status="L")

    def fund_daily(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Daily OHLCV for ETFs (same column shape as ``daily``)."""
        self._throttle()
        return self._pro.fund_daily(
            ts_code=ts_code, start_date=start_date, end_date=end_date
        )

    def moneyflow_hsgt(self, *, start_date: str, end_date: str) -> pd.DataFrame:
        self._throttle()
        return self._pro.moneyflow_hsgt(start_date=start_date, end_date=end_date)
