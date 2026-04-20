"""BaoStock zero-config fallback client.

BaoStock requires no token. Iteration pattern (confirmed in probe):

    lg = bs.login()
    rs = bs.query_history_k_data_plus("sh.000300", "date,code,close", ...)
    while (rs.error_code == "0") and rs.next():
        rows.append(rs.get_row_data())

Our wrapper hides that and returns plain dicts. BaoStock uses
``sh.000300`` / ``sz.300750`` ticker formats — callers translate from
TuShare's ``000300.SH`` style.
"""
from __future__ import annotations

from typing import Any


_INDEX_FIELDS = "date,code,open,high,low,close"
_STOCK_FIELDS = "date,code,open,high,low,close,volume,amount"


class BaoStockClient:
    def __init__(self, *, _bs: Any = None) -> None:
        if _bs is not None:
            self._bs = _bs
        else:
            import baostock as bs  # local import; baostock's import is slow

            self._bs = bs
        result = self._bs.login()
        if getattr(result, "error_code", "0") != "0":
            raise RuntimeError(
                f"BaoStock login failed: {getattr(result, 'error_msg', 'unknown')}"
            )

    def _query(
        self, code: str, start_date: str, end_date: str, fields: str
    ) -> list[dict]:
        rs = self._bs.query_history_k_data_plus(
            code,
            fields,
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="3",
        )
        rows: list[dict] = []
        names = fields.split(",")
        while (rs.error_code == "0") and rs.next():
            raw = rs.get_row_data()
            parsed: dict[str, Any] = {}
            for name, value in zip(names, raw):
                if name in {"date", "code"}:
                    parsed[name] = value
                else:
                    parsed[name] = (
                        float(value) if value not in ("", None) else None
                    )
            rows.append(parsed)
        # BaoStock emits ascending date order; TuShare emits descending.
        # Normalize to TuShare's convention so rows[0] is always latest.
        rows.reverse()
        return rows

    def index_daily(
        self, *, code: str, start_date: str, end_date: str
    ) -> list[dict]:
        return self._query(code, start_date, end_date, _INDEX_FIELDS)

    def stock_daily(
        self, *, code: str, start_date: str, end_date: str
    ) -> list[dict]:
        return self._query(code, start_date, end_date, _STOCK_FIELDS)
