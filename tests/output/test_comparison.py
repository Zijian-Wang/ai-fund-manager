"""Tests for the multi-agent comparison report renderer."""
from __future__ import annotations

from src.output.comparison import render_comparison_report


def _agent_entry(display_name: str, market_view: str) -> dict:
    return {
        "display_name": display_name,
        "decision": {
            "eval_date": "2026-04-17",
            "market_view": market_view,
            "decisions": [
                {"action": "BUY", "ticker": "300750", "name": "宁德时代",
                 "quantity": 100, "reason": {
                     "thesis": "好", "catalyst": "近", "risk": "低",
                     "invalidation": "业绩差"}},
            ],
            "reflection": "...",
            "note_to_audience": "...",
            "watchlist_updates": [],
        },
    }


def _metrics_sample() -> dict:
    return {
        "eval_date": "2026-04-17",
        "benchmark": {
            "index": "000300.SH",
            "close": 4728.67,
            "today_pct": 0.12,
            "cumulative_pct": 1.20,
        },
        "agents": {
            "claude": {"nav": 100500, "today_pct": 0.50,
                       "cumulative_pct": 0.50, "position_count": 2},
            "gemini": {"nav": 99800, "today_pct": -0.20,
                       "cumulative_pct": -0.20, "position_count": 3},
        },
    }


def test_comparison_has_title_with_date():
    out = render_comparison_report(
        metrics=_metrics_sample(),
        agent_entries={
            "claude": _agent_entry("Claude", "mv-claude"),
            "gemini": _agent_entry("Gemini 2.5 Pro", "mv-gemini"),
        },
    )
    first_line = out.splitlines()[0]
    assert "2026-04-17" in first_line
    assert "AI" in first_line


def test_comparison_table_lists_all_agents_and_benchmark():
    out = render_comparison_report(
        metrics=_metrics_sample(),
        agent_entries={
            "claude": _agent_entry("Claude", "mv-claude"),
            "gemini": _agent_entry("Gemini 2.5 Pro", "mv-gemini"),
        },
    )
    assert "Claude" in out
    assert "Gemini 2.5 Pro" in out
    assert "CSI" in out
    assert "+0.50" in out
    assert "-0.20" in out
    assert "+1.20" in out


def test_comparison_shows_each_agent_market_view_and_operations():
    out = render_comparison_report(
        metrics=_metrics_sample(),
        agent_entries={
            "claude": _agent_entry("Claude", "CLAUDE_MV_MARKER"),
            "gemini": _agent_entry("Gemini 2.5 Pro", "GEMINI_MV_MARKER"),
        },
    )
    assert "CLAUDE_MV_MARKER" in out
    assert "GEMINI_MV_MARKER" in out
    assert "宁德时代" in out


def test_comparison_includes_vs_benchmark_column():
    out = render_comparison_report(
        metrics=_metrics_sample(),
        agent_entries={
            "claude": _agent_entry("Claude", "x"),
            "gemini": _agent_entry("Gemini 2.5 Pro", "y"),
        },
    )
    # claude cumulative 0.5% - benchmark 1.2% = -0.70%
    assert "-0.70" in out
    # gemini cumulative -0.2% - benchmark 1.2% = -1.40%
    assert "-1.40" in out


def test_comparison_missing_agent_shown_as_skipped():
    metrics = _metrics_sample()
    metrics["agents"] = {
        "claude": metrics["agents"]["claude"],
    }
    out = render_comparison_report(
        metrics=metrics,
        agent_entries={
            "claude": _agent_entry("Claude", "x"),
            "gemini": {"display_name": "Gemini 2.5 Pro", "decision": None},
        },
    )
    assert "Gemini 2.5 Pro" in out
    assert "未评估" in out


def test_comparison_has_legal_footer():
    out = render_comparison_report(
        metrics=_metrics_sample(),
        agent_entries={
            "claude": _agent_entry("Claude", "x"),
            "gemini": _agent_entry("Gemini 2.5 Pro", "y"),
        },
    )
    assert "不构成投资建议" in out
