"""Tests for BaoStock wrapper using injected mock module.

Per probe findings the iteration pattern is:
    while (rs.error_code == "0") and rs.next():
        rows.append(rs.get_row_data())

``next()`` returns truthy if there's a next row (and advances the cursor),
``get_row_data()`` returns the current row as a list of strings.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.data.baostock_client import BaoStockClient


class FakeResultSet:
    """Mimics BaoStock's ResultData iteration semantics."""

    def __init__(self, rows: list[list[str]], fields: list[str]) -> None:
        self.error_code = "0"
        self.error_msg = "success"
        self.fields = fields
        self._rows = list(rows)
        self._idx = -1

    def next(self) -> bool:
        self._idx += 1
        return self._idx < len(self._rows)

    def get_row_data(self) -> list[str]:
        return self._rows[self._idx]


@pytest.fixture
def mock_bs() -> MagicMock:
    bs = MagicMock()
    bs.login.return_value = MagicMock(error_code="0", error_msg="success")
    return bs


def test_init_logs_in(mock_bs):
    BaoStockClient(_bs=mock_bs)
    mock_bs.login.assert_called_once()


def test_init_raises_on_login_failure():
    bs = MagicMock()
    bs.login.return_value = MagicMock(error_code="10001", error_msg="auth failed")
    with pytest.raises(RuntimeError, match="BaoStock login failed"):
        BaoStockClient(_bs=bs)


def test_index_daily_iterates_correctly(mock_bs):
    mock_bs.query_history_k_data_plus.return_value = FakeResultSet(
        rows=[
            ["2026-04-16", "sh.000300", "4694.43", "4739.22", "4689.41", "4736.60"],
            ["2026-04-17", "sh.000300", "4728.99", "4738.32", "4714.46", "4728.67"],
        ],
        fields=["date", "code", "open", "high", "low", "close"],
    )
    client = BaoStockClient(_bs=mock_bs)
    rows = client.index_daily(
        code="sh.000300", start_date="2026-04-13", end_date="2026-04-17"
    )
    mock_bs.query_history_k_data_plus.assert_called_once()
    call_args = mock_bs.query_history_k_data_plus.call_args
    # First positional is the code
    assert call_args.args[0] == "sh.000300"
    # Fields passed as positional or via kwargs — check date range is in kwargs
    assert call_args.kwargs["start_date"] == "2026-04-13"
    assert call_args.kwargs["end_date"] == "2026-04-17"

    assert len(rows) == 2
    # Normalized to descending (latest-first) to match TuShare's convention.
    assert rows[0] == {
        "date": "2026-04-17",
        "code": "sh.000300",
        "open": 4728.99,
        "high": 4738.32,
        "low": 4714.46,
        "close": 4728.67,
    }
    assert rows[1]["close"] == 4736.60


def test_stock_daily_parses_volume_and_amount(mock_bs):
    mock_bs.query_history_k_data_plus.return_value = FakeResultSet(
        rows=[
            ["2026-04-17", "sz.300750", "190.0", "193.0", "189.5", "192.30",
             "1000000", "192300000.00"],
        ],
        fields=["date", "code", "open", "high", "low", "close", "volume", "amount"],
    )
    client = BaoStockClient(_bs=mock_bs)
    rows = client.stock_daily(
        code="sz.300750", start_date="2026-04-13", end_date="2026-04-17"
    )
    assert rows[0]["close"] == 192.30
    assert rows[0]["volume"] == 1000000.0
    assert rows[0]["amount"] == 192300000.00


def test_empty_value_becomes_none(mock_bs):
    mock_bs.query_history_k_data_plus.return_value = FakeResultSet(
        rows=[["2026-04-17", "sh.000300", "", "4738.32", "4714.46", "4728.67"]],
        fields=["date", "code", "open", "high", "low", "close"],
    )
    client = BaoStockClient(_bs=mock_bs)
    rows = client.index_daily(
        code="sh.000300", start_date="2026-04-17", end_date="2026-04-17"
    )
    assert rows[0]["open"] is None
    assert rows[0]["close"] == 4728.67


def test_rows_are_latest_first(mock_bs):
    """Contract: rows[0] must be the latest date (matches TuShare)."""
    mock_bs.query_history_k_data_plus.return_value = FakeResultSet(
        rows=[
            # BaoStock yields ascending — we should flip.
            ["2026-04-13", "sh.000300", "4600", "4610", "4590", "4605"],
            ["2026-04-14", "sh.000300", "4605", "4620", "4600", "4615"],
            ["2026-04-15", "sh.000300", "4615", "4630", "4610", "4625"],
            ["2026-04-16", "sh.000300", "4625", "4640", "4620", "4635"],
            ["2026-04-17", "sh.000300", "4635", "4650", "4630", "4645"],
        ],
        fields=["date", "code", "open", "high", "low", "close"],
    )
    client = BaoStockClient(_bs=mock_bs)
    rows = client.index_daily(
        code="sh.000300", start_date="2026-04-13", end_date="2026-04-17"
    )
    assert rows[0]["date"] == "2026-04-17"
    assert rows[-1]["date"] == "2026-04-13"


def test_returns_empty_when_query_errored(mock_bs):
    """If the query itself returned a non-zero error_code, no rows are read."""
    rs = FakeResultSet(
        rows=[["2026-04-17", "sh.000300", "4728.99", "4738.32", "4714.46", "4728.67"]],
        fields=["date", "code", "open", "high", "low", "close"],
    )
    rs.error_code = "10001"
    rs.error_msg = "no permission"
    mock_bs.query_history_k_data_plus.return_value = rs

    client = BaoStockClient(_bs=mock_bs)
    rows = client.index_daily(
        code="sh.000300", start_date="2026-04-13", end_date="2026-04-17"
    )
    assert rows == []
