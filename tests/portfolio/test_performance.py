"""Tests for portfolio performance metrics + track record rebuild."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.portfolio.performance import (
    append_nav_entry,
    compute_cash_pct,
    compute_cumulative_return_pct,
    compute_nav,
    position_count,
    rebuild_track_record,
)


# ---- compute_nav ----

def test_compute_nav_is_cash_when_no_positions():
    state = {"current_cash": 100000, "positions": []}
    assert compute_nav(state, current_prices={}) == 100000


def test_compute_nav_adds_market_value_of_each_position():
    state = {
        "current_cash": 10000,
        "positions": [
            {"ticker": "300750", "quantity": 100, "avg_cost": 185.00},
            {"ticker": "600519", "quantity": 10, "avg_cost": 1500.00},
        ],
    }
    prices = {"300750": 200.00, "600519": 1600.00}
    # 10000 + 100*200 + 10*1600 = 10000 + 20000 + 16000 = 46000
    assert compute_nav(state, current_prices=prices) == 46000


def test_compute_nav_uses_avg_cost_when_price_missing():
    """If we can't price a position, fall back to avg_cost (conservative)."""
    state = {
        "current_cash": 10000,
        "positions": [
            {"ticker": "300750", "quantity": 100, "avg_cost": 185.00},
        ],
    }
    assert compute_nav(state, current_prices={}) == 10000 + 100 * 185.00


# ---- simple metrics ----

def test_compute_cumulative_return_pct_positive():
    assert compute_cumulative_return_pct(
        current_nav=105000, initial_capital=100000
    ) == pytest.approx(0.05)


def test_compute_cumulative_return_pct_negative():
    assert compute_cumulative_return_pct(
        current_nav=95000, initial_capital=100000
    ) == pytest.approx(-0.05)


def test_compute_cumulative_return_pct_zero_initial_is_safe():
    assert compute_cumulative_return_pct(
        current_nav=0, initial_capital=0
    ) == 0.0


def test_compute_cash_pct():
    state = {"current_cash": 50000}
    assert compute_cash_pct(state, current_nav=100000) == 0.5


def test_compute_cash_pct_zero_nav_is_safe():
    state = {"current_cash": 0}
    assert compute_cash_pct(state, current_nav=0) == 1.0


def test_position_count_is_length_of_positions_list():
    assert position_count({"positions": []}) == 0
    assert position_count({"positions": [{"ticker": "a"}, {"ticker": "b"}]}) == 2


# ---- append_nav_entry ----

def test_append_nav_entry_computes_all_fields():
    state = {
        "initial_capital": 100000,
        "current_cash": 50000,
        "positions": [
            {"ticker": "300750", "quantity": 100, "avg_cost": 185.00},
        ],
        "nav_history": [],
    }
    prices = {"300750": 200.00}
    new_state = append_nav_entry(
        state,
        eval_date="2026-04-17",
        current_prices=prices,
        benchmark_close=3845.20,
    )
    assert len(new_state["nav_history"]) == 1
    entry = new_state["nav_history"][0]
    assert entry["date"] == "2026-04-17"
    assert entry["nav"] == 70000  # 50000 + 100*200
    assert entry["cash_pct"] == pytest.approx(50000 / 70000)
    assert entry["position_count"] == 1
    assert entry["benchmark_close"] == 3845.20
    assert entry["cumulative_return_pct"] == pytest.approx(-0.30)


def test_append_nav_entry_does_not_mutate_input():
    state = {
        "initial_capital": 100000,
        "current_cash": 100000,
        "positions": [],
        "nav_history": [],
    }
    append_nav_entry(
        state, eval_date="2026-04-17", current_prices={}, benchmark_close=3800.0
    )
    assert state["nav_history"] == []


# ---- rebuild_track_record ----

def test_rebuild_track_record_merges_all_agents(tmp_path: Path):
    agents = tmp_path / "agents"
    (agents / "claude").mkdir(parents=True)
    (agents / "gemini").mkdir(parents=True)
    (agents / "claude" / "portfolio_state.json").write_text(
        json.dumps(
            {
                "agent": "claude",
                "initial_capital": 100000,
                "nav_history": [
                    {"date": "2026-04-17", "nav": 100500,
                     "cash_pct": 0.75, "position_count": 2,
                     "benchmark_close": 3845.20, "cumulative_return_pct": 0.005},
                    {"date": "2026-04-18", "nav": 100700,
                     "cash_pct": 0.70, "position_count": 2,
                     "benchmark_close": 3860.10, "cumulative_return_pct": 0.007},
                ],
            }
        ),
        encoding="utf-8",
    )
    (agents / "gemini" / "portfolio_state.json").write_text(
        json.dumps(
            {
                "agent": "gemini",
                "initial_capital": 100000,
                "nav_history": [
                    {"date": "2026-04-17", "nav": 99800,
                     "cash_pct": 0.60, "position_count": 3,
                     "benchmark_close": 3845.20, "cumulative_return_pct": -0.002},
                ],
            }
        ),
        encoding="utf-8",
    )
    out_path = tmp_path / "track_record" / "nav_history.json"

    rebuild_track_record(agents_root=agents, output_path=out_path)

    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    # 2 distinct dates
    assert len(payload) == 2
    # Sorted by date ascending
    assert payload[0]["date"] == "2026-04-17"
    assert payload[1]["date"] == "2026-04-18"
    # 04-17 has both agents
    assert set(payload[0]["agents"].keys()) == {"claude", "gemini"}
    assert payload[0]["agents"]["claude"]["nav"] == 100500
    # 04-18 has only claude
    assert set(payload[1]["agents"].keys()) == {"claude"}
    # Benchmark close captured per-date
    assert payload[0]["benchmark"]["close"] == 3845.20
    assert payload[0]["benchmark"]["index"] == "000300.SH"


def test_rebuild_track_record_handles_missing_benchmark(tmp_path: Path):
    agents = tmp_path / "agents"
    (agents / "gemini").mkdir(parents=True)
    (agents / "gemini" / "portfolio_state.json").write_text(
        json.dumps(
            {
                "agent": "gemini",
                "initial_capital": 100000,
                "nav_history": [
                    {"date": "2026-04-17", "nav": 100000,
                     "cash_pct": 1.0, "position_count": 0,
                     "benchmark_close": None, "cumulative_return_pct": 0.0},
                ],
            }
        ),
        encoding="utf-8",
    )
    out_path = tmp_path / "track_record" / "nav_history.json"

    rebuild_track_record(agents_root=agents, output_path=out_path)
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload[0]["benchmark"]["close"] is None
