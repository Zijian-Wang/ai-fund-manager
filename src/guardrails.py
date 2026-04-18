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
