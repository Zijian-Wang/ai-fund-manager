"""Gemini agent.

Uses the ``google-genai`` SDK (the supported successor to the deprecated
``google-generativeai``). The agent receives the per-agent briefing text
+ raw portfolio state + memory dict, renders the system prompt via
``build_full_prompt``, and calls the provider's API.

Tests inject a mock client via ``_client`` so they don't hit the network.
"""
from __future__ import annotations

import json
from typing import Any

from src.agents.base import AgentResult, BaseAgent
from src.briefing import build_full_prompt


_DEFAULT_MODEL = "gemini-2.5-pro"


class GeminiAgent(BaseAgent):
    name = "gemini"
    display_name = "Gemini 2.5 Pro"

    def __init__(
        self,
        api_key: str,
        *,
        model_name: str = _DEFAULT_MODEL,
        _client: Any = None,
    ) -> None:
        if not api_key and _client is None:
            raise ValueError(
                "GEMINI_API_KEY is required (set in .env or pass api_key=...)"
            )
        self.model_name = model_name
        if _client is not None:
            self._client = _client
        else:
            from google import genai

            self._client = genai.Client(api_key=api_key)

    def _render_memory(self, memory: dict) -> str:
        """Concatenate memory files into one text blob with section headers."""
        if not memory:
            return ""
        chunks = []
        for key, value in memory.items():
            if not value:
                continue
            chunks.append(f"# {key}\n{value}")
        return "\n\n".join(chunks) or ""

    def _render_state(self, state: dict) -> str:
        """Compact JSON snapshot for the agent's structured reference."""
        snapshot = {
            "current_cash": state.get("current_cash"),
            "positions": state.get("positions", []),
            "last_eval_date": state.get("last_eval_date"),
        }
        return json.dumps(snapshot, ensure_ascii=False, indent=2)

    def decide(
        self, briefing: str, portfolio_state: dict, memory: dict
    ) -> AgentResult:
        prompt = build_full_prompt(
            memory_text=self._render_memory(memory),
            portfolio_text=self._render_state(portfolio_state),
            market_briefing=briefing,
        )

        try:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            raw_text = response.text
        except Exception as exc:  # noqa: BLE001
            return AgentResult(status="error", error=str(exc))

        try:
            decision = self.parse_response(raw_text)
        except ValueError as exc:
            return AgentResult(
                status="error", error=str(exc), raw_response=raw_text
            )

        return AgentResult(
            status="decision", decision=decision, raw_response=raw_text
        )
