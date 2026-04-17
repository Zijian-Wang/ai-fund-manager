"""Agent registry — discover active agents from environment variables.

To add a new agent (e.g. DeepSeek):
1. Subclass BaseAgent in src/agents/<provider>_agent.py
2. Add an entry to AGENTS below with the dotted class path + env key
3. Add the env key to .env

Claude is intentionally NOT registered here — it's handled by the
orchestrator via an isolated Claude Code subagent (per spec).
"""
from __future__ import annotations

import importlib
import os
from typing import Any

from src.agents.base import BaseAgent


AGENTS: dict[str, dict[str, str]] = {
    "gemini": {
        "class": "src.agents.gemini_agent.GeminiAgent",
        "env_key": "GEMINI_API_KEY",
    },
    # "deepseek": {
    #     "class": "src.agents.deepseek_agent.DeepSeekAgent",
    #     "env_key": "DEEPSEEK_API_KEY",
    # },
}


def _resolve_class(dotted_path: str) -> type:
    """Import a class from a string like ``pkg.module.ClassName``."""
    module_path, _, class_name = dotted_path.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def get_active_agents(
    *,
    registry: dict[str, dict[str, str]] | None = None,
    env: dict[str, str] | None = None,
) -> list[BaseAgent]:
    """Return instantiated agents whose API key is present in ``env``.

    Empty/missing env values are treated identically (agent excluded).
    Tests pass a custom registry + env to avoid coupling to the live one.
    """
    reg = registry if registry is not None else AGENTS
    environment: Any = env if env is not None else os.environ

    active: list[BaseAgent] = []
    for name, info in reg.items():
        api_key = environment.get(info["env_key"], "")
        if not api_key:
            continue
        cls = _resolve_class(info["class"])
        active.append(cls(api_key=api_key))
    return active
