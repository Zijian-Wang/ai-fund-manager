"""Tests for AKShare wrapper using injected mock module.

Per probe findings: only sector_ranking is reliable; AKShare's other
endpoints (moneyflow_hsgt, fina indicators) backed by datacenter-web.
eastmoney.com are unreachable and dropped from Phase 1.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.data.akshare_client import AKShareClient


@pytest.fixture
def mock_ak() -> MagicMock:
    return MagicMock()


@pytest.fixture
def fake_sleep():
    calls: list[float] = []

    def _sleep(seconds: float) -> None:
        calls.append(seconds)

    _sleep.calls = calls  # type: ignore[attr-defined]
    return _sleep


def test_sector_ranking_returns_normalized_records(mock_ak, fake_sleep):
    mock_ak.stock_board_industry_name_em.return_value = pd.DataFrame(
        {
            "板块名称": ["医药生物", "电子"],
            "涨跌幅": [3.2, -1.1],
            "板块代码": ["BK0727", "BK0737"],
        }
    )
    client = AKShareClient(_ak=mock_ak, _sleep=fake_sleep)
    rows = client.sector_ranking()
    assert rows == [
        {"name": "医药生物", "code": "BK0727", "change_pct": 3.2},
        {"name": "电子", "code": "BK0737", "change_pct": -1.1},
    ]
    # No retry needed
    assert fake_sleep.calls == []


def test_sector_ranking_retries_on_failure(mock_ak, fake_sleep):
    mock_ak.stock_board_industry_name_em.side_effect = [
        ConnectionError("first fail"),
        ConnectionError("second fail"),
        pd.DataFrame(
            {"板块名称": ["医药生物"], "涨跌幅": [3.2], "板块代码": ["BK0727"]}
        ),
    ]
    client = AKShareClient(
        _ak=mock_ak, _sleep=fake_sleep, max_retries=3, backoff_initial_sec=0.5
    )
    rows = client.sector_ranking()
    assert rows == [{"name": "医药生物", "code": "BK0727", "change_pct": 3.2}]
    # Exponential backoff: 0.5, 1.0
    assert fake_sleep.calls == [0.5, 1.0]


def test_sector_ranking_raises_after_max_retries(mock_ak, fake_sleep):
    mock_ak.stock_board_industry_name_em.side_effect = ConnectionError("always fails")
    client = AKShareClient(
        _ak=mock_ak, _sleep=fake_sleep, max_retries=3, backoff_initial_sec=0.5
    )
    with pytest.raises(ConnectionError, match="always fails"):
        client.sector_ranking()
    assert mock_ak.stock_board_industry_name_em.call_count == 3
    # Slept twice between three attempts
    assert fake_sleep.calls == [0.5, 1.0]
