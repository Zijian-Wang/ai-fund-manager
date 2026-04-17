"""Tests for the market_data orchestrator.

Cascades per probe-validated design:
- Index / stock: TuShare -> BaoStock -> cache
- Sector ranking: AKShare -> cache
- Northbound: TuShare -> cache (AKShare dropped — unreachable)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.data.market_data import (
    _ts_to_baostock_code,
    fetch_index_5d,
    fetch_market_data,
    fetch_northbound_5d,
    fetch_sector_ranking,
    fetch_stock_5d,
    get_valid_tickers,
)


# ---- ticker format conversion ----

def test_ts_to_baostock_converts_index_format():
    assert _ts_to_baostock_code("000300.SH") == "sh.000300"


def test_ts_to_baostock_converts_stock_format():
    assert _ts_to_baostock_code("300750.SZ") == "sz.300750"


# ---- fetch_index_5d ----

def test_fetch_index_5d_uses_tushare_when_available(tmp_cache_dir):
    ts = MagicMock()
    ts.index_daily.return_value = pd.DataFrame(
        {"trade_date": ["20260417"], "close": [3845.2], "pct_chg": [0.5]}
    )
    bs = MagicMock()

    result = fetch_index_5d(
        ts_code="000300.SH",
        eval_date="2026-04-17",
        cache_root=tmp_cache_dir,
        tushare=ts,
        baostock=bs,
    )
    assert result["source"] == "tushare"
    assert result["rows"][0]["close"] == 3845.2
    assert not bs.index_daily.called


def test_fetch_index_5d_falls_back_to_baostock(tmp_cache_dir):
    ts = MagicMock()
    ts.index_daily.side_effect = RuntimeError("tushare down")
    bs = MagicMock()
    bs.index_daily.return_value = [
        {"date": "2026-04-17", "code": "sh.000300", "close": 3845.2}
    ]

    result = fetch_index_5d(
        ts_code="000300.SH",
        eval_date="2026-04-17",
        cache_root=tmp_cache_dir,
        tushare=ts,
        baostock=bs,
    )
    assert result["source"] == "baostock"
    assert result["rows"][0]["close"] == 3845.2
    bs.index_daily.assert_called_once()
    # BaoStock format translation
    assert bs.index_daily.call_args.kwargs["code"] == "sh.000300"


def test_fetch_index_5d_falls_back_to_cache_when_both_sources_fail(tmp_cache_dir):
    eval_dir = tmp_cache_dir / "2026-04-17"
    eval_dir.mkdir()
    (eval_dir / "index_000300.SH.json").write_text(
        json.dumps({"source": "tushare", "rows": [{"close": 3800.0}]}),
        encoding="utf-8",
    )
    ts = MagicMock()
    ts.index_daily.side_effect = RuntimeError("down")
    bs = MagicMock()
    bs.index_daily.side_effect = RuntimeError("down")

    result = fetch_index_5d(
        ts_code="000300.SH",
        eval_date="2026-04-17",
        cache_root=tmp_cache_dir,
        tushare=ts,
        baostock=bs,
    )
    assert result["source"] == "cache"
    assert result["rows"][0]["close"] == 3800.0


def test_fetch_index_5d_returns_error_when_no_cache(tmp_cache_dir):
    ts = MagicMock()
    ts.index_daily.side_effect = RuntimeError("ts fail")
    bs = MagicMock()
    bs.index_daily.side_effect = RuntimeError("bs fail")

    result = fetch_index_5d(
        ts_code="000300.SH",
        eval_date="2026-04-17",
        cache_root=tmp_cache_dir,
        tushare=ts,
        baostock=bs,
    )
    assert result["source"] == "error"
    assert "ts fail" in result["error"]
    assert "bs fail" in result["error"]
    assert result["rows"] == []


def test_fetch_index_5d_writes_cache_on_success(tmp_cache_dir):
    ts = MagicMock()
    ts.index_daily.return_value = pd.DataFrame(
        {"trade_date": ["20260417"], "close": [3845.2]}
    )
    fetch_index_5d(
        ts_code="000300.SH",
        eval_date="2026-04-17",
        cache_root=tmp_cache_dir,
        tushare=ts,
        baostock=MagicMock(),
    )
    cached = tmp_cache_dir / "2026-04-17" / "index_000300.SH.json"
    assert cached.exists()


# ---- fetch_stock_5d (same cascade, different function) ----

def test_fetch_stock_5d_uses_tushare(tmp_cache_dir):
    ts = MagicMock()
    ts.daily.return_value = pd.DataFrame(
        {"trade_date": ["20260417"], "close": [192.30]}
    )
    result = fetch_stock_5d(
        ts_code="300750.SZ",
        eval_date="2026-04-17",
        cache_root=tmp_cache_dir,
        tushare=ts,
        baostock=MagicMock(),
    )
    assert result["source"] == "tushare"
    assert result["rows"][0]["close"] == 192.30


def test_fetch_stock_5d_falls_back_to_baostock(tmp_cache_dir):
    ts = MagicMock()
    ts.daily.side_effect = RuntimeError("ts down")
    bs = MagicMock()
    bs.stock_daily.return_value = [{"date": "2026-04-17", "close": 192.30}]

    result = fetch_stock_5d(
        ts_code="300750.SZ",
        eval_date="2026-04-17",
        cache_root=tmp_cache_dir,
        tushare=ts,
        baostock=bs,
    )
    assert result["source"] == "baostock"
    assert bs.stock_daily.call_args.kwargs["code"] == "sz.300750"


# ---- fetch_sector_ranking ----

def test_fetch_sector_ranking_uses_akshare(tmp_cache_dir):
    ak = MagicMock()
    ak.sector_ranking.return_value = [
        {"name": "医药生物", "code": "BK0727", "change_pct": 3.2}
    ]
    result = fetch_sector_ranking(
        eval_date="2026-04-17", cache_root=tmp_cache_dir, akshare=ak
    )
    assert result["source"] == "akshare"
    assert result["rows"][0]["name"] == "医药生物"


def test_fetch_sector_ranking_falls_back_to_cache(tmp_cache_dir):
    eval_dir = tmp_cache_dir / "2026-04-17"
    eval_dir.mkdir()
    (eval_dir / "sector_ranking.json").write_text(
        json.dumps({"source": "akshare", "rows": [{"name": "电子"}]}),
        encoding="utf-8",
    )
    ak = MagicMock()
    ak.sector_ranking.side_effect = RuntimeError("ak down")

    result = fetch_sector_ranking(
        eval_date="2026-04-17", cache_root=tmp_cache_dir, akshare=ak
    )
    assert result["source"] == "cache"
    assert result["rows"][0]["name"] == "电子"


def test_fetch_sector_ranking_returns_error_when_no_cache(tmp_cache_dir):
    ak = MagicMock()
    ak.sector_ranking.side_effect = RuntimeError("ak dead")
    result = fetch_sector_ranking(
        eval_date="2026-04-17", cache_root=tmp_cache_dir, akshare=ak
    )
    assert result["source"] == "error"
    assert "ak dead" in result["error"]


# ---- fetch_northbound_5d ----

def test_fetch_northbound_uses_tushare(tmp_cache_dir):
    ts = MagicMock()
    ts.moneyflow_hsgt.return_value = pd.DataFrame(
        {"trade_date": ["20260417"], "north_money": ["292500.49"]}
    )
    result = fetch_northbound_5d(
        eval_date="2026-04-17", cache_root=tmp_cache_dir, tushare=ts
    )
    assert result["source"] == "tushare"
    # Values come back as strings from TuShare; orchestrator preserves them
    assert result["rows"][0]["north_money"] == "292500.49"


def test_fetch_northbound_falls_back_to_cache(tmp_cache_dir):
    eval_dir = tmp_cache_dir / "2026-04-17"
    eval_dir.mkdir()
    (eval_dir / "northbound.json").write_text(
        json.dumps({"source": "tushare", "rows": [{"north_money": "100000.0"}]}),
        encoding="utf-8",
    )
    ts = MagicMock()
    ts.moneyflow_hsgt.side_effect = RuntimeError("ts down")
    result = fetch_northbound_5d(
        eval_date="2026-04-17", cache_root=tmp_cache_dir, tushare=ts
    )
    assert result["source"] == "cache"


# ---- top-level orchestrator ----

def test_fetch_market_data_returns_unified_dict(tmp_cache_dir):
    ts = MagicMock()
    ts.index_daily.return_value = pd.DataFrame(
        {"trade_date": ["20260417"], "close": [3845.2]}
    )
    ts.daily.return_value = pd.DataFrame(
        {"trade_date": ["20260417"], "close": [192.30]}
    )
    ts.moneyflow_hsgt.return_value = pd.DataFrame(
        {"trade_date": ["20260417"], "north_money": ["292500.49"]}
    )
    ak = MagicMock()
    ak.sector_ranking.return_value = [
        {"name": "医药生物", "code": "BK0727", "change_pct": 3.2}
    ]
    bs = MagicMock()

    result = fetch_market_data(
        eval_date="2026-04-17",
        holdings_tickers=["300750.SZ"],
        cache_root=tmp_cache_dir,
        tushare=ts,
        akshare=ak,
        baostock=bs,
    )
    assert result["eval_date"] == "2026-04-17"
    assert set(result["indices"].keys()) == {
        "000001.SH", "399001.SZ", "399006.SZ", "000300.SH"
    }
    assert result["sector_ranking"]["rows"][0]["name"] == "医药生物"
    assert result["northbound"]["rows"][0]["north_money"] == "292500.49"
    assert result["holdings"]["300750.SZ"]["rows"][0]["close"] == 192.30
    assert result["errors"] == []


# ---- get_valid_tickers ----

def test_get_valid_tickers_fetches_and_caches_when_missing(tmp_cache_dir):
    ts = MagicMock()
    ts.stock_basic.return_value = pd.DataFrame(
        {"symbol": ["000001", "300750", "600519"], "name": ["a", "b", "c"]}
    )
    tickers = get_valid_tickers(cache_root=tmp_cache_dir, tushare=ts)
    assert tickers == {"000001", "300750", "600519"}
    # Wrote cache
    assert (tmp_cache_dir / "stock_basic.json").exists()


def test_get_valid_tickers_uses_cache_when_fresh(tmp_cache_dir):
    import json
    cache_path = tmp_cache_dir / "stock_basic.json"
    cache_path.write_text(
        json.dumps({"refreshed": "2026-04-17", "tickers": ["000001", "300750"]}),
        encoding="utf-8",
    )
    ts = MagicMock()
    tickers = get_valid_tickers(cache_root=tmp_cache_dir, tushare=ts)
    assert tickers == {"000001", "300750"}
    assert not ts.stock_basic.called


def test_get_valid_tickers_refreshes_when_stale(tmp_cache_dir):
    import json
    import os
    cache_path = tmp_cache_dir / "stock_basic.json"
    cache_path.write_text(
        json.dumps({"refreshed": "old", "tickers": ["000001"]}),
        encoding="utf-8",
    )
    # Backdate cache file 10 days
    old_ts = cache_path.stat().st_mtime - (10 * 86400)
    os.utime(cache_path, (old_ts, old_ts))

    ts = MagicMock()
    ts.stock_basic.return_value = pd.DataFrame(
        {"symbol": ["000001", "300750"], "name": ["a", "b"]}
    )
    tickers = get_valid_tickers(cache_root=tmp_cache_dir, tushare=ts)
    assert tickers == {"000001", "300750"}
    ts.stock_basic.assert_called_once()


def test_fetch_market_data_records_errors(tmp_cache_dir):
    ts = MagicMock()
    ts.index_daily.side_effect = RuntimeError("idx down")
    ts.daily.side_effect = RuntimeError("stk down")
    ts.moneyflow_hsgt.side_effect = RuntimeError("hsgt down")
    ak = MagicMock()
    ak.sector_ranking.side_effect = RuntimeError("ak down")
    bs = MagicMock()
    bs.index_daily.side_effect = RuntimeError("bs idx down")
    bs.stock_daily.side_effect = RuntimeError("bs stk down")

    result = fetch_market_data(
        eval_date="2026-04-17",
        holdings_tickers=["300750.SZ"],
        cache_root=tmp_cache_dir,
        tushare=ts,
        akshare=ak,
        baostock=bs,
    )
    # Every fetch fails — all show up in errors list
    assert len(result["errors"]) == 4 + 1 + 1 + 1  # 4 indices, sector, northbound, 1 stock
    assert any("sector" in e for e in result["errors"])
    assert any("northbound" in e for e in result["errors"])
