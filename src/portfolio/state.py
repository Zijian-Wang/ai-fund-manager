"""Per-agent portfolio state: I/O and trade application.

Each agent owns ``agents/<name>/portfolio_state.json``. The file is
initialized from ``memory_template/`` on first run and is the single
source of truth for the agent's history. All writes are atomic
(write-to-temp-then-rename) to protect against crash corruption.

Trade application (``apply_buy`` / ``apply_sell``) is a pure function —
returns a new state dict rather than mutating the input. This makes it
safe to snapshot state before guardrail validation and discard on reject.
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from src.data.cache import read_json, write_json_atomic


def _state_path(agent_name: str, agents_root: Path) -> Path:
    return Path(agents_root) / agent_name / "portfolio_state.json"


def init_agent_state(
    *,
    agent_name: str,
    agents_root: Path,
    template_root: Path,
    inception_date: str,
) -> dict:
    """Initialize ``agents/<name>/`` from ``memory_template/`` if absent.

    Idempotent: if the agent's state file already exists, returns it
    unchanged. The ``inception_date`` is only written on first init.
    """
    agent_dir = Path(agents_root) / agent_name
    state_path = _state_path(agent_name, agents_root)
    if state_path.exists():
        return load_state(agent_name=agent_name, agents_root=agents_root)

    agent_dir.mkdir(parents=True, exist_ok=True)
    template_root = Path(template_root)
    for item in template_root.iterdir():
        dest = agent_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)

    state = read_json(state_path)
    assert isinstance(state, dict), "memory_template/portfolio_state.json is malformed"
    state["agent"] = agent_name
    state["inception_date"] = inception_date
    write_json_atomic(state_path, state)
    return state


def load_state(*, agent_name: str, agents_root: Path) -> dict:
    state = read_json(_state_path(agent_name, agents_root))
    if state is None:
        raise FileNotFoundError(
            f"No state for agent {agent_name!r} under {agents_root}"
        )
    return state


def save_state(*, agent_name: str, state: dict, agents_root: Path) -> None:
    write_json_atomic(_state_path(agent_name, agents_root), state)


def apply_buy(
    state: dict,
    *,
    ticker: str,
    name: str,
    quantity: int,
    price: float,
    eval_date: str,
    reason_summary: str,
) -> dict:
    """Return a new state with the BUY applied.

    If the position already exists, ``avg_cost`` is volume-weighted and
    ``bought_date`` advances to ``eval_date`` (conservative for T+1).
    """
    new_state = copy.deepcopy(state)
    cost = quantity * price
    new_state["current_cash"] = new_state["current_cash"] - cost

    for pos in new_state["positions"]:
        if pos["ticker"] == ticker:
            old_qty = pos["quantity"]
            old_cost = pos["avg_cost"]
            total_qty = old_qty + quantity
            pos["avg_cost"] = round(
                (old_qty * old_cost + quantity * price) / total_qty, 4
            )
            pos["quantity"] = total_qty
            pos["bought_date"] = eval_date
            break
    else:
        new_state["positions"].append(
            {
                "ticker": ticker,
                "name": name,
                "quantity": quantity,
                "avg_cost": price,
                "bought_date": eval_date,
            }
        )

    new_state["trade_history"].append(
        {
            "eval_date": eval_date,
            "action": "BUY",
            "ticker": ticker,
            "name": name,
            "quantity": quantity,
            "price": price,
            "reason_summary": reason_summary,
        }
    )
    return new_state


def apply_sell(
    state: dict,
    *,
    ticker: str,
    quantity: int,
    price: float,
    eval_date: str,
    reason_summary: str,
) -> dict:
    """Return a new state with the SELL applied.

    Raises ``ValueError`` if the position doesn't exist or sell quantity
    exceeds the held quantity.
    """
    new_state = copy.deepcopy(state)

    target = None
    for pos in new_state["positions"]:
        if pos["ticker"] == ticker:
            target = pos
            break
    if target is None:
        raise ValueError(f"no position for ticker {ticker!r}")
    if quantity > target["quantity"]:
        raise ValueError(
            f"sell quantity {quantity} exceeds held {target['quantity']} for {ticker}"
        )

    target["quantity"] -= quantity
    name = target["name"]
    if target["quantity"] == 0:
        new_state["positions"].remove(target)

    new_state["current_cash"] = new_state["current_cash"] + quantity * price
    new_state["trade_history"].append(
        {
            "eval_date": eval_date,
            "action": "SELL",
            "ticker": ticker,
            "name": name,
            "quantity": quantity,
            "price": price,
            "reason_summary": reason_summary,
        }
    )
    return new_state


def _trade_journal_path(
    agent_name: str, eval_date: str, agents_root: Path
) -> Path:
    return Path(agents_root) / agent_name / "trade_journal" / f"{eval_date}.json"


def save_trade_journal(
    *,
    agent_name: str,
    eval_date: str,
    decision: dict,
    agents_root: Path,
) -> None:
    """Write the raw decision to ``agents/<name>/trade_journal/{eval_date}.json``.

    Creates the trade_journal/ dir if it doesn't exist. Atomic write.
    """
    path = _trade_journal_path(agent_name, eval_date, agents_root)
    write_json_atomic(path, decision)


def load_prev_decision(
    *,
    state: dict,
    agent_name: str,
    agents_root: Path,
) -> dict | None:
    """Return the agent's previous decision (keyed by state['last_eval_date']).

    Returns None on first eval (last_eval_date is None) or if the file
    doesn't exist (e.g. the prior eval errored before save).
    """
    last = state.get("last_eval_date")
    if not last:
        return None
    return read_json(_trade_journal_path(agent_name, last, agents_root))
