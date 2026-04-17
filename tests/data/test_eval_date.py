"""Tests for eval_date resolution."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.data.eval_date import EvalDateError, resolve_eval_date


BEIJING = timezone(timedelta(hours=8))


def _write_calendar(cache_root: Path, days: list[tuple[str, int]]) -> None:
    payload = {
        "start_date": days[0][0],
        "end_date": days[-1][0],
        "days": [{"cal_date": d, "is_open": o} for d, o in days],
    }
    (cache_root / "trade_cal.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_after_close_on_trading_day_returns_today(tmp_cache_dir: Path) -> None:
    _write_calendar(tmp_cache_dir, [("20260417", 1)])
    now = datetime(2026, 4, 17, 16, 0, tzinfo=BEIJING)
    assert resolve_eval_date(cache_root=tmp_cache_dir, now=now) == "2026-04-17"


def test_before_close_on_trading_day_returns_previous(tmp_cache_dir: Path) -> None:
    _write_calendar(tmp_cache_dir, [("20260416", 1), ("20260417", 1)])
    now = datetime(2026, 4, 17, 14, 0, tzinfo=BEIJING)
    assert resolve_eval_date(cache_root=tmp_cache_dir, now=now) == "2026-04-16"


def test_on_non_trading_day_walks_back(tmp_cache_dir: Path) -> None:
    # Sunday → walks back over Saturday → Friday
    _write_calendar(
        tmp_cache_dir,
        [("20260417", 1), ("20260418", 0), ("20260419", 0)],
    )
    now = datetime(2026, 4, 19, 12, 0, tzinfo=BEIJING)
    assert resolve_eval_date(cache_root=tmp_cache_dir, now=now) == "2026-04-17"


def test_at_15_30_exactly_returns_today(tmp_cache_dir: Path) -> None:
    _write_calendar(tmp_cache_dir, [("20260417", 1)])
    now = datetime(2026, 4, 17, 15, 30, tzinfo=BEIJING)
    assert resolve_eval_date(cache_root=tmp_cache_dir, now=now) == "2026-04-17"


def test_naive_datetime_treated_as_beijing(tmp_cache_dir: Path) -> None:
    _write_calendar(tmp_cache_dir, [("20260417", 1)])
    now = datetime(2026, 4, 17, 16, 0)  # naive
    assert resolve_eval_date(cache_root=tmp_cache_dir, now=now) == "2026-04-17"


def test_holiday_run_walks_back(tmp_cache_dir: Path) -> None:
    # Simulate 调休 — holiday run on a date marked is_open=0
    _write_calendar(
        tmp_cache_dir,
        [("20260430", 1), ("20260501", 0), ("20260502", 0), ("20260503", 0)],
    )
    now = datetime(2026, 5, 3, 16, 0, tzinfo=BEIJING)
    assert resolve_eval_date(cache_root=tmp_cache_dir, now=now) == "2026-04-30"


def test_missing_calendar_raises(tmp_cache_dir: Path) -> None:
    with pytest.raises(EvalDateError, match="trade_cal.json"):
        resolve_eval_date(
            cache_root=tmp_cache_dir,
            now=datetime(2026, 4, 17, 16, 0, tzinfo=BEIJING),
        )


def test_calendar_does_not_cover_date_raises(tmp_cache_dir: Path) -> None:
    _write_calendar(tmp_cache_dir, [("20260101", 1), ("20260102", 0)])
    with pytest.raises(EvalDateError, match="does not cover"):
        resolve_eval_date(
            cache_root=tmp_cache_dir,
            now=datetime(2026, 4, 17, 16, 0, tzinfo=BEIJING),
        )
