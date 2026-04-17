"""AKShare client wrapper.

Per probe findings: only ``sector_ranking`` (Eastmoney-backed Shenwan L1
industries) is reliable enough to use, and even that fails ~half the
time with connection errors. We retry with exponential backoff.

The other AKShare endpoints originally planned (moneyflow_hsgt,
fina indicator) all hit ``datacenter-web.eastmoney.com`` which is
unreachable from our environment — they were dropped from Phase 1.
"""
from __future__ import annotations

import time
from typing import Any, Callable


class AKShareClient:
    def __init__(
        self,
        *,
        _ak: Any = None,
        _sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 3,
        backoff_initial_sec: float = 1.0,
    ) -> None:
        if _ak is not None:
            self._ak = _ak
        else:
            import akshare as ak  # local import; akshare's import is slow

            self._ak = ak
        self._sleep = _sleep
        self.max_retries = max_retries
        self.backoff_initial_sec = backoff_initial_sec

    def sector_ranking(self) -> list[dict]:
        """Shenwan L1 industries with today's change %.

        Source: Eastmoney via ``stock_board_industry_name_em``.
        Retries with exponential backoff on any exception.
        """
        delay = self.backoff_initial_sec
        last_exc: BaseException | None = None
        for attempt in range(self.max_retries):
            try:
                df = self._ak.stock_board_industry_name_em()
                return [
                    {
                        "name": row["板块名称"],
                        "code": row["板块代码"],
                        "change_pct": float(row["涨跌幅"]),
                    }
                    for _, row in df.iterrows()
                ]
            except Exception as exc:  # noqa: BLE001 — we retry anything
                last_exc = exc
                if attempt < self.max_retries - 1:
                    self._sleep(delay)
                    delay *= 2
        assert last_exc is not None
        raise last_exc
