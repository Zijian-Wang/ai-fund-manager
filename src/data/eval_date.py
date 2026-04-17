"""Resolve the evaluation date — the most recent completed A-share trading day.

Rules (Beijing time):
- After 15:30 on a trading day -> today (today's session has closed)
- Before 15:30 on a trading day -> previous trading day
- On a non-trading day (weekend/holiday/调休) -> previous trading day

The trading calendar (``data_cache/trade_cal.json``) must already exist and
cover the date in question. This module reads it but never refreshes it.
"""
from __future__ import annotations

from datetime import datetime, time, timezone, timedelta
from pathlib import Path

from src.data.cache import read_json, trade_cal_path


BEIJING = timezone(timedelta(hours=8))
SESSION_CLOSE = time(15, 30)


class EvalDateError(RuntimeError):
    """Raised when the trading calendar is missing or doesn't cover the date."""


def resolve_eval_date(
    *,
    cache_root: Path,
    now: datetime | None = None,
) -> str:
    if now is None:
        now_bj = datetime.now(BEIJING)
    elif now.tzinfo is None:
        now_bj = now.replace(tzinfo=BEIJING)
    else:
        now_bj = now.astimezone(BEIJING)

    cal = read_json(trade_cal_path(cache_root))
    if cal is None:
        raise EvalDateError(
            f"trade_cal.json not found at {trade_cal_path(cache_root)}; "
            "call TuShareClient.trade_cal_refresh() first."
        )

    days = {row["cal_date"]: int(row["is_open"]) for row in cal["days"]}

    today_yyyymmdd = now_bj.strftime("%Y%m%d")
    if today_yyyymmdd not in days:
        raise EvalDateError(
            f"trade_cal.json does not cover {today_yyyymmdd}; "
            f"covers {cal['start_date']}..{cal['end_date']}. Refresh the calendar."
        )

    is_today_trading = days[today_yyyymmdd] == 1
    after_close = now_bj.time() >= SESSION_CLOSE

    if is_today_trading and after_close:
        return now_bj.date().strftime("%Y-%m-%d")

    cursor = now_bj.date() - timedelta(days=1)
    while True:
        key = cursor.strftime("%Y%m%d")
        if key not in days:
            raise EvalDateError(
                f"trade_cal.json does not cover {key} while walking back "
                f"from {today_yyyymmdd}. Refresh the calendar with a wider range."
            )
        if days[key] == 1:
            return cursor.strftime("%Y-%m-%d")
        cursor -= timedelta(days=1)
