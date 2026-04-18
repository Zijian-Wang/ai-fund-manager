"""Tests for apply_agent_decision — the validate + apply + nav-append helper."""
from __future__ import annotations

import pytest

from src.apply import allocation_to_shares, apply_agent_decision


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


# ---- allocation_to_shares unit tests ----

def test_allocation_to_shares_basic():
    # NAV=100k, 40%, price=200 → target=40000, 40000/200=200 shares → 200
    assert allocation_to_shares(40, 100000, 200.0) == 200


def test_allocation_to_shares_rounds_down_to_lot():
    # NAV=100k, 20%, price=185.50 → target=20000, 20000/185.50=107.8 → floor(107.8/100)*100 = 100
    assert allocation_to_shares(20, 100000, 185.50) == 100


def test_allocation_to_shares_zero_pct_returns_zero():
    assert allocation_to_shares(0, 100000, 200.0) == 0


def test_allocation_to_shares_price_too_high_returns_zero():
    # NAV=100k, 1%, price=2000 → target=1000, 1000/2000=0.5 → 0 lots
    assert allocation_to_shares(1, 100000, 2000.0) == 0


# ---- apply_agent_decision integration tests ----

def test_clean_buy_applied_and_nav_entry_added():
    """BUY 40% of NAV at ¥185.50 → 200 shares."""
    state = _base_state()
    decision = _decision(decisions=[
        {"action": "BUY", "ticker": "300750", "name": "宁德时代",
         "allocation_pct": 40, "reason": {"thesis": "ok"}},
    ])
    new_state, errors = apply_agent_decision(
        decision=decision, state=state, eval_date="2026-04-17",
        current_prices={"300750": 185.50},
        valid_tickers={"300750"},
        ticker_volumes_yuan={"300750": 10_000_000},
        benchmark_close=4728.67,
    )
    assert errors == []
    # 40% of 100k = 40000, floor(40000/185.50/100)*100 = floor(2.157)*100 = 200 shares
    expected_shares = 200
    expected_cost = expected_shares * 185.50
    assert new_state["current_cash"] == pytest.approx(100000 - expected_cost)
    assert len(new_state["positions"]) == 1
    assert new_state["positions"][0]["ticker"] == "300750"
    assert new_state["positions"][0]["quantity"] == expected_shares
    assert new_state["last_eval_date"] == "2026-04-17"
    assert len(new_state["nav_history"]) == 1
    assert new_state["nav_history"][0]["benchmark_close"] == 4728.67


def test_rejected_decision_returns_original_state():
    state = _base_state()
    decision = _decision(decisions=[
        {"action": "BUY", "ticker": "999999", "name": "bogus",
         "allocation_pct": 20, "reason": {}},
    ])
    new_state, errors = apply_agent_decision(
        decision=decision, state=state, eval_date="2026-04-17",
        current_prices={},
        valid_tickers={"300750"},
        ticker_volumes_yuan={},
        benchmark_close=4728.67,
    )
    assert len(errors) >= 1
    assert any(e.rule == "ticker" for e in errors)
    assert new_state == state
    assert state["last_eval_date"] is None


def test_sell_full_position_clears_it():
    """SELL with allocation_pct=0 clears entire position."""
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
         "allocation_pct": 0, "reason": {"thesis": "take profit"}},
    ])
    new_state, errors = apply_agent_decision(
        decision=decision, state=state, eval_date="2026-04-17",
        current_prices={"300750": 200.0},
        valid_tickers={"300750"},
        benchmark_close=4728.67,
    )
    assert errors == []
    assert new_state["current_cash"] == pytest.approx(200 * 200.0)
    assert new_state["positions"] == []


def test_sell_partial_reduces_position():
    """SELL with allocation_pct=30 on a position reduces to target."""
    # NAV = 50000 cash + 200 shares @ 250 = 100000
    state = {
        **_base_state(),
        "current_cash": 50000,
        "positions": [
            {"ticker": "300750", "name": "宁德时代", "quantity": 200,
             "avg_cost": 250.0, "bought_date": "2026-04-10"},
        ],
    }
    # target = 30% of 100k / 250 = 120 → floor(120/100)*100 = 100 shares
    # current = 200, delta = -100 → sell 100 shares
    decision = _decision(decisions=[
        {"action": "SELL", "ticker": "300750", "name": "宁德时代",
         "allocation_pct": 30, "reason": {"thesis": "reduce"}},
    ])
    new_state, errors = apply_agent_decision(
        decision=decision, state=state, eval_date="2026-04-17",
        current_prices={"300750": 250.0},
        valid_tickers={"300750"},
        benchmark_close=4728.67,
    )
    assert errors == []
    assert new_state["positions"][0]["quantity"] == 100
    assert new_state["current_cash"] == pytest.approx(50000 + 100 * 250.0)


def test_sell_processed_before_buy():
    """SELLs happen first to free cash, then BUYs execute."""
    # NAV = 100 shares @ 1600 = 160000 (no cash)
    state = {
        **_base_state(),
        "current_cash": 0,
        "positions": [
            {"ticker": "600519", "name": "贵州茅台", "quantity": 100,
             "avg_cost": 1500.0, "bought_date": "2026-04-10"},
        ],
    }
    # BUY submitted before SELL in list — system must sort SELL first
    # After SELL: 160000 cash. BUY 40% of 160000 / 200 = 320 raw shares
    # → floor(320/100)*100 = 300 shares (3 lots; 320 is not a round-lot quantity)
    decision = _decision(decisions=[
        {"action": "BUY", "ticker": "300750", "name": "宁德时代",
         "allocation_pct": 40, "reason": {"thesis": "enter"}},
        {"action": "SELL", "ticker": "600519", "name": "贵州茅台",
         "allocation_pct": 0, "reason": {"thesis": "exit"}},
    ])
    new_state, errors = apply_agent_decision(
        decision=decision, state=state, eval_date="2026-04-17",
        current_prices={"600519": 1600.0, "300750": 200.0},
        valid_tickers={"600519", "300750"},
        benchmark_close=4728.67,
    )
    assert errors == []
    tickers = {p["ticker"] for p in new_state["positions"]}
    assert "600519" not in tickers
    assert "300750" in tickers
    assert new_state["positions"][0]["quantity"] == 300


def test_hold_only_decision_still_appends_nav():
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
    assert new_state["nav_history"][0]["nav"] == 70000.0
    assert new_state["last_eval_date"] == "2026-04-17"


def test_empty_decisions_list_still_appends_nav():
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


def test_input_state_not_mutated_on_success():
    state = _base_state()
    decision = _decision(decisions=[
        {"action": "BUY", "ticker": "300750", "name": "宁德时代",
         "allocation_pct": 40, "reason": {"thesis": ""}},
    ])
    apply_agent_decision(
        decision=decision, state=state, eval_date="2026-04-17",
        current_prices={"300750": 185.50},
        valid_tickers={"300750"},
        benchmark_close=4728.67,
    )
    assert state["current_cash"] == 100000
    assert state["positions"] == []
    assert state["nav_history"] == []
    assert state["last_eval_date"] is None
