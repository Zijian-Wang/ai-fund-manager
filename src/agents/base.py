"""Agent base class and result type.

Every agent (Gemini, future DeepSeek, etc.) subclasses ``BaseAgent`` and
implements ``decide()``. Claude is NOT in this hierarchy — it's handled
by the orchestrator via an isolated Claude Code subagent (per spec).

``parse_response`` provides a default JSON extractor that handles common
LLM quirks: markdown fences, leading/trailing commentary. Providers can
override if their output format is more structured.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


@dataclass
class AgentResult:
    status: Literal["decision", "error"]
    decision: dict | None = None
    error: str | None = None
    raw_response: str | None = None


def extract_json(raw: str) -> dict:
    """Extract the first JSON object from a raw LLM response.

    Strategy:
    1. Try parsing as-is.
    2. Strip surrounding markdown fences (```json ... ``` or ``` ... ```).
    3. Bracket-match the first ``{...}`` block (string-aware).

    Raises ``ValueError`` if no valid JSON object is found.
    """
    text = raw.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    if text.startswith("```"):
        stripped = text
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
        if "```" in stripped:
            stripped = stripped.rsplit("```", 1)[0]
        stripped = stripped.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    start = raw.find("{")
    if start == -1:
        raise ValueError("no JSON object found in response")
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(raw)):
        c = raw[i]
        if in_string:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                candidate = raw[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"JSON parse failed: {exc.msg} in {candidate[:80]!r}"
                    ) from exc
    raise ValueError("unbalanced braces in response")


class BaseAgent(ABC):
    name: str = ""
    display_name: str = ""

    @abstractmethod
    def decide(
        self, briefing: str, portfolio_state: dict, memory: dict
    ) -> AgentResult:
        ...

    def parse_response(self, raw: str) -> dict:
        return extract_json(raw)
