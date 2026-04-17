"""Tests for the per-agent Markdown report renderer."""
from __future__ import annotations

from src.output.renderer import render_agent_report


def _decision_sample() -> dict:
    return {
        "eval_date": "2026-04-17",
        "market_view": "当前市场震荡，结构性行情为主。新能源和医药有轮动机会。",
        "decisions": [
            {
                "action": "BUY",
                "ticker": "300750",
                "name": "宁德时代",
                "quantity": 100,
                "reason": {
                    "thesis": "新能源长期趋势 + Q1业绩催化",
                    "catalyst": "Q1财报 + 海外订单落地",
                    "risk": "欧美关税不确定性",
                    "invalidation": "Q1净利润不及预期",
                },
            },
            {
                "action": "HOLD",
                "ticker": "600519",
                "name": "贵州茅台",
            },
        ],
        "watchlist_updates": [
            {"ticker": "300308", "name": "中际旭创", "note": "等回调再看"}
        ],
        "reflection": "上期买入 300750 判断基本正确，涨幅 3.7%。",
        "note_to_audience": "市场在这个位置，别慌。",
    }


def _state_sample() -> dict:
    return {
        "agent": "claude",
        "inception_date": "2026-04-01",
        "initial_capital": 100000,
        "current_cash": 81450,
        "last_eval_date": "2026-04-17",
        "positions": [
            {"ticker": "300750", "name": "宁德时代", "quantity": 100,
             "avg_cost": 185.50, "bought_date": "2026-04-17"},
        ],
        "trade_history": [],
        "nav_history": [],
    }


def test_report_starts_with_agent_header():
    out = render_agent_report(
        display_name="Claude",
        decision=_decision_sample(),
        state=_state_sample(),
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=4671.00,
    )
    first_line = out.splitlines()[0]
    assert "Claude" in first_line
    assert "2026-04-17" in first_line


def test_report_includes_market_view():
    out = render_agent_report(
        display_name="Claude",
        decision=_decision_sample(),
        state=_state_sample(),
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=4671.00,
    )
    assert "市场判断" in out
    assert "当前市场震荡" in out


def test_report_groups_decisions_by_action():
    out = render_agent_report(
        display_name="Claude",
        decision=_decision_sample(),
        state=_state_sample(),
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=4671.00,
    )
    assert "买入" in out
    assert "持有" in out or "HOLD" in out
    assert "宁德时代" in out
    assert "新能源长期趋势" in out
    assert "Q1财报" in out
    assert "Q1净利润不及预期" in out


def test_report_renders_current_portfolio_table():
    out = render_agent_report(
        display_name="Claude",
        decision=_decision_sample(),
        state=_state_sample(),
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=4671.00,
    )
    assert "当前组合" in out or "持仓" in out
    assert "81,450" in out


def test_report_includes_watchlist_updates():
    out = render_agent_report(
        display_name="Claude",
        decision=_decision_sample(),
        state=_state_sample(),
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=4671.00,
    )
    assert "观察" in out or "watchlist" in out.lower()
    assert "中际旭创" in out
    assert "等回调再看" in out


def test_report_includes_reflection_and_audience_note():
    out = render_agent_report(
        display_name="Claude",
        decision=_decision_sample(),
        state=_state_sample(),
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=4671.00,
    )
    assert "反思" in out
    assert "上期买入 300750 判断基本正确" in out
    assert "致观众" in out or "观众" in out
    assert "别慌" in out


def test_report_handles_no_decisions_gracefully():
    decision = {
        "eval_date": "2026-04-17",
        "market_view": "观望",
        "decisions": [],
        "watchlist_updates": [],
        "reflection": "",
        "note_to_audience": "",
    }
    state = {
        "agent": "claude",
        "initial_capital": 100000,
        "current_cash": 100000,
        "positions": [],
        "trade_history": [],
        "nav_history": [],
        "inception_date": "2026-04-17",
    }
    out = render_agent_report(
        display_name="Claude",
        decision=decision,
        state=state,
        current_prices={},
        benchmark_close=None,
        inception_benchmark_close=None,
    )
    assert "Claude" in out
    assert "2026-04-17" in out
    assert "无操作" in out or "暂无" in out
