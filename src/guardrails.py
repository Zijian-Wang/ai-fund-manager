"""Shared guardrail validation.

Every agent's decision (Claude's subagent output and each API agent's
response) runs through the same ``validate_decision`` before state is
updated. An empty error list means the decision is clean; a non-empty
list means the orchestrator logs the errors and skips that agent's
application for the eval.

Rules implemented (per spec):
- ``eval_date``         decision's eval_date must match current
- ``idempotency``       agent's last_eval_date != current
- ``ticker``            ticker exists in valid_tickers (for BUY/SELL)
- ``lot_size``          quantity is a multiple of 100 (for BUY/SELL)
- ``t_plus_1``          cannot SELL a position bought today
- ``max_trades``        BUY+SELL count <= 10
- ``max_single_position`` post-buy position value <= 50% of NAV
- ``circuit_breaker``   portfolio cumulative_return_pct > -15%
- ``min_volume``        stock's daily ¥-volume >= ¥5M (when data available)
- ``schema``            decision dict has required top-level keys
"""
from __future__ import annotations

from dataclasses import dataclass


MAX_SINGLE_POSITION_PCT = 0.50
CIRCUIT_BREAKER_CUMRETURN_PCT = -0.15
MAX_TRADES_PER_DAY = 10
ROUND_LOT = 100
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
        return errors  # can't check further without basic structure
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

    # Compute pre-trade NAV for position-size checks
    pre_trade_nav = float(state.get("current_cash", 0))
    for pos in state.get("positions", []):
        price = current_prices.get(pos["ticker"], pos["avg_cost"])
        pre_trade_nav += pos["quantity"] * price

    # Map ticker -> existing quantity for buy accumulation
    existing_qty: dict[str, int] = {
        pos["ticker"]: pos["quantity"]
        for pos in state.get("positions", [])
    }
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
        quantity = d.get("quantity", 0)

        # ticker
        if ticker not in valid_tickers:
            errors.append(ValidationError(
                rule="ticker",
                message=f"unknown ticker {ticker!r} at decisions[{idx}]",
            ))

        # lot size
        if not isinstance(quantity, int) or quantity <= 0 or quantity % ROUND_LOT != 0:
            errors.append(ValidationError(
                rule="lot_size",
                message=(
                    f"quantity {quantity!r} at decisions[{idx}] must be a "
                    f"positive multiple of {ROUND_LOT}"
                ),
            ))

        # T+1
        if action == "SELL":
            if bought_dates.get(ticker) == eval_date:
                errors.append(ValidationError(
                    rule="t_plus_1",
                    message=f"cannot SELL {ticker} — bought today ({eval_date})",
                ))

        # max single position (check after applying all BUYs of this ticker)
        if action == "BUY":
            price = current_prices.get(ticker)
            if price is not None and isinstance(quantity, int):
                total_qty = existing_qty.get(ticker, 0) + quantity
                post_position_value = total_qty * price
                if post_position_value > MAX_SINGLE_POSITION_PCT * pre_trade_nav:
                    errors.append(ValidationError(
                        rule="max_single_position",
                        message=(
                            f"post-buy {ticker} position ¥{post_position_value:,.0f} "
                            f"> {MAX_SINGLE_POSITION_PCT:.0%} of NAV ¥{pre_trade_nav:,.0f}"
                        ),
                    ))
                existing_qty[ticker] = total_qty

            # min volume (only when we have the data)
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
