"""Tests for GeminiAgent.

We inject a mock model so tests don't hit Gemini's API. The mock mimics
``model.generate_content(prompt, ...)`` returning an object with ``.text``.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.agents.base import AgentResult
from src.agents.gemini_agent import GeminiAgent


def _ok_response(text: str):
    return SimpleNamespace(text=text)


def test_init_requires_api_key_when_no_model_injected():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiAgent(api_key="")


def test_init_accepts_injected_model_without_api_key():
    fake_model = MagicMock()
    agent = GeminiAgent(api_key="", _model=fake_model)
    assert agent._model is fake_model


def test_decide_returns_parsed_decision_on_success():
    fake_model = MagicMock()
    json_text = '{"eval_date": "2026-04-17", "market_view": "neutral", "decisions": []}'
    fake_model.generate_content.return_value = _ok_response(json_text)

    agent = GeminiAgent(api_key="", _model=fake_model)
    result = agent.decide(
        briefing="market briefing here",
        portfolio_state={"agent": "gemini", "current_cash": 100000, "positions": []},
        memory={"investment_beliefs": "be patient"},
    )
    assert isinstance(result, AgentResult)
    assert result.status == "decision"
    assert result.decision == {
        "eval_date": "2026-04-17",
        "market_view": "neutral",
        "decisions": [],
    }
    assert result.raw_response == json_text


def test_decide_passes_briefing_into_prompt():
    fake_model = MagicMock()
    fake_model.generate_content.return_value = _ok_response('{"x": 1}')

    agent = GeminiAgent(api_key="", _model=fake_model)
    agent.decide(
        briefing="UNIQUE_BRIEFING_MARKER",
        portfolio_state={"agent": "gemini", "current_cash": 100000, "positions": []},
        memory={},
    )
    sent_prompt = fake_model.generate_content.call_args.args[0]
    assert "UNIQUE_BRIEFING_MARKER" in sent_prompt


def test_decide_includes_memory_in_prompt():
    fake_model = MagicMock()
    fake_model.generate_content.return_value = _ok_response('{"x": 1}')

    agent = GeminiAgent(api_key="", _model=fake_model)
    agent.decide(
        briefing="b",
        portfolio_state={"agent": "gemini", "current_cash": 100000, "positions": []},
        memory={"investment_beliefs": "BELIEFS_MARKER"},
    )
    sent_prompt = fake_model.generate_content.call_args.args[0]
    assert "BELIEFS_MARKER" in sent_prompt


def test_decide_includes_portfolio_state_in_prompt():
    fake_model = MagicMock()
    fake_model.generate_content.return_value = _ok_response('{"x": 1}')

    agent = GeminiAgent(api_key="", _model=fake_model)
    agent.decide(
        briefing="b",
        portfolio_state={
            "agent": "gemini",
            "current_cash": 81450,
            "positions": [{"ticker": "300750", "name": "宁德时代", "quantity": 100,
                           "avg_cost": 185.50, "bought_date": "2026-04-10"}],
        },
        memory={},
    )
    sent_prompt = fake_model.generate_content.call_args.args[0]
    # The portfolio state is rendered into the prompt somewhere
    assert "300750" in sent_prompt
    assert "81450" in sent_prompt or "81,450" in sent_prompt


def test_decide_returns_error_on_api_exception():
    fake_model = MagicMock()
    fake_model.generate_content.side_effect = RuntimeError("API timeout")

    agent = GeminiAgent(api_key="", _model=fake_model)
    result = agent.decide(briefing="b", portfolio_state={}, memory={})
    assert result.status == "error"
    assert "API timeout" in result.error


def test_decide_returns_error_on_unparseable_response():
    fake_model = MagicMock()
    fake_model.generate_content.return_value = _ok_response("not json at all")

    agent = GeminiAgent(api_key="", _model=fake_model)
    result = agent.decide(briefing="b", portfolio_state={}, memory={})
    assert result.status == "error"
    assert result.raw_response == "not json at all"
    assert "JSON" in result.error or "json" in result.error


def test_decide_handles_markdown_fenced_json():
    fake_model = MagicMock()
    fake_model.generate_content.return_value = _ok_response(
        '```json\n{"eval_date": "2026-04-17", "decisions": []}\n```'
    )
    agent = GeminiAgent(api_key="", _model=fake_model)
    result = agent.decide(briefing="b", portfolio_state={}, memory={})
    assert result.status == "decision"
    assert result.decision["eval_date"] == "2026-04-17"


def test_name_and_display_name():
    fake_model = MagicMock()
    agent = GeminiAgent(api_key="", _model=fake_model)
    assert agent.name == "gemini"
    assert "Gemini" in agent.display_name
