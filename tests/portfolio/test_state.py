"""Tests for per-agent portfolio state I/O + trade application."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.portfolio.state import (
    apply_buy,
    apply_sell,
    init_agent_state,
    load_state,
    save_state,
)


@pytest.fixture
def template_root(tmp_path: Path) -> Path:
    template = tmp_path / "memory_template"
    template.mkdir()
    (template / "portfolio_state.json").write_text(
        json.dumps(
            {
                "agent": None,
                "inception_date": None,
                "initial_capital": 100000,
                "current_cash": 100000,
                "last_eval_date": None,
                "positions": [],
                "trade_history": [],
                "nav_history": [],
            }
        ),
        encoding="utf-8",
    )
    return template


@pytest.fixture
def agents_root(tmp_path: Path) -> Path:
    d = tmp_path / "agents"
    d.mkdir()
    return d


# ---- init ----

def test_init_agent_state_creates_dir_with_template(
    template_root: Path, agents_root: Path
) -> None:
    state = init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-17",
    )
    assert state["agent"] == "gemini"
    assert state["inception_date"] == "2026-04-17"
    assert state["initial_capital"] == 100000
    assert state["current_cash"] == 100000

    on_disk = json.loads(
        (agents_root / "gemini" / "portfolio_state.json").read_text(encoding="utf-8")
    )
    assert on_disk["agent"] == "gemini"


def test_init_agent_state_is_idempotent(
    template_root: Path, agents_root: Path
) -> None:
    # First init sets inception_date; second init must NOT overwrite it
    s1 = init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-17",
    )
    # Simulate a buy so the on-disk state differs from the template
    s1["current_cash"] = 50000
    save_state(agent_name="gemini", state=s1, agents_root=agents_root)

    s2 = init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-05-01",  # Different — should be ignored
    )
    assert s2["inception_date"] == "2026-04-17"
    assert s2["current_cash"] == 50000  # existing state preserved


def test_init_creates_memory_subdirs(
    template_root: Path, agents_root: Path
) -> None:
    (template_root / "investment_beliefs.md").write_text("# beliefs", encoding="utf-8")
    (template_root / "watchlist.json").write_text("[]", encoding="utf-8")
    (template_root / "trade_journal").mkdir()

    init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-17",
    )
    assert (agents_root / "gemini" / "investment_beliefs.md").exists()
    assert (agents_root / "gemini" / "watchlist.json").exists()
    assert (agents_root / "gemini" / "trade_journal").is_dir()


# ---- load/save ----

def test_load_state_returns_parsed_dict(
    template_root: Path, agents_root: Path
) -> None:
    init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-17",
    )
    state = load_state(agent_name="gemini", agents_root=agents_root)
    assert state["agent"] == "gemini"


def test_save_state_is_atomic(template_root: Path, agents_root: Path) -> None:
    init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-17",
    )
    state = load_state(agent_name="gemini", agents_root=agents_root)
    state["current_cash"] = 99000
    save_state(agent_name="gemini", state=state, agents_root=agents_root)
    # No temp file left behind
    assert not (agents_root / "gemini" / "portfolio_state.json.tmp").exists()
    # Value persisted
    assert load_state(agent_name="gemini", agents_root=agents_root)["current_cash"] == 99000


# ---- apply_buy ----

def test_apply_buy_deducts_cash_and_adds_position():
    state = {
        "agent": "gemini",
        "current_cash": 100000,
        "positions": [],
        "trade_history": [],
    }
    new_state = apply_buy(
        state,
        ticker="300750",
        name="宁德时代",
        quantity=100,
        price=185.50,
        eval_date="2026-04-17",
        reason_summary="新能源长期趋势",
    )
    assert new_state["current_cash"] == 100000 - (100 * 185.50)
    assert len(new_state["positions"]) == 1
    pos = new_state["positions"][0]
    assert pos == {
        "ticker": "300750",
        "name": "宁德时代",
        "quantity": 100,
        "avg_cost": 185.50,
        "bought_date": "2026-04-17",
    }
    assert len(new_state["trade_history"]) == 1
    t = new_state["trade_history"][0]
    assert t["action"] == "BUY"
    assert t["eval_date"] == "2026-04-17"
    assert t["reason_summary"] == "新能源长期趋势"


def test_apply_buy_averages_cost_when_adding_to_existing_position():
    state = {
        "current_cash": 50000,
        "positions": [
            {
                "ticker": "300750",
                "name": "宁德时代",
                "quantity": 100,
                "avg_cost": 180.00,
                "bought_date": "2026-04-10",
            }
        ],
        "trade_history": [],
    }
    new_state = apply_buy(
        state,
        ticker="300750",
        name="宁德时代",
        quantity=100,
        price=200.00,
        eval_date="2026-04-17",
        reason_summary="加仓",
    )
    pos = new_state["positions"][0]
    assert pos["quantity"] == 200
    assert pos["avg_cost"] == 190.00  # (100*180 + 100*200) / 200
    # bought_date moved to most recent for conservative T+1
    assert pos["bought_date"] == "2026-04-17"
    assert new_state["current_cash"] == 50000 - 100 * 200


# ---- apply_sell ----

def test_apply_sell_reduces_position_and_adds_cash():
    state = {
        "current_cash": 10000,
        "positions": [
            {
                "ticker": "300750",
                "name": "宁德时代",
                "quantity": 200,
                "avg_cost": 185.00,
                "bought_date": "2026-04-10",
            }
        ],
        "trade_history": [],
    }
    new_state = apply_sell(
        state,
        ticker="300750",
        quantity=100,
        price=192.30,
        eval_date="2026-04-17",
        reason_summary="部分获利了结",
    )
    pos = new_state["positions"][0]
    assert pos["quantity"] == 100
    assert pos["avg_cost"] == 185.00  # unchanged on partial sell
    assert new_state["current_cash"] == 10000 + 100 * 192.30
    assert new_state["trade_history"][0]["action"] == "SELL"


def test_apply_sell_removes_position_when_fully_closed():
    state = {
        "current_cash": 0,
        "positions": [
            {
                "ticker": "300750",
                "name": "宁德时代",
                "quantity": 100,
                "avg_cost": 185.00,
                "bought_date": "2026-04-10",
            }
        ],
        "trade_history": [],
    }
    new_state = apply_sell(
        state,
        ticker="300750",
        quantity=100,
        price=192.30,
        eval_date="2026-04-17",
        reason_summary="全部卖出",
    )
    assert new_state["positions"] == []
    assert new_state["current_cash"] == 100 * 192.30


def test_apply_sell_raises_when_position_missing():
    state = {"current_cash": 0, "positions": [], "trade_history": []}
    with pytest.raises(ValueError, match="no position"):
        apply_sell(
            state,
            ticker="300750",
            quantity=100,
            price=192.30,
            eval_date="2026-04-17",
            reason_summary="",
        )


def test_apply_sell_raises_when_quantity_too_large():
    state = {
        "current_cash": 0,
        "positions": [
            {
                "ticker": "300750",
                "name": "宁德时代",
                "quantity": 100,
                "avg_cost": 185.00,
                "bought_date": "2026-04-10",
            }
        ],
        "trade_history": [],
    }
    with pytest.raises(ValueError, match="quantity"):
        apply_sell(
            state,
            ticker="300750",
            quantity=200,
            price=192.30,
            eval_date="2026-04-17",
            reason_summary="",
        )


def test_apply_operations_do_not_mutate_input():
    """Both apply_buy and apply_sell must return new state, not mutate in place."""
    state = {
        "current_cash": 100000,
        "positions": [],
        "trade_history": [],
    }
    apply_buy(
        state,
        ticker="300750",
        name="宁德时代",
        quantity=100,
        price=185.50,
        eval_date="2026-04-17",
        reason_summary="",
    )
    # Original state untouched
    assert state["current_cash"] == 100000
    assert state["positions"] == []
    assert state["trade_history"] == []


# ---- Phase 3: trade journal + prev-decision + memory helpers ----

from src.portfolio.state import (
    load_prev_decision,
    save_trade_journal,
)


def test_save_trade_journal_writes_dated_file(template_root, agents_root):
    init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-17",
    )
    decision = {"eval_date": "2026-04-17", "market_view": "neutral", "decisions": []}
    save_trade_journal(
        agent_name="gemini",
        eval_date="2026-04-17",
        decision=decision,
        agents_root=agents_root,
    )
    path = agents_root / "gemini" / "trade_journal" / "2026-04-17.json"
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == decision


def test_save_trade_journal_creates_dir_if_missing(agents_root, tmp_path):
    # Bypass init — test that the helper creates trade_journal/ on demand
    (agents_root / "newbie").mkdir()
    decision = {"eval_date": "2026-04-17", "decisions": []}
    save_trade_journal(
        agent_name="newbie",
        eval_date="2026-04-17",
        decision=decision,
        agents_root=agents_root,
    )
    assert (agents_root / "newbie" / "trade_journal" / "2026-04-17.json").exists()


def test_load_prev_decision_returns_entry_matching_last_eval_date(
    template_root, agents_root
):
    init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-10",
    )
    prev = {"eval_date": "2026-04-10", "decisions": [
        {"action": "BUY", "ticker": "300750", "name": "宁德时代",
         "quantity": 100, "reason": {}}
    ]}
    save_trade_journal(
        agent_name="gemini",
        eval_date="2026-04-10",
        decision=prev,
        agents_root=agents_root,
    )
    state = load_state(agent_name="gemini", agents_root=agents_root)
    state["last_eval_date"] = "2026-04-10"

    got = load_prev_decision(state=state, agent_name="gemini", agents_root=agents_root)
    assert got == prev


def test_load_prev_decision_returns_none_when_no_prior_eval(
    template_root, agents_root
):
    init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-17",
    )
    state = load_state(agent_name="gemini", agents_root=agents_root)
    # last_eval_date is None — first eval
    assert load_prev_decision(
        state=state, agent_name="gemini", agents_root=agents_root
    ) is None


def test_load_prev_decision_returns_none_when_file_missing(
    template_root, agents_root
):
    init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-10",
    )
    state = load_state(agent_name="gemini", agents_root=agents_root)
    state["last_eval_date"] = "2026-04-99"  # file doesn't exist
    assert load_prev_decision(
        state=state, agent_name="gemini", agents_root=agents_root
    ) is None
