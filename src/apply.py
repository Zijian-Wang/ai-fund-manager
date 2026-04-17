"""Validate + apply a single agent's decision to its portfolio state.

Composes guardrails + apply_buy/apply_sell + append_nav_entry into one
pure function used by the orchestrator (both Claude's isolated subagent
path and the manual webchat ingestion path). Caller is responsible for
I/O (save_state on success, save_trade_journal always for audit).
"""
from __future__ import annotations

import copy

from src.guardrails import ValidationError, validate_decision
from src.portfolio.performance import append_nav_entry
from src.portfolio.state import apply_buy, apply_sell


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

    Returns ``(new_state, errors)``. If ``errors`` is non-empty the
    original state is returned unchanged — caller should log + skip
    applying but still save the raw decision to ``trade_journal`` for
    the record. If ``errors`` is empty, every BUY/SELL is applied, a
    nav_history snapshot is appended (even for HOLD-only decisions, so
    the track record has a checkpoint), and ``last_eval_date`` is set.
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

    working = state
    for d in decision.get("decisions", []):
        action = d.get("action")
        if action == "BUY":
            working = apply_buy(
                working,
                ticker=d["ticker"], name=d["name"],
                quantity=d["quantity"],
                price=current_prices[d["ticker"]],
                eval_date=eval_date,
                reason_summary=(d.get("reason") or {}).get("thesis", ""),
            )
        elif action == "SELL":
            working = apply_sell(
                working,
                ticker=d["ticker"], quantity=d["quantity"],
                price=current_prices[d["ticker"]],
                eval_date=eval_date,
                reason_summary=(d.get("reason") or {}).get("thesis", ""),
            )
        # HOLD: no state change

    working = append_nav_entry(
        working,
        eval_date=eval_date,
        current_prices=current_prices,
        benchmark_close=benchmark_close,
    )
    # append_nav_entry deepcopies — safe to mutate
    working["last_eval_date"] = eval_date
    return working, []
