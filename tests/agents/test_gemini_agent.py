"""Tests for GeminiAgent.

We inject a mock ``client`` so tests don't hit Gemini's API. The mock
mimics ``client.models.generate_content(model=, contents=)`` returning
an object with a ``.text`` attribute.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.agents.base import AgentResult
from src.agents.gemini_agent import GeminiAgent


def _ok_response(text: str):
    return SimpleNamespace(text=text)


def _make_client(text: str = "{}", *, raise_exc: Exception | None = None) -> MagicMock:
    client = MagicMock()
    if raise_exc is not None:
        client.models.generate_content.side_effect = raise_exc
    else:
        client.models.generate_content.return_value = _ok_response(text)
    return client


# ---- init ----

def test_init_requires_api_key_when_no_client_injected():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiAgent(api_key="")


def test_init_accepts_injected_client_without_api_key():
    fake_client = MagicMock()
    agent = GeminiAgent(api_key="", _client=fake_client)
    assert agent._client is fake_client


def test_init_stores_model_name():
    agent = GeminiAgent(api_key="", model_name="gemini-3-pro", _client=MagicMock())
    assert agent.model_name == "gemini-3-pro"


# ---- decide ----

def test_decide_returns_parsed_decision_on_success():
    json_text = '{"eval_date": "2026-04-17", "market_view": "neutral", "decisions": []}'
    client = _make_client(json_text)

    agent = GeminiAgent(api_key="", _client=client)
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


def test_decide_calls_generate_content_with_keyword_args():
    """The new SDK requires kw-only args: model= and contents=."""
    client = _make_client('{"x": 1}')
    agent = GeminiAgent(
        api_key="", model_name="gemini-2.5-pro", _client=client,
    )
    agent.decide(briefing="b", portfolio_state={}, memory={})

    call = client.models.generate_content.call_args
    assert call.kwargs["model"] == "gemini-2.5-pro"
    assert "b" in call.kwargs["contents"]
    # No positional args (would fail upstream)
    assert call.args == ()


def test_decide_passes_briefing_into_prompt():
    client = _make_client('{"x": 1}')
    agent = GeminiAgent(api_key="", _client=client)
    agent.decide(
        briefing="UNIQUE_BRIEFING_MARKER",
        portfolio_state={"agent": "gemini", "current_cash": 100000, "positions": []},
        memory={},
    )
    sent_prompt = client.models.generate_content.call_args.kwargs["contents"]
    assert "UNIQUE_BRIEFING_MARKER" in sent_prompt


def test_decide_includes_memory_in_prompt():
    client = _make_client('{"x": 1}')
    agent = GeminiAgent(api_key="", _client=client)
    agent.decide(
        briefing="b",
        portfolio_state={"agent": "gemini", "current_cash": 100000, "positions": []},
        memory={"investment_beliefs": "BELIEFS_MARKER"},
    )
    sent_prompt = client.models.generate_content.call_args.kwargs["contents"]
    assert "BELIEFS_MARKER" in sent_prompt


def test_decide_includes_portfolio_state_in_prompt():
    client = _make_client('{"x": 1}')
    agent = GeminiAgent(api_key="", _client=client)
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
    sent_prompt = client.models.generate_content.call_args.kwargs["contents"]
    assert "300750" in sent_prompt
    assert "81450" in sent_prompt or "81,450" in sent_prompt


def test_decide_returns_error_on_api_exception():
    client = _make_client(raise_exc=RuntimeError("API timeout"))
    agent = GeminiAgent(api_key="", _client=client)
    result = agent.decide(briefing="b", portfolio_state={}, memory={})
    assert result.status == "error"
    assert "API timeout" in result.error


def test_decide_returns_error_on_unparseable_response():
    client = _make_client("not json at all")
    agent = GeminiAgent(api_key="", _client=client)
    result = agent.decide(briefing="b", portfolio_state={}, memory={})
    assert result.status == "error"
    assert result.raw_response == "not json at all"
    assert "JSON" in result.error or "json" in result.error


def test_decide_handles_markdown_fenced_json():
    client = _make_client(
        '```json\n{"eval_date": "2026-04-17", "decisions": []}\n```'
    )
    agent = GeminiAgent(api_key="", _client=client)
    result = agent.decide(briefing="b", portfolio_state={}, memory={})
    assert result.status == "decision"
    assert result.decision["eval_date"] == "2026-04-17"


def test_name_and_display_name():
    agent = GeminiAgent(api_key="", _client=MagicMock())
    assert agent.name == "gemini"
    assert "Gemini" in agent.display_name
