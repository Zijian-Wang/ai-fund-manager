"""Tests for shared guardrail validation."""
from __future__ import annotations

import pytest

from src.guardrails import ValidationError, validate_decision


VALID_TICKERS = {"300750", "600519", "000001"}


def _base_state(**overrides) -> dict:
    state = {
        "agent": "gemini",
        "initial_capital": 100000,
        "current_cash": 100000,
        "last_eval_date": None,
        "positions": [],
        "trade_history": [],
        "nav_history": [],
    }
    state.update(overrides)
    return state


def _base_decision(**overrides) -> dict:
    decision = {
        "eval_date": "2026-04-17",
        "market_view": "...",
        "decisions": [],
        "watchlist_updates": [],
        "reflection": "",
        "note_to_audience": "",
    }
    decision.update(overrides)
    return decision


# ---- Happy paths ----

def test_valid_empty_decision_returns_no_errors():
    errors = validate_decision(
        _base_decision(),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={},
        valid_tickers=VALID_TICKERS,
    )
    assert errors == []


def test_valid_single_buy_returns_no_errors():
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "300750", "name": "宁德时代",
            "allocation_pct": 40, "reason": {}
        }]),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert errors == []


def test_hold_action_does_not_require_ticker_lookup():
    """HOLD decisions don't need ticker/quantity validation."""
    errors = validate_decision(
        _base_decision(decisions=[{"action": "HOLD"}]),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={},
        valid_tickers=VALID_TICKERS,
    )
    assert errors == []


# ---- eval_date + idempotency ----

def test_eval_date_mismatch_errors():
    errors = validate_decision(
        _base_decision(eval_date="2026-04-10"),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={},
        valid_tickers=VALID_TICKERS,
    )
    assert any(e.rule == "eval_date" for e in errors)


def test_idempotency_rejects_reapplication():
    errors = validate_decision(
        _base_decision(),
        state=_base_state(last_eval_date="2026-04-17"),
        eval_date="2026-04-17",
        current_prices={},
        valid_tickers=VALID_TICKERS,
    )
    assert any(e.rule == "idempotency" for e in errors)


# ---- Ticker ----

def test_unknown_ticker_errors():
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "999999", "name": "假",
            "allocation_pct": 20, "reason": {}
        }]),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"999999": 10.0},
        valid_tickers=VALID_TICKERS,
    )
    assert any(e.rule == "ticker" for e in errors)


# ---- allocation_pct ----

def test_allocation_pct_over_50_errors():
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "300750", "name": "宁德",
            "allocation_pct": 60, "reason": {}
        }]),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert any(e.rule == "allocation_pct" for e in errors)


def test_allocation_pct_exactly_50_is_fine():
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "300750", "name": "宁德",
            "allocation_pct": 50, "reason": {}
        }]),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert not any(e.rule == "allocation_pct" for e in errors)


def test_allocation_pct_sum_over_100_errors():
    decisions = [
        {"action": "BUY", "ticker": "300750", "name": "宁德",
         "allocation_pct": 50, "reason": {}},
        {"action": "BUY", "ticker": "600519", "name": "茅台",
         "allocation_pct": 51, "reason": {}},
    ]
    errors = validate_decision(
        _base_decision(decisions=decisions),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00, "600519": 1500.00},
        valid_tickers=VALID_TICKERS,
    )
    assert any(e.rule == "allocation_pct" for e in errors)


def test_allocation_pct_sum_exactly_100_is_fine():
    decisions = [
        {"action": "BUY", "ticker": "300750", "name": "宁德",
         "allocation_pct": 50, "reason": {}},
        {"action": "BUY", "ticker": "600519", "name": "茅台",
         "allocation_pct": 50, "reason": {}},
    ]
    errors = validate_decision(
        _base_decision(decisions=decisions),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00, "600519": 1500.00},
        valid_tickers=VALID_TICKERS,
    )
    assert not any(e.rule == "allocation_pct" for e in errors)


def test_sell_allocation_pct_excluded_from_sum():
    """SELL decisions don't count toward the 100% total."""
    decisions = [
        {"action": "SELL", "ticker": "600519", "name": "茅台",
         "allocation_pct": 0, "reason": {}},
        {"action": "BUY", "ticker": "300750", "name": "宁德",
         "allocation_pct": 50, "reason": {}},
    ]
    errors = validate_decision(
        _base_decision(decisions=decisions),
        state=_base_state(
            positions=[{"ticker": "600519", "name": "茅台",
                        "quantity": 10, "avg_cost": 1500.0,
                        "bought_date": "2026-04-10"}]
        ),
        eval_date="2026-04-17",
        current_prices={"600519": 1600.00, "300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert not any(e.rule == "allocation_pct" for e in errors)


def test_negative_allocation_pct_errors():
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "300750", "name": "宁德",
            "allocation_pct": -5, "reason": {}
        }]),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert any(e.rule == "allocation_pct" for e in errors)


# ---- T+1 ----

def test_sell_on_same_day_as_buy_errors_t1():
    state = _base_state(
        positions=[{
            "ticker": "300750", "name": "宁德时代", "quantity": 100,
            "avg_cost": 185.00, "bought_date": "2026-04-17",
        }]
    )
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "SELL", "ticker": "300750", "name": "宁德",
            "allocation_pct": 0, "reason": {}
        }]),
        state=state,
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert any(e.rule == "t_plus_1" for e in errors)


def test_sell_next_day_is_fine():
    state = _base_state(
        positions=[{
            "ticker": "300750", "name": "宁德时代", "quantity": 100,
            "avg_cost": 185.00, "bought_date": "2026-04-16",
        }]
    )
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "SELL", "ticker": "300750", "name": "宁德",
            "allocation_pct": 0, "reason": {}
        }]),
        state=state,
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert not any(e.rule == "t_plus_1" for e in errors)


# ---- Max trades per day ----

def test_more_than_10_trades_errors():
    many = [
        {"action": "BUY", "ticker": "300750", "name": "宁德",
         "allocation_pct": 5, "reason": {}}
        for _ in range(11)
    ]
    errors = validate_decision(
        _base_decision(decisions=many),
        state=_base_state(current_cash=10_000_000),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert any(e.rule == "max_trades" for e in errors)


def test_exactly_10_trades_is_fine():
    many = [
        {"action": "BUY", "ticker": "300750", "name": "宁德",
         "allocation_pct": 5, "reason": {}}
        for _ in range(10)
    ]
    errors = validate_decision(
        _base_decision(decisions=many),
        state=_base_state(current_cash=10_000_000),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert not any(e.rule == "max_trades" for e in errors)


# ---- Circuit breaker ----

def test_circuit_breaker_triggers_at_minus_15pct():
    state = _base_state(
        nav_history=[
            {"date": "2026-04-16", "nav": 84000,
             "cumulative_return_pct": -0.16, "cash_pct": 1.0, "position_count": 0,
             "benchmark_close": None},
        ]
    )
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "300750", "name": "宁德",
            "allocation_pct": 20, "reason": {}
        }]),
        state=state,
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert any(e.rule == "circuit_breaker" for e in errors)


def test_circuit_breaker_does_not_trigger_at_minus_14pct():
    state = _base_state(
        nav_history=[
            {"date": "2026-04-16", "nav": 86000,
             "cumulative_return_pct": -0.14, "cash_pct": 1.0, "position_count": 0,
             "benchmark_close": None},
        ]
    )
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "300750", "name": "宁德",
            "allocation_pct": 20, "reason": {}
        }]),
        state=state,
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert not any(e.rule == "circuit_breaker" for e in errors)


# ---- Min daily volume ----

def test_low_volume_ticker_errors_when_data_available():
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "300750", "name": "宁德",
            "allocation_pct": 20, "reason": {}
        }]),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
        ticker_volumes_yuan={"300750": 3_000_000},
    )
    assert any(e.rule == "min_volume" for e in errors)


def test_min_volume_skipped_when_data_missing():
    """No volume data → skip check (orchestrator couldn't get it)."""
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "300750", "name": "宁德",
            "allocation_pct": 20, "reason": {}
        }]),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
        ticker_volumes_yuan={},
    )
    assert not any(e.rule == "min_volume" for e in errors)


# ---- Schema ----

def test_missing_eval_date_in_decision_errors():
    errors = validate_decision(
        {"decisions": []},  # no eval_date
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={},
        valid_tickers=VALID_TICKERS,
    )
    assert any(e.rule == "schema" for e in errors)


def test_validation_error_has_rule_and_message():
    err = ValidationError(rule="test", message="something happened")
    assert err.rule == "test"
    assert err.message == "something happened"
