"""Validate + apply a single agent's decision to its portfolio state.

Agents express intent via allocation_pct (0-50 integer per position,
sum of non-SELL decisions <= 100). This module converts percentages to
actual share quantities via allocation_to_shares(), then delegates to
apply_buy / apply_sell. SELLs are processed before BUYs so sell
proceeds are available to fund purchases within the same eval.
"""
from __future__ import annotations

import copy

from src.guardrails import ValidationError, validate_decision
from src.portfolio.performance import append_nav_entry, compute_nav
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

    nav = compute_nav(state, current_prices=current_prices)

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

    # Defense-in-depth: the cash_budget guardrail should have caught this,
    # but if rounding or a missing price slipped a BUY past validation, bail
    # out before persisting a negative balance.
    if working.get("current_cash", 0) < -0.01:
        return copy.deepcopy(state), [ValidationError(
            rule="cash_budget",
            message=(
                f"cash went negative to ¥{working['current_cash']:,.0f} after "
                "applying trades — decision rejected"
            ),
        )]

    working = append_nav_entry(
        working,
        eval_date=eval_date,
        current_prices=current_prices,
        benchmark_close=benchmark_close,
    )
    working["last_eval_date"] = eval_date
    return working, []
