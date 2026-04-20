"""Tests for the TuShareClient wrapper.

We inject a mock ``pro`` object so tests don't hit the network.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.data.tushare_client import _RATE_LIMIT_WINDOW_SEC, TuShareClient


@pytest.fixture
def mock_pro() -> MagicMock:
    return MagicMock()


@pytest.fixture
def client(mock_pro: MagicMock, tmp_cache_dir: Path) -> TuShareClient:
    return TuShareClient(token="dummy", cache_root=tmp_cache_dir, _pro=mock_pro)


# ---- init ----

def test_init_requires_token_when_no_pro_injected(tmp_cache_dir: Path) -> None:
    with pytest.raises(ValueError, match="TUSHARE_TOKEN"):
        TuShareClient(token="", cache_root=tmp_cache_dir)


def test_init_accepts_injected_pro_without_real_token(tmp_cache_dir: Path) -> None:
    fake_pro = MagicMock()
    c = TuShareClient(token="", cache_root=tmp_cache_dir, _pro=fake_pro)
    assert c._pro is fake_pro


# ---- throttle ----

def test_throttle_records_calls(client: TuShareClient) -> None:
    client._throttle()
    client._throttle()
    assert len(client._call_log) == 2


def test_throttle_drops_calls_outside_window(client: TuShareClient) -> None:
    # time.monotonic() has an implementation-defined reference; a literal
    # 0.0 isn't guaranteed to be outside the window on a freshly-started
    # process (e.g. CI runners where the monotonic clock is still small).
    # Anchor the "ancient" timestamp relative to the current clock.
    ancient = time.monotonic() - _RATE_LIMIT_WINDOW_SEC - 1.0
    client._call_log.append(ancient)
    client._throttle()
    assert ancient not in client._call_log


# ---- trade_cal ----

def test_trade_cal_calls_pro_with_sse_and_dates(client, mock_pro):
    mock_pro.trade_cal.return_value = pd.DataFrame(
        {
            "exchange": ["SSE", "SSE"],
            "cal_date": ["20260416", "20260417"],
            "is_open": [1, 1],
            "pretrade_date": ["20260415", "20260416"],
        }
    )
    df = client.trade_cal(start_date="20260416", end_date="20260417")
    mock_pro.trade_cal.assert_called_once_with(
        exchange="SSE", start_date="20260416", end_date="20260417"
    )
    assert list(df["cal_date"]) == ["20260416", "20260417"]


def test_trade_cal_refresh_writes_cache_file(client, mock_pro, tmp_cache_dir):
    mock_pro.trade_cal.return_value = pd.DataFrame(
        {
            "exchange": ["SSE"],
            "cal_date": ["20260417"],
            "is_open": [1],
            "pretrade_date": ["20260416"],
        }
    )
    client.trade_cal_refresh(start_date="20260101", end_date="20261231")
    cache_file = tmp_cache_dir / "trade_cal.json"
    assert cache_file.exists()
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert payload["start_date"] == "20260101"
    assert payload["end_date"] == "20261231"
    assert payload["days"] == [{"cal_date": "20260417", "is_open": 1}]


# ---- market data methods ----

def test_index_daily_passes_kwargs(client, mock_pro):
    mock_pro.index_daily.return_value = pd.DataFrame(
        {"ts_code": ["000300.SH"], "trade_date": ["20260417"], "close": [3845.20]}
    )
    df = client.index_daily(
        ts_code="000300.SH", start_date="20260413", end_date="20260417"
    )
    mock_pro.index_daily.assert_called_once_with(
        ts_code="000300.SH", start_date="20260413", end_date="20260417"
    )
    assert df.iloc[0]["close"] == 3845.20


def test_daily_passes_kwargs(client, mock_pro):
    mock_pro.daily.return_value = pd.DataFrame(
        {"ts_code": ["300750.SZ"], "trade_date": ["20260417"], "close": [192.30]}
    )
    df = client.daily(
        ts_code="300750.SZ", start_date="20260413", end_date="20260417"
    )
    mock_pro.daily.assert_called_once_with(
        ts_code="300750.SZ", start_date="20260413", end_date="20260417"
    )
    assert df.iloc[0]["close"] == 192.30


def test_stock_basic_uses_listed_status(client, mock_pro):
    mock_pro.stock_basic.return_value = pd.DataFrame(
        {"ts_code": ["000001.SZ"], "name": ["平安银行"]}
    )
    df = client.stock_basic()
    mock_pro.stock_basic.assert_called_once_with(
        exchange="",
        list_status="L",
        fields="ts_code,symbol,name,area,industry,market",
    )
    assert df.iloc[0]["name"] == "平安银行"


def test_fund_basic_filters_etf_listed(client, mock_pro):
    mock_pro.fund_basic.return_value = pd.DataFrame(
        {"ts_code": ["512760.SH"], "name": ["芯片ETF国泰"]}
    )
    df = client.fund_basic()
    mock_pro.fund_basic.assert_called_once_with(market="E", status="L")
    assert df.iloc[0]["name"] == "芯片ETF国泰"


def test_fund_daily_passes_dates(client, mock_pro):
    mock_pro.fund_daily.return_value = pd.DataFrame(
        {"ts_code": ["512480.SH"], "trade_date": ["20260417"], "close": [1.628]}
    )
    df = client.fund_daily(
        ts_code="512480.SH", start_date="20260413", end_date="20260417"
    )
    mock_pro.fund_daily.assert_called_once_with(
        ts_code="512480.SH", start_date="20260413", end_date="20260417"
    )
    assert df.iloc[0]["close"] == 1.628


def test_moneyflow_hsgt_passes_dates(client, mock_pro):
    mock_pro.moneyflow_hsgt.return_value = pd.DataFrame(
        {"trade_date": ["20260417"], "north_money": ["292500.49"]}
    )
    df = client.moneyflow_hsgt(start_date="20260413", end_date="20260417")
    mock_pro.moneyflow_hsgt.assert_called_once_with(
        start_date="20260413", end_date="20260417"
    )
    # TuShare returns string values for moneyflow_hsgt — caller converts
    assert df.iloc[0]["north_money"] == "292500.49"
