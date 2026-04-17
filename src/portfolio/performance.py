"""Portfolio performance metrics and track-record rebuild.

Per spec, ``track_record/nav_history.json`` is a derived file — it is
rebuilt from every agent's ``portfolio_state.json`` after each eval and
never edited by hand. Per-agent state is the single source of truth.
"""
from __future__ import annotations

import copy
from pathlib import Path

from src.data.cache import write_json_atomic, read_json


BENCHMARK_INDEX = "000300.SH"


def compute_nav(state: dict, *, current_prices: dict[str, float]) -> float:
    """Cash + market value of positions. Falls back to ``avg_cost`` when
    a ticker isn't in ``current_prices`` (conservative)."""
    total = float(state.get("current_cash", 0))
    for pos in state.get("positions", []):
        price = current_prices.get(pos["ticker"], pos["avg_cost"])
        total += pos["quantity"] * price
    return total


def compute_cumulative_return_pct(
    *, current_nav: float, initial_capital: float
) -> float:
    if initial_capital == 0:
        return 0.0
    return (current_nav - initial_capital) / initial_capital


def compute_cash_pct(state: dict, *, current_nav: float) -> float:
    if current_nav == 0:
        return 1.0
    return state.get("current_cash", 0) / current_nav


def position_count(state: dict) -> int:
    return len(state.get("positions", []))


def append_nav_entry(
    state: dict,
    *,
    eval_date: str,
    current_prices: dict[str, float],
    benchmark_close: float | None,
) -> dict:
    """Return a new state with a NAV entry appended for ``eval_date``.

    All derived fields are computed at write time so the entry is
    self-contained (no re-derivation needed downstream).
    """
    new_state = copy.deepcopy(state)
    nav = compute_nav(new_state, current_prices=current_prices)
    entry = {
        "date": eval_date,
        "nav": nav,
        "cash_pct": compute_cash_pct(new_state, current_nav=nav),
        "position_count": position_count(new_state),
        "benchmark_close": benchmark_close,
        "cumulative_return_pct": compute_cumulative_return_pct(
            current_nav=nav, initial_capital=new_state.get("initial_capital", 0)
        ),
    }
    new_state.setdefault("nav_history", []).append(entry)
    return new_state


def rebuild_track_record(*, agents_root: Path, output_path: Path) -> None:
    """Aggregate all agents' nav_history into a single merged file.

    Output shape (per spec):
        [
          {
            "date": "YYYY-MM-DD",
            "benchmark": {"index": "000300.SH", "close": float|null},
            "agents": {
              "claude": {"nav": ..., "cumulative_return_pct": ...,
                         "cash_pct": ..., "position_count": ...},
              ...
            }
          },
          ...
        ]
    """
    agents_root = Path(agents_root)
    by_date: dict[str, dict] = {}

    if agents_root.exists():
        for agent_dir in sorted(agents_root.iterdir()):
            if not agent_dir.is_dir():
                continue
            state_path = agent_dir / "portfolio_state.json"
            state = read_json(state_path)
            if state is None:
                continue
            agent_name = state.get("agent") or agent_dir.name
            for entry in state.get("nav_history", []):
                date = entry["date"]
                bucket = by_date.setdefault(
                    date,
                    {
                        "date": date,
                        "benchmark": {
                            "index": BENCHMARK_INDEX,
                            "close": entry.get("benchmark_close"),
                        },
                        "agents": {},
                    },
                )
                # Prefer a non-null benchmark_close if any agent has it
                if (
                    bucket["benchmark"]["close"] is None
                    and entry.get("benchmark_close") is not None
                ):
                    bucket["benchmark"]["close"] = entry["benchmark_close"]
                bucket["agents"][agent_name] = {
                    "nav": entry["nav"],
                    "cumulative_return_pct": entry.get("cumulative_return_pct", 0.0),
                    "cash_pct": entry.get("cash_pct", 1.0),
                    "position_count": entry.get("position_count", 0),
                }

    sorted_rows = [by_date[d] for d in sorted(by_date.keys())]
    write_json_atomic(output_path, sorted_rows)
