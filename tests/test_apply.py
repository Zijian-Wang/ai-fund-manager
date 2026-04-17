"""Tests for apply_agent_decision — the validate + apply + nav-append helper."""
from __future__ import annotations

import pytest

from src.apply import apply_agent_decision


def _base_state() -> dict:
    return {
        "agent": "claude",
        "inception_date": "2026-04-17",
        "initial_capital": 100000,
        "current_cash": 100000,
        "last_eval_date": None,
        "positions": [],
        "trade_history": [],
        "nav_history": [],
    }


def _decision(**overrides) -> dict:
    base = {
        "eval_date": "2026-04-17",
        "market_view": "bullish",
        "decisions": [],
    }
    base.update(overrides)
    return base


def test_clean_buy_applied_and_nav_entry_added():
    state = _base_state()
    decision = _decision(decisions=[
        {"action": "BUY", "ticker": "300750", "name": "宁德时代",
         "quantity": 100, "reason": {"thesis": "ok"}},
    ])
    new_state, errors = apply_agent_decision(
        decision=decision, state=state, eval_date="2026-04-17",
        current_prices={"300750": 185.50},
        valid_tickers={"300750"},
        ticker_volumes_yuan={"300750": 10_000_000},
        benchmark_close=4728.67,
    )
    assert errors == []
    assert new_state["current_cash"] == 100000 - 100 * 185.50
    assert len(new_state["positions"]) == 1
    assert new_state["positions"][0]["ticker"] == "300750"
    assert new_state["last_eval_date"] == "2026-04-17"
    assert len(new_state["nav_history"]) == 1
    assert new_state["nav_history"][0]["date"] == "2026-04-17"
    assert new_state["nav_history"][0]["benchmark_close"] == 4728.67


def test_rejected_decision_returns_original_state():
    state = _base_state()
    decision = _decision(decisions=[
        {"action": "BUY", "ticker": "999999", "name": "bogus",
         "quantity": 100, "reason": {}},
    ])
    new_state, errors = apply_agent_decision(
        decision=decision, state=state, eval_date="2026-04-17",
        current_prices={},
        valid_tickers={"300750"},  # 999999 not in set
        ticker_volumes_yuan={},
        benchmark_close=4728.67,
    )
    assert len(errors) >= 1
    assert any(e.rule == "ticker" for e in errors)
    # State unchanged
    assert new_state == state
    # No mutation of input
    assert state["last_eval_date"] is None


def test_sell_applied():
    state = {
        **_base_state(),
        "current_cash": 0,
        "positions": [
            {"ticker": "300750", "name": "宁德时代", "quantity": 200,
             "avg_cost": 180.0, "bought_date": "2026-04-10"},
        ],
    }
    decision = _decision(decisions=[
        {"action": "SELL", "ticker": "300750", "name": "宁德时代",
         "quantity": 100, "reason": {"thesis": "take profit"}},
    ])
    new_state, errors = apply_agent_decision(
        decision=decision, state=state, eval_date="2026-04-17",
        current_prices={"300750": 200.0},
        valid_tickers={"300750"},
        benchmark_close=4728.67,
    )
    assert errors == []
    assert new_state["current_cash"] == 100 * 200.0
    assert new_state["positions"][0]["quantity"] == 100


def test_hold_only_decision_still_appends_nav():
    """Even with no trades, we record an NAV snapshot for track-record continuity."""
    state = {
        **_base_state(),
        "current_cash": 50000,
        "positions": [
            {"ticker": "300750", "name": "宁德时代", "quantity": 100,
             "avg_cost": 180.0, "bought_date": "2026-04-10"},
        ],
    }
    decision = _decision(decisions=[
        {"action": "HOLD", "ticker": "300750", "name": "宁德时代"},
    ])
    new_state, errors = apply_agent_decision(
        decision=decision, state=state, eval_date="2026-04-17",
        current_prices={"300750": 200.0},
        valid_tickers={"300750"},
        benchmark_close=4728.67,
    )
    assert errors == []
    assert len(new_state["nav_history"]) == 1
    # NAV = 50000 cash + 100 * 200 = 70000
    assert new_state["nav_history"][0]["nav"] == 70000.0
    assert new_state["last_eval_date"] == "2026-04-17"


def test_empty_decisions_list_still_appends_nav():
    """All-cash observation day — no trades, still want an NAV checkpoint."""
    state = _base_state()
    decision = _decision(decisions=[])
    new_state, errors = apply_agent_decision(
        decision=decision, state=state, eval_date="2026-04-17",
        current_prices={},
        valid_tickers=set(),
        benchmark_close=4728.67,
    )
    assert errors == []
    assert len(new_state["nav_history"]) == 1
    assert new_state["nav_history"][0]["nav"] == 100000.0


def test_multi_decision_buy_sell_hold_order():
    state = {
        **_base_state(),
        "current_cash": 50000,
        "positions": [
            {"ticker": "600519", "name": "贵州茅台", "quantity": 100,
             "avg_cost": 1500.0, "bought_date": "2026-04-10"},
        ],
    }
    decision = _decision(decisions=[
        {"action": "SELL", "ticker": "600519", "name": "贵州茅台",
         "quantity": 100, "reason": {"thesis": "locked in"}},
        {"action": "BUY", "ticker": "300750", "name": "宁德时代",
         "quantity": 100, "reason": {"thesis": "enter"}},
        {"action": "HOLD", "ticker": "000001", "name": "平安银行"},
    ])
    new_state, errors = apply_agent_decision(
        decision=decision, state=state, eval_date="2026-04-17",
        current_prices={"600519": 1600.0, "300750": 185.0, "000001": 12.0},
        valid_tickers={"600519", "300750", "000001"},
        benchmark_close=4728.67,
    )
    assert errors == []
    # Cash: 50000 + 100*1600 (sell) - 100*185 (buy) = 191,500
    assert new_state["current_cash"] == 50000 + 100 * 1600 - 100 * 185
    # Position count: removed 600519, added 300750
    tickers = {p["ticker"] for p in new_state["positions"]}
    assert tickers == {"300750"}


def test_input_state_not_mutated_on_success():
    state = _base_state()
    decision = _decision(decisions=[
        {"action": "BUY", "ticker": "300750", "name": "宁德时代",
         "quantity": 100, "reason": {"thesis": ""}},
    ])
    apply_agent_decision(
        decision=decision, state=state, eval_date="2026-04-17",
        current_prices={"300750": 185.50},
        valid_tickers={"300750"},
        benchmark_close=4728.67,
    )
    # Original state dict untouched
    assert state["current_cash"] == 100000
    assert state["positions"] == []
    assert state["nav_history"] == []
    assert state["last_eval_date"] is None
