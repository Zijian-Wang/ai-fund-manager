# allocation_pct Schema Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `quantity`-in-decision schema with `allocation_pct` so agents express intent in percentages and the system computes shares — eliminating math errors in agent outputs.

**Architecture:** Agents submit `allocation_pct` (0–50 integer, sum ≤ 100); `apply.py` converts to share delta via `allocation_to_shares()`; guardrails validate percentages only; renderer shows target % alongside computed shares and actual cost.

**Tech Stack:** Python 3.11+, pytest, existing `src/` layout.

---

## File Map

| File | Change |
|------|--------|
| `src/guardrails.py` | Remove `lot_size` + quantity-based `max_single_position`; add `validate_allocations` |
| `src/apply.py` | Add `allocation_to_shares`, `compute_trade`; update `apply_agent_decision` to convert pct → shares; process SELLs before BUYs |
| `src/briefing.py` | Update system prompt JSON example + constraints block; add `_render_trading_constraints`; update `_render_prev_review` |
| `src/output/renderer.py` | Add `nav` param to `render_agent_report`; update decisions section to show allocation table |
| `CLAUDE.md` | Update Agent output format schema + allocation_pct semantics section |
| `tests/test_guardrails.py` | Replace quantity tests with allocation_pct tests |
| `tests/test_apply.py` | Replace quantity decisions with allocation_pct decisions |
| `tests/test_briefing.py` | Add test for trading constraints block; update prev_review test |
| `tests/output/test_renderer.py` | Update sample decision; add nav param |

---

## Task 1: Update `guardrails.py` — allocation_pct validation

**Files:**
- Modify: `src/guardrails.py`
- Test: `tests/test_guardrails.py`

- [ ] **Step 1: Write failing tests for the new rules**

Replace the `test_quantity_not_multiple_of_100_errors` and `test_buy_that_pushes_position_over_50pct_errors` tests and add new allocation_pct tests. Open `tests/test_guardrails.py` and make these changes:

In `_base_decision`, update the helper (decisions with `allocation_pct` instead of `quantity`):
```python
# No change to _base_decision itself — individual tests supply decisions
```

Replace the existing `test_quantity_not_multiple_of_100_errors` test with:
```python
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
```

Also delete the old tests that check `quantity` / `lot_size` / `max_single_position`:
- Remove `test_quantity_not_multiple_of_100_errors`
- Remove `test_buy_that_pushes_position_over_50pct_errors`
- Remove `test_buy_that_stays_under_50pct_is_fine`
- Remove `test_buy_into_existing_position_counts_total`

Update `test_valid_single_buy_returns_no_errors` to use allocation_pct:
```python
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
```

Update T+1 tests to use allocation_pct:
```python
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
```

Update max trades tests to use allocation_pct:
```python
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
```

Update min-volume tests to use allocation_pct:
```python
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
```

Also update the circuit breaker tests to use allocation_pct:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/zijian/Developer/ai-fund-manager && python -m pytest tests/test_guardrails.py -v 2>&1 | head -60
```

Expected: multiple FAILED (rules reference `quantity`, new `allocation_pct` rule doesn't exist yet).

- [ ] **Step 3: Implement the new guardrails**

Replace `src/guardrails.py` with:

```python
"""Shared guardrail validation.

Rules implemented (per spec):
- ``eval_date``         decision's eval_date must match current
- ``idempotency``       agent's last_eval_date != current
- ``ticker``            ticker exists in valid_tickers (for BUY/SELL)
- ``allocation_pct``    each pct in 0-50; sum of non-SELL pcts <= 100
- ``t_plus_1``          cannot SELL a position bought today
- ``max_trades``        BUY+SELL count <= 10
- ``circuit_breaker``   portfolio cumulative_return_pct > -15%
- ``min_volume``        stock's daily ¥-volume >= ¥5M (when data available)
- ``schema``            decision dict has required top-level keys
"""
from __future__ import annotations

from dataclasses import dataclass


MAX_SINGLE_POSITION_PCT = 50   # allocation_pct upper bound per position
CIRCUIT_BREAKER_CUMRETURN_PCT = -0.15
MAX_TRADES_PER_DAY = 10
MIN_DAILY_VOLUME_YUAN = 5_000_000


@dataclass
class ValidationError:
    rule: str
    message: str


def validate_decision(
    decision: dict,
    *,
    state: dict,
    eval_date: str,
    current_prices: dict[str, float],
    valid_tickers: set[str],
    ticker_volumes_yuan: dict[str, float] | None = None,
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    volumes = ticker_volumes_yuan or {}

    # ---- schema ----
    if not isinstance(decision, dict) or "eval_date" not in decision:
        errors.append(ValidationError(
            rule="schema", message="decision missing 'eval_date'"
        ))
        return errors
    if "decisions" not in decision or not isinstance(decision["decisions"], list):
        errors.append(ValidationError(
            rule="schema", message="decision missing 'decisions' list"
        ))
        return errors

    # ---- eval_date match ----
    if decision["eval_date"] != eval_date:
        errors.append(ValidationError(
            rule="eval_date",
            message=f"decision eval_date {decision['eval_date']!r} != {eval_date!r}",
        ))

    # ---- idempotency ----
    if state.get("last_eval_date") == eval_date:
        errors.append(ValidationError(
            rule="idempotency",
            message=f"agent already evaluated for {eval_date}",
        ))

    # ---- circuit breaker ----
    nav_history = state.get("nav_history", [])
    if nav_history:
        last_return = nav_history[-1].get("cumulative_return_pct", 0.0)
        if last_return <= CIRCUIT_BREAKER_CUMRETURN_PCT:
            errors.append(ValidationError(
                rule="circuit_breaker",
                message=(
                    f"portfolio down {last_return:.1%} — circuit breaker at "
                    f"{CIRCUIT_BREAKER_CUMRETURN_PCT:.0%}"
                ),
            ))

    # ---- max trades ----
    trades = [
        d for d in decision["decisions"]
        if isinstance(d, dict) and d.get("action") in {"BUY", "SELL"}
    ]
    if len(trades) > MAX_TRADES_PER_DAY:
        errors.append(ValidationError(
            rule="max_trades",
            message=f"{len(trades)} trades exceeds max {MAX_TRADES_PER_DAY}",
        ))

    # ---- allocation_pct sum check (non-SELL decisions only) ----
    non_sell_pcts = [
        d.get("allocation_pct", 0)
        for d in decision["decisions"]
        if isinstance(d, dict) and d.get("action") != "SELL"
    ]
    total_pct = sum(non_sell_pcts)
    if total_pct > 100:
        errors.append(ValidationError(
            rule="allocation_pct",
            message=f"total allocation_pct {total_pct}% exceeds 100%",
        ))

    # T+1 lookup: positions bought today
    bought_dates: dict[str, str] = {
        pos["ticker"]: pos.get("bought_date", "")
        for pos in state.get("positions", [])
    }

    # ---- per-decision checks ----
    for idx, d in enumerate(decision["decisions"]):
        if not isinstance(d, dict):
            errors.append(ValidationError(
                rule="schema",
                message=f"decisions[{idx}] is not a dict",
            ))
            continue
        action = d.get("action")
        if action == "HOLD":
            continue
        if action not in {"BUY", "SELL"}:
            errors.append(ValidationError(
                rule="schema",
                message=f"decisions[{idx}] unknown action {action!r}",
            ))
            continue

        ticker = d.get("ticker", "")
        pct = d.get("allocation_pct")

        # ticker
        if ticker not in valid_tickers:
            errors.append(ValidationError(
                rule="ticker",
                message=f"unknown ticker {ticker!r} at decisions[{idx}]",
            ))

        # allocation_pct range
        if pct is None or not isinstance(pct, (int, float)) or pct < 0 or pct > MAX_SINGLE_POSITION_PCT:
            errors.append(ValidationError(
                rule="allocation_pct",
                message=(
                    f"decisions[{idx}] allocation_pct={pct!r} must be "
                    f"a number in 0–{MAX_SINGLE_POSITION_PCT}"
                ),
            ))

        # T+1
        if action == "SELL":
            if bought_dates.get(ticker) == eval_date:
                errors.append(ValidationError(
                    rule="t_plus_1",
                    message=f"cannot SELL {ticker} — bought today ({eval_date})",
                ))

        # min volume (BUY only)
        if action == "BUY":
            vol = volumes.get(ticker)
            if vol is not None and vol < MIN_DAILY_VOLUME_YUAN:
                errors.append(ValidationError(
                    rule="min_volume",
                    message=(
                        f"{ticker} daily volume ¥{vol:,.0f} < "
                        f"¥{MIN_DAILY_VOLUME_YUAN:,}"
                    ),
                ))

    return errors
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/zijian/Developer/ai-fund-manager && python -m pytest tests/test_guardrails.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/zijian/Developer/ai-fund-manager && git add src/guardrails.py tests/test_guardrails.py && git commit -m "feat(guardrails): replace quantity with allocation_pct validation"
```

---

## Task 2: Update `apply.py` — convert allocation_pct to shares

**Files:**
- Modify: `src/apply.py`
- Test: `tests/test_apply.py`

- [ ] **Step 1: Write failing tests for the new apply behavior**

Replace all of `tests/test_apply.py` with:

```python
"""Tests for apply_agent_decision — the validate + apply + nav-append helper."""
from __future__ import annotations

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
    # NAV=100k, 40%, price=200 → target=40000, 40000/200=200 shares → 200 (already multiple of 100)
    assert allocation_to_shares(40, 100000, 200.0) == 200


def test_allocation_to_shares_rounds_down_to_lot():
    # NAV=100k, 15%, price=185.50 → target=15000, 15000/185.50=80.9 shares → floor to 0 lots
    # 15000 / 185.50 = 80.86 → 0 complete lots of 100... wait
    # floor(80.86 / 100) * 100 = 0. Let's use a better example:
    # NAV=100k, 20%, price=185.50 → target=20000, 20000/185.50=107.8 → floor(107.8/100)*100 = 100
    assert allocation_to_shares(20, 100000, 185.50) == 100


def test_allocation_to_shares_zero_pct_returns_zero():
    assert allocation_to_shares(0, 100000, 200.0) == 0


def test_allocation_to_shares_price_too_high_returns_zero():
    # NAV=100k, 1%, price=2000 → target=1000, 1000/2000=0.5 → 0 lots
    assert allocation_to_shares(1, 100000, 2000.0) == 0


# ---- apply_agent_decision integration tests ----

def test_clean_buy_applied_and_nav_entry_added():
    """BUY 40% of NAV at ¥185.50 → 200 shares (200*185.50 = 37100)."""
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
    """SELL with allocation_pct=10 on a 40%-position reduces by delta."""
    # NAV ≈ 100k (50k cash + 200 shares @ 250 = 50k)
    state = {
        **_base_state(),
        "current_cash": 50000,
        "positions": [
            {"ticker": "300750", "name": "宁德时代", "quantity": 200,
             "avg_cost": 250.0, "bought_date": "2026-04-10"},
        ],
    }
    # NAV = 50000 + 200*250 = 100000
    # target = 10% of 100000 = 10000, target_shares = 10000/250 = 40 → floor(40/100)*100 = 0
    # Hmm, 10% of 100k = 10k, 10k/250 = 40 shares → rounds to 0 lots
    # Let's use allocation_pct=20: 20k/250 = 80 shares → 0 lots (still < 100)
    # Use allocation_pct=30: 30k/250 = 120 → 100 shares target. Current=200. Delta=-100.
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
    # target = 30% of 100k / 250 = 120 → floor(120/100)*100 = 100 shares
    # current = 200, delta = -100 → sell 100 shares
    assert new_state["positions"][0]["quantity"] == 100
    assert new_state["current_cash"] == pytest.approx(50000 + 100 * 250.0)


def test_sell_processed_before_buy():
    """SELLs happen first to free cash, then BUYs execute."""
    state = {
        **_base_state(),
        "current_cash": 0,
        "positions": [
            {"ticker": "600519", "name": "贵州茅台", "quantity": 10,
             "avg_cost": 1500.0, "bought_date": "2026-04-10"},
        ],
    }
    # NAV = 0 + 10*1600 = 16000. If BUY ran first with 0 cash, nothing would happen.
    # SELL 600519 @ allocation_pct=0 → sell all 10 shares → get 10*1600=16000 cash.
    # BUY 300750 @ allocation_pct=40 → 40% of 16000 = 6400, 6400/185=34 shares → 0 lots.
    # Hmm, small NAV. Let's test the ordering principle with a more meaningful case.
    # Use larger NAV: state with 1000 shares of 茅台 @ 1600
    state2 = {
        **_base_state(),
        "current_cash": 0,
        "positions": [
            {"ticker": "600519", "name": "贵州茅台", "quantity": 100,
             "avg_cost": 1500.0, "bought_date": "2026-04-10"},
        ],
    }
    # NAV = 100*1600 = 160000
    # SELL 茅台 (allocation_pct=0) → sell 100 shares → 160000 cash
    # BUY 宁德 (allocation_pct=40) → 40% of 160000 = 64000, 64000/200 = 320 shares
    decision = _decision(decisions=[
        {"action": "BUY", "ticker": "300750", "name": "宁德时代",
         "allocation_pct": 40, "reason": {"thesis": "enter"}},
        {"action": "SELL", "ticker": "600519", "name": "贵州茅台",
         "allocation_pct": 0, "reason": {"thesis": "exit"}},
    ])
    new_state, errors = apply_agent_decision(
        decision=decision, state=state2, eval_date="2026-04-17",
        current_prices={"600519": 1600.0, "300750": 200.0},
        valid_tickers={"600519", "300750"},
        benchmark_close=4728.67,
    )
    assert errors == []
    tickers = {p["ticker"] for p in new_state["positions"]}
    assert "600519" not in tickers
    assert "300750" in tickers
    assert new_state["positions"][0]["quantity"] == 320


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
```

Note: Add `import pytest` at the top of the file.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/zijian/Developer/ai-fund-manager && python -m pytest tests/test_apply.py -v 2>&1 | head -40
```

Expected: ImportError for `allocation_to_shares` (not yet defined).

- [ ] **Step 3: Implement the new apply.py**

Replace `src/apply.py` with:

```python
"""Validate + apply a single agent's decision to its portfolio state.

Agents express intent via allocation_pct (0-50 integer per position,
sum of non-SELL decisions <= 100). This module converts percentages to
actual share quantities via allocation_to_shares(), then delegates to
apply_buy / apply_sell. SELLs are processed before BUYs so sell
proceeds are available to fund purchases within the same eval.
"""
from __future__ import annotations

import copy
import math

from src.guardrails import ValidationError, validate_decision
from src.portfolio.performance import append_nav_entry
from src.portfolio.state import apply_buy, apply_sell


def allocation_to_shares(allocation_pct: float, nav: float, price: float) -> int:
    """Convert a target allocation percentage to a round-lot share count.

    Rounds DOWN to the nearest 100-share lot. Returns 0 if the position
    is smaller than one lot at current price.
    """
    if price <= 0:
        return 0
    target_value = nav * (allocation_pct / 100)
    raw_shares = target_value / price
    return int(raw_shares / 100) * 100


def _compute_nav(state: dict, current_prices: dict[str, float]) -> float:
    nav = float(state.get("current_cash", 0))
    for pos in state.get("positions", []):
        price = current_prices.get(pos["ticker"], pos["avg_cost"])
        nav += pos["quantity"] * price
    return nav


def apply_agent_decision(
    *,
    decision: dict,
    state: dict,
    eval_date: str,
    current_prices: dict[str, float],
    valid_tickers: set[str],
    ticker_volumes_yuan: dict[str, float] | None = None,
    benchmark_close: float | None = None,
) -> tuple[dict, list[ValidationError]]:
    """Validate then apply ``decision`` to ``state``.

    Returns ``(new_state, errors)``. On error the original state is
    returned unchanged. On success, all BUY/SELL decisions are applied
    (SELLs first, then BUYs), a nav_history snapshot is appended, and
    ``last_eval_date`` is set.
    """
    errors = validate_decision(
        decision,
        state=state,
        eval_date=eval_date,
        current_prices=current_prices,
        valid_tickers=valid_tickers,
        ticker_volumes_yuan=ticker_volumes_yuan,
    )
    if errors:
        return copy.deepcopy(state), errors

    nav = _compute_nav(state, current_prices)

    existing_qty: dict[str, int] = {
        pos["ticker"]: pos["quantity"]
        for pos in state.get("positions", [])
    }

    working = state
    decisions = decision.get("decisions", [])

    # Process SELLs first so proceeds are available for BUYs
    for d in sorted(decisions, key=lambda x: 0 if x.get("action") == "SELL" else 1):
        action = d.get("action")
        ticker = d.get("ticker", "")
        pct = d.get("allocation_pct", 0)
        price = current_prices.get(ticker)

        if action == "SELL":
            if price is None:
                continue
            target_qty = allocation_to_shares(pct, nav, price)
            current_qty = existing_qty.get(ticker, 0)
            delta = current_qty - target_qty  # shares to sell
            if delta > 0:
                working = apply_sell(
                    working,
                    ticker=ticker,
                    quantity=delta,
                    price=price,
                    eval_date=eval_date,
                    reason_summary=(d.get("reason") or {}).get("thesis", ""),
                )
                existing_qty[ticker] = target_qty

        elif action == "BUY":
            if price is None:
                continue
            target_qty = allocation_to_shares(pct, nav, price)
            current_qty = existing_qty.get(ticker, 0)
            delta = target_qty - current_qty  # shares to buy
            if delta > 0:
                working = apply_buy(
                    working,
                    ticker=ticker,
                    name=d.get("name", ticker),
                    quantity=delta,
                    price=price,
                    eval_date=eval_date,
                    reason_summary=(d.get("reason") or {}).get("thesis", ""),
                )
                existing_qty[ticker] = target_qty

        # HOLD: no state change

    working = append_nav_entry(
        working,
        eval_date=eval_date,
        current_prices=current_prices,
        benchmark_close=benchmark_close,
    )
    working["last_eval_date"] = eval_date
    return working, []
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/zijian/Developer/ai-fund-manager && python -m pytest tests/test_apply.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Run full test suite to catch regressions**

```bash
cd /Users/zijian/Developer/ai-fund-manager && python -m pytest --tb=short 2>&1 | tail -30
```

Fix any failures before committing.

- [ ] **Step 6: Commit**

```bash
cd /Users/zijian/Developer/ai-fund-manager && git add src/apply.py tests/test_apply.py && git commit -m "feat(apply): convert allocation_pct to share delta; process SELLs before BUYs"
```

---

## Task 3: Update `briefing.py` — system prompt + trading constraint section

**Files:**
- Modify: `src/briefing.py`
- Test: `tests/test_briefing.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_briefing.py` (after the existing tests):

```python
# ---- trading constraints block ----

def test_build_agent_briefing_contains_trading_constraints():
    """The briefing must include the trading constraints reminder."""
    briefing = build_agent_briefing(
        shared="## Shared",
        agent_name="claude",
        state={
            "initial_capital": 100000,
            "current_cash": 100000,
            "positions": [],
        },
        prev_decision=None,
        current_prices={},
        benchmark_close=None,
        inception_benchmark_close=None,
    )
    assert "交易约束提醒" in briefing
    assert "allocation_pct" in briefing


def test_trading_constraints_shows_impossible_price_threshold():
    """NAV/100 threshold appears in the constraint block."""
    briefing = build_agent_briefing(
        shared="## Shared",
        agent_name="claude",
        state={
            "initial_capital": 100000,
            "current_cash": 100000,
            "positions": [],
        },
        prev_decision=None,
        current_prices={},
        benchmark_close=None,
        inception_benchmark_close=None,
    )
    # NAV=100000, threshold=1000
    assert "¥1000" in briefing or "¥1,000" in briefing


def test_trading_constraints_flags_expensive_holdings():
    """Holdings requiring >= 10% allocation are flagged individually."""
    briefing = build_agent_briefing(
        shared="## Shared",
        agent_name="claude",
        state={
            "initial_capital": 100000,
            "current_cash": 50000,
            "positions": [
                {"ticker": "300750", "name": "宁德时代",
                 "quantity": 100, "avg_cost": 185.0,
                 "bought_date": "2026-04-10"},
            ],
        },
        prev_decision=None,
        current_prices={"300750": 500.0},  # 500*100/100000*100 = 50% min alloc
        benchmark_close=None,
        inception_benchmark_close=None,
    )
    # min alloc = ceil(500 * 100 / nav * 100) where nav ≈ 100k → 50%
    assert "宁德时代" in briefing or "300750" in briefing
    assert "50%" in briefing or "50 %" in briefing


def test_prev_review_shows_allocation_pct():
    """Previous decision review renders allocation_pct."""
    prev = {
        "eval_date": "2026-04-10",
        "decisions": [
            {"action": "BUY", "ticker": "300750", "name": "宁德时代",
             "allocation_pct": 40, "reason": {}},
        ],
    }
    briefing = build_agent_briefing(
        shared="## Shared",
        agent_name="claude",
        state={
            "initial_capital": 100000,
            "current_cash": 100000,
            "positions": [],
        },
        prev_decision=prev,
        current_prices={"300750": 200.0},
        benchmark_close=None,
        inception_benchmark_close=None,
    )
    assert "40%" in briefing
    assert "300750" in briefing


def test_system_prompt_template_uses_allocation_pct():
    """The system prompt JSON example must reference allocation_pct."""
    assert "allocation_pct" in SYSTEM_PROMPT_TEMPLATE
    assert "quantity" not in SYSTEM_PROMPT_TEMPLATE
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/zijian/Developer/ai-fund-manager && python -m pytest tests/test_briefing.py -v -k "allocation or constraint or prev_review or system_prompt" 2>&1 | tail -20
```

Expected: multiple FAILED.

- [ ] **Step 3: Update `src/briefing.py`**

Make these changes:

**3a. Add `import math` at the top** (after `from __future__ import annotations`):
```python
import math
```

**3b. Replace `SYSTEM_PROMPT_TEMPLATE`** — update `【约束】` block (remove price-calculation guidance, add allocation_pct instructions) and `【输出格式】` block (replace `quantity` with `allocation_pct`):

```python
SYSTEM_PROMPT_TEMPLATE = """你是一位管理10万元人民币A股模拟组合的独立基金经理。你拥有完全的投资决策权。

【你是谁】
你有自己的投资风格和判断力。你不是一个信息聚合器——你是一个有观点的投资者。
你会犯错，但你从错误中学习。你敢于持有与市场共识不同的观点，但只在你有充分
理由时才这样做。你不追涨杀跌，你寻找别人还没看到的机会。

【决策框架】
对于每一个投资决策，你必须产出结构化的思考：

1. THESIS（核心逻辑）：用2-3句话说清楚为什么买/卖/持有这个标的。
2. CATALYST（催化剂）：未来1-6个月内，什么会让市场认识到价值？
3. RISK（风险）：最大的下行风险是什么？
4. SIZING（仓位）：你有多确信？高确信=大仓位。
5. INVALIDATION（失效条件）：什么情况发生意味着thesis错了？

【约束】
- 投资范围：A股股票、ETF。不做期货/期权。
- 持有现金是完全可以接受的决策。
- 考虑T+1交易规则：今天买入的标的今天不能卖出。
- **单只标的最大配置 ≤ 50%（allocation_pct 上限）**。
- 你的推理过程会被公开展示。坦诚、清晰、有个性。不写官话。

【重要：你不负责计算股数】
用 allocation_pct（0–50 的整数）表达你对每个标的的目标仓位比例。
不要自己计算股数、总成本或验证资金是否充足。
一个独立的验证系统会把百分比转换为具体股数并检查可执行性。
如果总配置超过 100% 或违反其他规则，系统会告诉你，你再调整。

示例：
- "对宁德时代非常有 conviction" → allocation_pct: 40
- "小仓位试探性建仓" → allocation_pct: 10
- "清仓" → allocation_pct: 0
- "不操作的标的" → 不需要出现在 decisions 里

【输出格式】
你必须以JSON格式输出决策。结构如下：
{{
  "eval_date": "YYYY-MM-DD",
  "market_view": "对当前市场的判断（2-3段文字）",
  "decisions": [
    {{
      "action": "BUY",
      "ticker": "300750",
      "name": "宁德时代",
      "allocation_pct": 40,
      "reason": {{
        "thesis": "...",
        "catalyst": "...",
        "risk": "...",
        "invalidation": "..."
      }}
    }},
    {{
      "action": "SELL",
      "ticker": "600036",
      "name": "招商银行",
      "allocation_pct": 0,
      "reason": {{
        "thesis": "thesis已失效，清仓",
        "invalidation": "已触发"
      }}
    }}
  ],
  "watchlist_updates": [
    {{"ticker": "300308", "name": "中际旭创", "note": "等回调再看"}}
  ],
  "reflection": "对上期决策的回顾（基于简报中的上期回顾数据）",
  "note_to_audience": "写给观众的一段话，坦诚、有个性"
}}

注意：eval_date 必须与简报日期一致。不操作的持仓不需要出现在 decisions 里。

【记忆】
{memory_content}

【当前持仓与业绩】
{portfolio_state}

【市场简报】
{market_briefing}

现在请做出本期投资决策。
"""
```

**3c. Add `_render_trading_constraints` helper** (insert before `build_shared_briefing`):

```python
def _render_trading_constraints(
    nav: float, positions: list[dict], current_prices: dict[str, float]
) -> str:
    max_price = nav / 100
    lines = [
        "【交易约束提醒】",
        f"组合规模：¥{nav:,.0f}。A股最小交易单位100股。",
        f"股价超过¥{max_price:.0f}的标的无法买入（任何 allocation_pct 都不够买一手）。",
        "买入100股（一手）股价为P的标的所需最小 allocation_pct = ⌈P × 100 ÷ NAV × 100⌉%。",
    ]
    expensive = []
    for pos in positions:
        price = current_prices.get(pos["ticker"])
        if price and price > 0:
            min_alloc = math.ceil(price * 100 / nav * 100)
            if min_alloc >= 10:
                name = pos.get("name", pos["ticker"])
                expensive.append(
                    f"  - {name}({pos['ticker']}) @¥{price:.2f} → 最小 allocation_pct = {min_alloc}%"
                )
    if expensive:
        lines.append("当前持仓需注意：")
        lines.extend(expensive)
    return "\n".join(lines)
```

**3d. Update `_render_prev_review`** — replace `qty = d.get("quantity", "?")` and surrounding line:

```python
def _render_prev_review(
    prev_decision: dict, current_prices: dict[str, float]
) -> str:
    lines = ["## 上期回顾"]
    eval_date = prev_decision.get("eval_date", "?")
    lines.append(f"上期({eval_date}) 你的操作：")
    decisions = prev_decision.get("decisions", []) or []
    if not decisions:
        lines.append("- 无操作")
        return "\n".join(lines)
    for d in decisions:
        action = d.get("action", "?")
        ticker = d.get("ticker", "")
        name = d.get("name", "")
        if action == "HOLD":
            lines.append(f"- HOLD")
            continue
        pct = d.get("allocation_pct")
        pct_str = f" allocation_pct={pct}%" if pct is not None else ""
        line = f"- {action} {name}({ticker}){pct_str}"
        cur = current_prices.get(ticker)
        if cur is not None:
            line += f" → 现价 ¥{cur:.2f}"
        lines.append(line)
    lines.append("（请基于结果反思你的判断。）")
    return "\n".join(lines)
```

**3e. Update `build_agent_briefing`** — add the constraint section. After the section that adds `f"组合净值：..."`, add:

```python
    sections.extend([
        "",
        _render_trading_constraints(nav, positions, current_prices),
    ])
```

(Insert this before the `if prev_decision:` block.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/zijian/Developer/ai-fund-manager && python -m pytest tests/test_briefing.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/zijian/Developer/ai-fund-manager && git add src/briefing.py tests/test_briefing.py && git commit -m "feat(briefing): allocation_pct prompt + trading constraints section"
```

---

## Task 4: Update `renderer.py` — show allocation_pct + computed shares

**Files:**
- Modify: `src/output/renderer.py`
- Test: `tests/output/test_renderer.py`

- [ ] **Step 1: Write failing tests**

In `tests/output/test_renderer.py`, update `_decision_sample()` to use `allocation_pct` instead of `quantity`, and add a test for the allocation table. Also add `nav` param to `render_agent_report` calls.

Replace the existing `_decision_sample()`:
```python
def _decision_sample() -> dict:
    return {
        "eval_date": "2026-04-17",
        "market_view": "当前市场震荡，结构性行情为主。新能源和医药有轮动机会。",
        "decisions": [
            {
                "action": "BUY",
                "ticker": "300750",
                "name": "宁德时代",
                "allocation_pct": 40,
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
```

Add `nav=100000` to every existing `render_agent_report(...)` call in the test file.

Add a new test:
```python
def test_report_shows_allocation_pct_and_computed_shares():
    out = render_agent_report(
        display_name="Claude",
        decision=_decision_sample(),
        state=_state_sample(),
        current_prices={"300750": 192.30},
        nav=100000,
        benchmark_close=4728.67,
        inception_benchmark_close=4700.0,
    )
    # allocation_pct should appear
    assert "40%" in out
    # computed shares should appear (40% of 100k / 192.30 = 207.9 → 200 shares)
    assert "200股" in out or "200 股" in out


def test_report_does_not_contain_quantity_field():
    out = render_agent_report(
        display_name="Claude",
        decision=_decision_sample(),
        state=_state_sample(),
        current_prices={"300750": 192.30},
        nav=100000,
        benchmark_close=4728.67,
        inception_benchmark_close=4700.0,
    )
    # "quantity" key name should not leak into the report
    assert "quantity" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/zijian/Developer/ai-fund-manager && python -m pytest tests/output/test_renderer.py -v 2>&1 | tail -20
```

Expected: FAILED (missing `nav` param, `quantity` referenced in `_bullet_decisions`).

- [ ] **Step 3: Update `src/output/renderer.py`**

**3a. Add `import math` at the top.**

**3b. Replace `_bullet_decisions`** to show allocation_pct + computed shares table:

```python
def _bullet_decisions(
    decisions: list[dict],
    *,
    action: str,
    nav: float,
    current_prices: dict[str, float],
) -> str:
    items = [d for d in decisions if d.get("action") == action]
    if not items:
        return "无"
    lines = []
    for d in items:
        ticker = d.get("ticker", "")
        name = d.get("name", "")
        pct = d.get("allocation_pct")
        price = current_prices.get(ticker)
        header = f"- {name}" + (f" ({ticker})" if ticker else "")
        if pct is not None:
            header += f"  目标 {pct}%"
            if price and price > 0 and nav > 0:
                shares = int(nav * pct / 100 / price / 100) * 100
                cost = shares * price
                actual_pct = cost / nav * 100 if nav else 0
                header += f" → {shares}股 / ¥{cost:,.0f} / 实际{actual_pct:.1f}%"
        lines.append(header)
        reason = d.get("reason") or {}
        for label, key in (
            ("Thesis", "thesis"),
            ("Catalyst", "catalyst"),
            ("Risk", "risk"),
            ("Invalidation", "invalidation"),
        ):
            val = reason.get(key)
            if val:
                lines.append(f"  - **{label}**: {val}")
    return "\n".join(lines)
```

**3c. Update `render_agent_report` signature** — add `nav: float` parameter:

```python
def render_agent_report(
    *,
    display_name: str,
    decision: dict,
    state: dict,
    current_prices: dict[str, float],
    nav: float,
    benchmark_close: float | None,
    inception_benchmark_close: float | None,
) -> str:
```

**3d. Update the calls to `_bullet_decisions`** inside `render_agent_report`:

```python
        sections.append(f"### 买入 ({len(buys)})")
        sections.append(_bullet_decisions(decisions, action="BUY", nav=nav, current_prices=current_prices))
        sections.append("")
        sections.append(f"### 卖出 ({len(sells)})")
        sections.append(_bullet_decisions(decisions, action="SELL", nav=nav, current_prices=current_prices))
        sections.append("")
        if holds:
            sections.append(f"### 持有 ({len(holds)})")
            sections.append(_bullet_decisions(decisions, action="HOLD", nav=nav, current_prices=current_prices))
```

Note: `nav` in `render_agent_report` is now a parameter; remove the internal `nav` computation from positions (keep `cum_return_pct` calculation using the same `nav` value passed in, or recompute — keep it simple: the caller passes in the pre-computed nav).

Actually, the internal `nav` computation block:
```python
    nav = cash
    for pos in positions:
        price = current_prices.get(pos["ticker"], pos["avg_cost"])
        nav += pos["quantity"] * price
```
should be removed since `nav` is now a parameter. But `cash` and `cum_return_pct` still need `nav`. Update:
```python
    cum_return_pct = (nav - initial) / initial * 100 if initial else 0.0
```
(Remove the `nav = cash + ...` block; `nav` comes from the parameter.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/zijian/Developer/ai-fund-manager && python -m pytest tests/output/test_renderer.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/zijian/Developer/ai-fund-manager && python -m pytest --tb=short 2>&1 | tail -20
```

Fix any failures (e.g., `comparison.py` or skill code calling `render_agent_report` without `nav`).

- [ ] **Step 6: Commit**

```bash
cd /Users/zijian/Developer/ai-fund-manager && git add src/output/renderer.py tests/output/test_renderer.py && git commit -m "feat(renderer): show allocation_pct target + computed shares in report"
```

---

## Task 5: Update `CLAUDE.md` — schema docs

**Files:**
- Modify: `CLAUDE.md`

No tests — this is documentation.

- [ ] **Step 1: Update Agent output format schema**

In `CLAUDE.md`, find the JSON schema block under "## Agent输出格式" and replace it with:

```json
{
  "eval_date": "2026-04-17",
  "market_view": "对当前市场的判断",
  "decisions": [
    {
      "action": "BUY/SELL/HOLD",
      "ticker": "300750",
      "name": "宁德时代",
      "allocation_pct": 40,
      "reason": {
        "thesis": "...",
        "catalyst": "...",
        "risk": "...",
        "invalidation": "..."
      }
    }
  ],
  "watchlist_updates": [
    {"ticker": "300308", "name": "中际旭创", "note": "等回调再看"}
  ],
  "reflection": "对上期决策的回顾",
  "note_to_audience": "写给观众的一段话"
}
```

- [ ] **Step 2: Add `allocation_pct` semantics section**

After the JSON schema, add:

```markdown
### allocation_pct 语义

- `allocation_pct` 表示该标的占**组合总NAV**的目标百分比（0-50整数）
- BUY新标的：`allocation_pct: 40` = 把组合的40%配置到该标的
- 加仓：现有15%仓位，`allocation_pct: 30` = 加到30%
- 减仓：现有30%仓位，`allocation_pct: 15` = 减到15%
- 清仓：`allocation_pct: 0`（SELL + 0）
- 不操作：不出现在decisions里（或 `action: "HOLD"`，allocation_pct可省略）
- 所有非SELL decisions的allocation_pct之和不得超过100%

apply.py 转换：`target_shares = floor(NAV × pct/100 / price / 100) × 100`
delta = target_shares − current_shares → BUY delta if positive, SELL if negative.
SELLs are processed before BUYs within each eval.
```

- [ ] **Step 3: Update Guardrails table**

In the Guardrails table, replace:
```
| 单只最大仓位 | 50% |
| 最小交易单位 | 100股 |
```
with:
```
| 单只最大配置 | allocation_pct ≤ 50 |
| 总配置上限 | 非SELL decisions之和 ≤ 100% |
```
Remove the `最小交易单位 | 100股` row (now handled by apply.py rounding, not guardrails).

- [ ] **Step 4: Commit**

```bash
cd /Users/zijian/Developer/ai-fund-manager && git add CLAUDE.md && git commit -m "docs(CLAUDE.md): update schema to allocation_pct, add semantics + guardrails"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Covered by |
|---|---|
| Agent outputs `allocation_pct` instead of `quantity` | Tasks 3, 4, 5 |
| `allocation_to_shares(pct, nav, price)` helper | Task 2 |
| `compute_trade` (delta logic) | Task 2 (inlined in `apply_agent_decision`) |
| Guardrails: each pct 0-50, sum ≤ 100 | Task 1 |
| Guardrails: remove lot_size / qty-based max_single_position | Task 1 |
| SELLs before BUYs | Task 2 |
| Briefing: "你不负责计算" block | Task 3 |
| Briefing: trading constraint reminder with NAV/100 threshold | Task 3 |
| Briefing: flag expensive holdings (min alloc ≥ 10%) | Task 3 |
| Briefing: `_render_prev_review` shows allocation_pct | Task 3 |
| Renderer: show target %, computed shares, actual cost, actual % | Task 4 |
| CLAUDE.md schema updated | Task 5 |
| No backward compatibility with old `quantity` format | All tasks (clean cut) |

**Placeholder scan:** No TBDs, TODOs, or vague steps found.

**Type consistency:**
- `allocation_to_shares(allocation_pct: float, nav: float, price: float) -> int` defined in Task 2, referenced in Task 2 tests — consistent.
- `render_agent_report(..., nav: float, ...)` defined in Task 4, tested in Task 4 — consistent.
- `_bullet_decisions(..., nav: float, current_prices: dict[str, float])` defined in Task 4, called in Task 4 — consistent.
- `_render_trading_constraints(nav, positions, current_prices)` defined in Task 3, called in Task 3 — consistent.

**One gap identified:** `src/output/comparison.py` may call `render_agent_report` without `nav`. Check and fix in Task 4 Step 5 (full suite run catches this).
