"""Tests for AgentResult dataclass and BaseAgent ABC."""
from __future__ import annotations

import pytest

from src.agents.base import AgentResult, BaseAgent


# ---- AgentResult ----

def test_agent_result_decision_status():
    r = AgentResult(status="decision", decision={"market_view": "bullish"})
    assert r.status == "decision"
    assert r.decision == {"market_view": "bullish"}
    assert r.error is None
    assert r.raw_response is None


def test_agent_result_error_status():
    r = AgentResult(status="error", error="API timeout", raw_response="...")
    assert r.status == "error"
    assert r.error == "API timeout"
    assert r.decision is None


# ---- BaseAgent.parse_response: default implementation ----

class _Concrete(BaseAgent):
    """A concrete subclass for testing the default parse_response."""
    name = "test"
    display_name = "Test Agent"

    def decide(self, briefing, portfolio_state, memory):  # pragma: no cover
        return AgentResult(status="decision", decision={})


def test_parse_response_plain_json():
    out = _Concrete().parse_response('{"action": "BUY", "ticker": "300750"}')
    assert out == {"action": "BUY", "ticker": "300750"}


def test_parse_response_strips_markdown_json_fence():
    raw = '```json\n{"action": "BUY"}\n```'
    out = _Concrete().parse_response(raw)
    assert out == {"action": "BUY"}


def test_parse_response_strips_bare_markdown_fence():
    raw = '```\n{"action": "SELL"}\n```'
    out = _Concrete().parse_response(raw)
    assert out == {"action": "SELL"}


def test_parse_response_extracts_first_json_with_leading_commentary():
    raw = (
        "Here is my decision after thinking carefully:\n"
        '{"market_view": "neutral", "decisions": []}\n'
        "Hope this helps!"
    )
    out = _Concrete().parse_response(raw)
    assert out == {"market_view": "neutral", "decisions": []}


def test_parse_response_handles_nested_objects():
    raw = '{"reason": {"thesis": "growth", "risk": "regulation"}}'
    out = _Concrete().parse_response(raw)
    assert out["reason"]["thesis"] == "growth"


def test_parse_response_raises_on_no_json():
    with pytest.raises(ValueError, match="no JSON"):
        _Concrete().parse_response("just some text, no JSON here")


def test_parse_response_raises_on_invalid_json():
    with pytest.raises(ValueError, match="JSON"):
        _Concrete().parse_response("{invalid: json}")


# ---- BaseAgent ABC enforcement ----

def test_base_agent_cannot_instantiate_directly():
    with pytest.raises(TypeError):
        BaseAgent()  # type: ignore[abstract]


# ---- extract_json module-level ----

from src.agents.base import extract_json


def test_extract_json_module_function_works_standalone():
    assert extract_json('{"action": "BUY"}') == {"action": "BUY"}


def test_extract_json_module_function_handles_markdown_fence():
    assert extract_json('```json\n{"x": 1}\n```') == {"x": 1}


def test_extract_json_module_function_raises_on_no_json():
    with pytest.raises(ValueError):
        extract_json("plain text")


def test_extract_json_skips_unparseable_brace_block_before_real_json():
    """Leading prose with an example like `{foo}` shouldn't abort parsing."""
    raw = (
        "First let me think: maybe {alpha: beta} or similar.\n"
        "Actually the answer is:\n"
        '{"eval_date": "2026-04-17", "decisions": []}'
    )
    assert extract_json(raw) == {
        "eval_date": "2026-04-17",
        "decisions": [],
    }
