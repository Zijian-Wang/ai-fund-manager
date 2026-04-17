"""Tests for news_fetcher (Eastmoney + 财联社).

Probe-validated payload shapes:
- Eastmoney: data.fastNewsList[*] with title/summary/showTime
- 财联社:    data.roll_data[*]    with title/brief/ctime (epoch int)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.data.news_fetcher import (
    fetch_caixin,
    fetch_eastmoney,
    fetch_news,
)


_EASTMONEY_PAYLOAD = {
    "code": "1",
    "data": {
        "fastNewsList": [
            {
                "title": "国务院发布药品价格形成机制新政",
                "summary": "今日国务院常务会议通过...",
                "showTime": "2026-04-17 14:30:00",
            },
            {
                "title": "央行净投放 1500 亿元",
                "summary": "央行通过 7 天逆回购...",
                "showTime": "2026-04-17 09:20:00",
            },
        ],
    },
}


_CAIXIN_PAYLOAD = {
    "error": 0,
    "data": {
        "roll_data": [
            {
                "title": "新能源车4月销量预计同比+25%",
                "brief": "中汽协预测4月新能源车批发销量约80万辆...",
                "ctime": 1744892400,
            },
            {
                "title": "美联储官员讲话偏鹰",
                "brief": "Mester表示需保持限制性政策...",
                "ctime": 1744889400,
            },
        ],
    },
}


# ---- Eastmoney ----

def test_fetch_eastmoney_returns_normalized_items():
    mock_resp = MagicMock()
    mock_resp.json.return_value = _EASTMONEY_PAYLOAD
    mock_resp.raise_for_status.return_value = None
    with patch("src.data.news_fetcher.requests.get", return_value=mock_resp) as mget:
        items = fetch_eastmoney(limit=10)
    assert mget.called
    assert len(items) == 2
    assert items[0] == {
        "title": "国务院发布药品价格形成机制新政",
        "summary": "今日国务院常务会议通过...",
        "source": "eastmoney",
        "timestamp": "2026-04-17 14:30:00",
    }


def test_fetch_eastmoney_respects_limit():
    mock_resp = MagicMock()
    mock_resp.json.return_value = _EASTMONEY_PAYLOAD
    mock_resp.raise_for_status.return_value = None
    with patch("src.data.news_fetcher.requests.get", return_value=mock_resp):
        items = fetch_eastmoney(limit=1)
    assert len(items) == 1


def test_fetch_eastmoney_returns_empty_on_http_error():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = RuntimeError("503")
    with patch("src.data.news_fetcher.requests.get", return_value=mock_resp):
        assert fetch_eastmoney(limit=10) == []


def test_fetch_eastmoney_returns_empty_on_unexpected_payload():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"unexpected": "shape"}
    mock_resp.raise_for_status.return_value = None
    with patch("src.data.news_fetcher.requests.get", return_value=mock_resp):
        assert fetch_eastmoney(limit=10) == []


# ---- 财联社 ----

def test_fetch_caixin_returns_normalized_items():
    mock_resp = MagicMock()
    mock_resp.json.return_value = _CAIXIN_PAYLOAD
    mock_resp.raise_for_status.return_value = None
    with patch("src.data.news_fetcher.requests.get", return_value=mock_resp):
        items = fetch_caixin(limit=10)
    assert len(items) == 2
    assert items[0]["title"] == "新能源车4月销量预计同比+25%"
    assert items[0]["summary"].startswith("中汽协预测")
    assert items[0]["source"] == "caixin"
    # ctime is converted to a timestamp string (we don't assert exact format)
    assert items[0]["timestamp"]


def test_fetch_caixin_returns_empty_on_http_error():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = RuntimeError("503")
    with patch("src.data.news_fetcher.requests.get", return_value=mock_resp):
        assert fetch_caixin(limit=10) == []


# ---- merged news ----

def test_fetch_news_merges_and_dedups_by_title():
    eastmoney_items = [
        {"title": "央行净投放 1500 亿元", "summary": "...",
         "source": "eastmoney", "timestamp": "2026-04-17 09:20:00"},
        {"title": "国务院发布药品价格形成机制新政", "summary": "...",
         "source": "eastmoney", "timestamp": "2026-04-17 14:30:00"},
    ]
    caixin_items = [
        {"title": "央行净投放 1500 亿元", "summary": "...",
         "source": "caixin", "timestamp": "2026-04-17 09:21:00"},
        {"title": "新能源车4月销量预计同比+25%", "summary": "...",
         "source": "caixin", "timestamp": "2026-04-17 16:00:00"},
    ]
    with patch("src.data.news_fetcher.fetch_eastmoney",
               return_value=eastmoney_items), \
         patch("src.data.news_fetcher.fetch_caixin",
               return_value=caixin_items):
        merged = fetch_news(limit=10)
    titles = [item["title"] for item in merged]
    assert len(titles) == len(set(titles))  # no dupes
    assert "央行净投放 1500 亿元" in titles
    assert "国务院发布药品价格形成机制新政" in titles
    assert "新能源车4月销量预计同比+25%" in titles


def test_fetch_news_partial_when_one_source_fails():
    with patch("src.data.news_fetcher.fetch_eastmoney",
               return_value=[{"title": "T1", "summary": "...",
                              "source": "eastmoney", "timestamp": "..."}]), \
         patch("src.data.news_fetcher.fetch_caixin", return_value=[]):
        merged = fetch_news(limit=10)
    assert [item["title"] for item in merged] == ["T1"]


def test_fetch_news_returns_empty_when_both_fail():
    with patch("src.data.news_fetcher.fetch_eastmoney", return_value=[]), \
         patch("src.data.news_fetcher.fetch_caixin", return_value=[]):
        assert fetch_news(limit=10) == []
