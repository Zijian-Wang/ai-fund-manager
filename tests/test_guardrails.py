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
            "quantity": 100, "reason": {}
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


# ---- Ticker + lot size ----

def test_unknown_ticker_errors():
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "999999", "name": "假",
            "quantity": 100, "reason": {}
        }]),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"999999": 10.0},
        valid_tickers=VALID_TICKERS,
    )
    assert any(e.rule == "ticker" for e in errors)


def test_quantity_not_multiple_of_100_errors():
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "300750", "name": "宁德",
            "quantity": 50, "reason": {}
        }]),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert any(e.rule == "lot_size" for e in errors)


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
            "quantity": 100, "reason": {}
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
            "quantity": 100, "reason": {}
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
         "quantity": 100, "reason": {}}
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
         "quantity": 100, "reason": {}}
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


# ---- Max single position 50% ----

def test_buy_that_pushes_position_over_50pct_errors():
    # NAV is ~100k, buying 400 shares @ 200 = 80k (80% of portfolio)
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "300750", "name": "宁德",
            "quantity": 400, "reason": {}
        }]),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert any(e.rule == "max_single_position" for e in errors)


def test_buy_that_stays_under_50pct_is_fine():
    # NAV is ~100k, buying 200 shares @ 200 = 40k (40%)
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "300750", "name": "宁德",
            "quantity": 200, "reason": {}
        }]),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert not any(e.rule == "max_single_position" for e in errors)


def test_buy_into_existing_position_counts_total():
    """Adding to an existing position — total value must stay <= 50%."""
    state = _base_state(
        current_cash=60000,
        positions=[{
            "ticker": "300750", "name": "宁德", "quantity": 200,
            "avg_cost": 180.00, "bought_date": "2026-04-10",
        }],
    )
    # Existing 200 @ 200 = 40k, plus new 200 @ 200 = 40k, total = 80k
    # Pre-trade NAV = 60k cash + 200*200 = 100k. Post buy position = 80k = 80%.
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "300750", "name": "宁德",
            "quantity": 200, "reason": {}
        }]),
        state=state,
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
    )
    assert any(e.rule == "max_single_position" for e in errors)


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
            "quantity": 100, "reason": {}
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
            "quantity": 100, "reason": {}
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
            "quantity": 100, "reason": {}
        }]),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
        ticker_volumes_yuan={"300750": 3_000_000},  # ¥3M, under 5M threshold
    )
    assert any(e.rule == "min_volume" for e in errors)


def test_min_volume_skipped_when_data_missing():
    """No volume data → skip check (orchestrator couldn't get it)."""
    errors = validate_decision(
        _base_decision(decisions=[{
            "action": "BUY", "ticker": "300750", "name": "宁德",
            "quantity": 100, "reason": {}
        }]),
        state=_base_state(),
        eval_date="2026-04-17",
        current_prices={"300750": 200.00},
        valid_tickers=VALID_TICKERS,
        ticker_volumes_yuan={},  # no data
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
