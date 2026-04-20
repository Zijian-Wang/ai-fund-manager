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

    # Walk every balanced {...} block in the raw text and return the first
    # that parses as JSON. This tolerates leading prose that happens to
    # contain braces (e.g. "I think {x: 1} is an example... {real: json}").
    last_parse_error: json.JSONDecodeError | None = None
    cursor = 0
    while True:
        start = raw.find("{", cursor)
        if start == -1:
            break
        depth = 0
        in_string = False
        escaped = False
        end = -1
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
                    end = i
                    break
        if end == -1:
            break  # unbalanced; nothing more to try
        candidate = raw[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_parse_error = exc
            cursor = start + 1  # try the next `{`
    if last_parse_error is not None:
        raise ValueError(
            f"JSON parse failed: {last_parse_error.msg}"
        ) from last_parse_error
    raise ValueError("no JSON object found in response")


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
