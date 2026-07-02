"""Ollama Cloud agent (API path).

Uses Ollama Cloud via its OpenAI-compatible endpoint (https://ollama.com/v1).
Authentication uses the real OLLAMA_CLOUD_API_KEY (not the dummy "ollama").

IMPORTANT:
- Only models hosted on Ollama Cloud are supported (open-weight models).
- Good choices (2026): qwen3*, deepseek-r1*, glm-*, gemma4*, gpt-oss*, llama* etc.
- DO NOT use closed models here (e.g. gpt-4o, claude-*, gemini-*, grok-*) — they are not
  available on Ollama Cloud. Use the manual webchat agents for those.

The agent receives the same briefing + portfolio + memory as other agents and
must return the exact JSON schema expected by the system.
"""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from src.agents.base import AgentResult, BaseAgent
from src.briefing import build_full_prompt


_DEFAULT_MODEL = "qwen3:30b"   # Strong reasoning + Chinese support. Change per your cloud models.
# Other solid options often available on Ollama Cloud:
#   "deepseek-r1:70b", "qwen3.6:27b", "glm-5", "gemma4:27b", "gpt-oss:20b", "llama3.3:70b"


class OllamaAgent(BaseAgent):
    name = "ollama"
    display_name = "Ollama Cloud"

    def __init__(
        self,
        api_key: str,
        *,
        model_name: str = _DEFAULT_MODEL,
        _client: Any = None,
    ) -> None:
        if not api_key and _client is None:
            raise ValueError(
                "OLLAMA_CLOUD_API_KEY is required (set in .env or pass api_key=...)"
            )
        self.model_name = model_name
        if _client is not None:
            self._client = _client
        else:
            self._client = OpenAI(
                base_url="https://ollama.com/v1",
                api_key=api_key,
            )

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
            response = self._client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                # Many Ollama models respect this; harmless if ignored.
                # response_format={"type": "json_object"},
            )
            raw_text = response.choices[0].message.content or ""
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
