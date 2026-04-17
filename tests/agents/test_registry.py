"""Tests for agent registry / discovery."""
from __future__ import annotations

import pytest

from src.agents.base import AgentResult, BaseAgent
from src.agents.registry import AGENTS, _resolve_class, get_active_agents


# ---- _resolve_class ----

def test_resolve_class_imports_dotted_path():
    cls = _resolve_class("src.agents.base.BaseAgent")
    assert cls is BaseAgent


def test_resolve_class_raises_on_bad_module():
    with pytest.raises(ImportError):
        _resolve_class("src.nonexistent.Module")


def test_resolve_class_raises_on_missing_class():
    with pytest.raises(AttributeError):
        _resolve_class("src.agents.base.DoesNotExist")


# ---- get_active_agents with custom registry ----

def test_get_active_agents_returns_empty_when_no_env_keys():
    registry = {
        "gemini": {
            "class": "src.agents.gemini_agent.GeminiAgent",
            "env_key": "GEMINI_API_KEY",
        },
    }
    agents = get_active_agents(registry=registry, env={})
    assert agents == []


def test_get_active_agents_skips_missing_keys():
    registry = {
        "gemini": {
            "class": "src.agents.gemini_agent.GeminiAgent",
            "env_key": "GEMINI_API_KEY",
        },
        "deepseek": {
            "class": "src.agents.gemini_agent.GeminiAgent",  # reused for test
            "env_key": "DEEPSEEK_API_KEY",
        },
    }
    # Provide only GEMINI_API_KEY
    agents = get_active_agents(
        registry=registry,
        env={"GEMINI_API_KEY": "fake-key"},
    )
    assert len(agents) == 1
    assert agents[0].name == "gemini"


def test_get_active_agents_with_present_key_instantiates_agent():
    registry = {
        "gemini": {
            "class": "src.agents.gemini_agent.GeminiAgent",
            "env_key": "GEMINI_API_KEY",
        },
    }
    agents = get_active_agents(
        registry=registry,
        env={"GEMINI_API_KEY": "fake-key"},
    )
    assert len(agents) == 1
    assert isinstance(agents[0], BaseAgent)
    assert agents[0].name == "gemini"


def test_get_active_agents_skips_empty_string_keys():
    registry = {
        "gemini": {
            "class": "src.agents.gemini_agent.GeminiAgent",
            "env_key": "GEMINI_API_KEY",
        },
    }
    # Empty string is treated as "not set"
    agents = get_active_agents(
        registry=registry,
        env={"GEMINI_API_KEY": ""},
    )
    assert agents == []


# ---- registry contents ----

def test_default_registry_includes_gemini():
    assert "gemini" in AGENTS
    assert AGENTS["gemini"]["env_key"] == "GEMINI_API_KEY"
    assert AGENTS["gemini"]["class"] == "src.agents.gemini_agent.GeminiAgent"
