"""Tests for briefing assembly + system prompt rendering."""
from __future__ import annotations

import pytest

from src.briefing import (
    INDEX_DISPLAY_NAMES,
    SYSTEM_PROMPT_TEMPLATE,
    build_agent_briefing,
    build_full_prompt,
    build_shared_briefing,
)


# ---- index name map ----

def test_index_display_names_covers_all_four():
    assert set(INDEX_DISPLAY_NAMES.keys()) == {
        "000001.SH", "399001.SZ", "399006.SZ", "000300.SH"
    }
    assert INDEX_DISPLAY_NAMES["000300.SH"] == "沪深300"


# ---- build_shared_briefing ----

def _market_data_sample() -> dict:
    return {
        "eval_date": "2026-04-17",
        "indices": {
            "000300.SH": {
                "source": "tushare",
                "rows": [
                    # newest first per TuShare convention
                    {"trade_date": "20260417", "close": 4728.67, "pct_chg": -0.17},
                    {"trade_date": "20260416", "close": 4736.61, "pct_chg": 1.10},
                    {"trade_date": "20260415", "close": 4685.25, "pct_chg": 0.30},
                    {"trade_date": "20260414", "close": 4671.16, "pct_chg": -0.50},
                    {"trade_date": "20260413", "close": 4694.74, "pct_chg": 0.20},
                ],
            },
            "000001.SH": {
                "source": "tushare",
                "rows": [
                    {"trade_date": "20260417", "close": 4027.21, "pct_chg": 0.01},
                    {"trade_date": "20260413", "close": 4047.51, "pct_chg": 0.0},
                ],
            },
            "399001.SZ": {"source": "tushare", "rows": [
                {"trade_date": "20260417", "close": 13000.0, "pct_chg": 0.5},
                {"trade_date": "20260413", "close": 12900.0, "pct_chg": 0.0},
            ]},
            "399006.SZ": {"source": "tushare", "rows": [
                {"trade_date": "20260417", "close": 2800.0, "pct_chg": 1.2},
                {"trade_date": "20260413", "close": 2750.0, "pct_chg": 0.0},
            ]},
        },
        "sector_ranking": {
            "source": "akshare",
            "rows": [
                {"name": "医药生物", "code": "BK0727", "change_pct": 3.2},
                {"name": "电子", "code": "BK0737", "change_pct": 2.1},
                {"name": "新能源", "code": "BK0801", "change_pct": -1.1},
            ],
        },
        "northbound": {
            "source": "tushare",
            "rows": [
                {"trade_date": "20260417", "north_money": "292500.49"},
                {"trade_date": "20260416", "north_money": "150000.00"},
            ],
        },
        "holdings": {},
        "errors": [],
    }


def _news_sample() -> list[dict]:
    return [
        {"title": "国务院发布药品价格形成机制新政", "summary": "...",
         "source": "eastmoney", "timestamp": "2026-04-17 14:30:00"},
        {"title": "央行净投放 1500 亿元", "summary": "...",
         "source": "eastmoney", "timestamp": "2026-04-17 09:20:00"},
    ]


def test_build_shared_briefing_includes_date_header():
    out = build_shared_briefing(_market_data_sample(), _news_sample())
    assert "市场简报" in out
    assert "2026-04-17" in out


def test_build_shared_briefing_includes_all_4_indices_with_chinese_names():
    out = build_shared_briefing(_market_data_sample(), _news_sample())
    assert "上证综指" in out
    assert "深证成指" in out
    assert "创业板指" in out
    assert "沪深300" in out
    # Most recent close is rendered
    assert "4,728.67" in out or "4728.67" in out


def test_build_shared_briefing_includes_sector_top_n():
    out = build_shared_briefing(_market_data_sample(), _news_sample())
    assert "医药生物" in out
    assert "+3.2" in out


def test_build_shared_briefing_includes_northbound_summary():
    out = build_shared_briefing(_market_data_sample(), _news_sample())
    assert "北向" in out
    # Sum of 2 rows (292500.49 + 150000.00 万元) = 442500.49 万元 = 44.25 亿元
    assert "44.25" in out


def test_build_shared_briefing_lists_news_titles():
    out = build_shared_briefing(_market_data_sample(), _news_sample())
    assert "国务院发布药品价格形成机制新政" in out
    assert "央行净投放" in out


def test_build_shared_briefing_handles_empty_news():
    out = build_shared_briefing(_market_data_sample(), [])
    assert "新闻数据暂不可用" in out or "新闻" in out


def test_build_shared_briefing_handles_missing_index():
    md = _market_data_sample()
    md["indices"]["000001.SH"]["rows"] = []
    out = build_shared_briefing(md, _news_sample())
    # Doesn't crash; missing index just shown as "—" or omitted
    assert "上证综指" in out


# ---- build_agent_briefing ----

def _state_sample(**overrides) -> dict:
    base = {
        "agent": "gemini",
        "initial_capital": 100000,
        "current_cash": 81450,
        "positions": [
            {
                "ticker": "300750", "name": "宁德时代", "quantity": 100,
                "avg_cost": 185.50, "bought_date": "2026-04-10",
            }
        ],
        "trade_history": [],
        "nav_history": [],
    }
    base.update(overrides)
    return base


def test_build_agent_briefing_shows_holdings_table():
    out = build_agent_briefing(
        shared="(shared briefing here)",
        agent_name="gemini",
        state=_state_sample(),
        prev_decision=None,
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=4671.00,
    )
    assert "你的持仓" in out
    assert "宁德时代" in out
    assert "300750" in out
    assert "100" in out
    # 192.30 current price
    assert "192.30" in out
    # (192.30 - 185.50) / 185.50 = +3.67%
    assert "+3.67" in out


def test_build_agent_briefing_shows_nav_and_cash():
    out = build_agent_briefing(
        shared="",
        agent_name="gemini",
        state=_state_sample(),
        prev_decision=None,
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=None,
    )
    # NAV = 81450 + 100*192.30 = 100,680
    assert "100,680" in out
    # Current cash
    assert "81,450" in out


def test_build_agent_briefing_shows_vs_benchmark_when_provided():
    out = build_agent_briefing(
        shared="",
        agent_name="gemini",
        state=_state_sample(),
        prev_decision=None,
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=4671.00,
    )
    # benchmark return: (4728.67 - 4671.00) / 4671.00 = 0.01235 → +1.23%
    assert "CSI300" in out
    assert "+1.2" in out


def test_build_agent_briefing_omits_vs_benchmark_when_inception_close_missing():
    out = build_agent_briefing(
        shared="",
        agent_name="gemini",
        state=_state_sample(),
        prev_decision=None,
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=None,
    )
    # No CSI300 comparison line
    assert "同期CSI300" not in out


def test_build_agent_briefing_renders_prev_decision_review():
    prev = {
        "eval_date": "2026-04-10",
        "decisions": [
            {
                "action": "BUY", "ticker": "300750", "name": "宁德时代",
                "quantity": 100, "reason": {"thesis": "..."}
            },
        ],
    }
    out = build_agent_briefing(
        shared="",
        agent_name="gemini",
        state=_state_sample(),
        prev_decision=prev,
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=None,
    )
    assert "上期回顾" in out
    assert "2026-04-10" in out
    assert "宁德时代" in out
    # Outcome shown — bought at 185.50, now at 192.30
    assert "192.30" in out


def test_build_agent_briefing_omits_prev_review_when_no_prev_decision():
    out = build_agent_briefing(
        shared="",
        agent_name="gemini",
        state=_state_sample(),
        prev_decision=None,
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=None,
    )
    assert "上期回顾" not in out


def test_build_agent_briefing_with_no_positions_shows_all_cash():
    out = build_agent_briefing(
        shared="",
        agent_name="gemini",
        state=_state_sample(positions=[], current_cash=100000),
        prev_decision=None,
        current_prices={},
        benchmark_close=4728.67,
        inception_benchmark_close=None,
    )
    assert "100,000" in out
    # No holdings table rows for stocks
    assert "暂无持仓" in out or "你的持仓" in out


# ---- build_full_prompt ----

def test_build_full_prompt_fills_all_placeholders():
    out = build_full_prompt(
        memory_text="MEMORY_HERE",
        portfolio_text="PORTFOLIO_HERE",
        market_briefing="BRIEFING_HERE",
    )
    assert "MEMORY_HERE" in out
    assert "PORTFOLIO_HERE" in out
    assert "BRIEFING_HERE" in out


def test_system_prompt_template_has_required_placeholders():
    assert "{memory_content}" in SYSTEM_PROMPT_TEMPLATE
    assert "{portfolio_state}" in SYSTEM_PROMPT_TEMPLATE
    assert "{market_briefing}" in SYSTEM_PROMPT_TEMPLATE


def test_system_prompt_template_describes_decision_framework():
    """Sanity check — the prompt should mention the 5-part decision framework."""
    assert "THESIS" in SYSTEM_PROMPT_TEMPLATE
    assert "CATALYST" in SYSTEM_PROMPT_TEMPLATE
    assert "RISK" in SYSTEM_PROMPT_TEMPLATE
    assert "SIZING" in SYSTEM_PROMPT_TEMPLATE
    assert "INVALIDATION" in SYSTEM_PROMPT_TEMPLATE
