"""Multi-agent comparison report renderer.

The 小红书-ready digest: leaderboard table + each agent's market view and
operation summary. Rendered from pre-computed metrics (per-eval returns
vs benchmark) and each agent's decision dict.

``agent_entries`` maps agent_name -> {display_name, decision}. If
``decision`` is None, the agent is rendered as 未评估 in the table and
its narrative section is skipped.
"""
from __future__ import annotations


def _pct(value: float) -> str:
    return f"{value:+.2f}%" if value != 0 else "0.00%"


def _yuan(value: float) -> str:
    return f"¥{value:,.0f}"


def _summarize_decisions(decision: dict) -> str:
    """One-paragraph summary of the agent's operations."""
    decisions = (decision or {}).get("decisions", []) or []
    if not decisions:
        return "无操作（观望）"
    chunks: list[str] = []
    for d in decisions:
        action = d.get("action", "?")
        name = d.get("name", "")
        ticker = d.get("ticker", "")
        if action == "HOLD":
            chunks.append(f"HOLD {name}({ticker})")
            continue
        qty = d.get("quantity", "?")
        chunks.append(f"{action} {name}({ticker}) {qty}股")
    return "；".join(chunks)


def render_comparison_report(
    *,
    metrics: dict,
    agent_entries: dict[str, dict],
) -> str:
    """Render the full multi-agent comparison report.

    ``metrics`` shape:
        {
          "eval_date": "YYYY-MM-DD",
          "benchmark": {"index": "000300.SH", "close": 4728.67,
                        "today_pct": 0.12, "cumulative_pct": 1.20},
          "agents": {
            "<name>": {"nav": 100500, "today_pct": 0.50,
                       "cumulative_pct": 0.50, "position_count": 2},
            ...
          }
        }

    ``agent_entries`` shape:
        {
          "<name>": {
            "display_name": "Claude",
            "decision": <decision dict> or None,  # None = skipped
          },
          ...
        }
    """
    eval_date = metrics.get("eval_date", "?")
    bench = metrics.get("benchmark", {})
    bench_cum = bench.get("cumulative_pct", 0.0)

    sections: list[str] = []
    sections.append(f"# AI基金经理大乱斗｜{eval_date}")
    sections.append("")

    sections.append("| 选手 | 净值 | 本周收益 | 累计收益 | vs CSI300 |")
    sections.append("|------|------|---------|---------|-----------|")
    for name, entry in agent_entries.items():
        display = entry.get("display_name", name)
        m = metrics.get("agents", {}).get(name)
        if m is None or entry.get("decision") is None:
            sections.append(f"| {display} | — | — | — | 未评估 |")
            continue
        nav = m.get("nav", 0)
        today = m.get("today_pct", 0.0)
        cum = m.get("cumulative_pct", 0.0)
        vs_bench = cum - bench_cum
        sections.append(
            f"| {display} | {_yuan(nav)} | {_pct(today)} | "
            f"{_pct(cum)} | {_pct(vs_bench)} |"
        )
    sections.append(
        f"| CSI 300 | — | {_pct(bench.get('today_pct', 0))} | "
        f"{_pct(bench_cum)} | — |"
    )
    sections.append("")

    for name, entry in agent_entries.items():
        display = entry.get("display_name", name)
        decision = entry.get("decision")
        if decision is None:
            continue
        sections.append(f"## {display} 的判断")
        mv = (decision.get("market_view") or "").strip()
        sections.append(mv if mv else "（未提供）")
        sections.append("")
        sections.append("### 操作")
        sections.append(_summarize_decisions(decision))
        sections.append("")

    sections.append("---")
    sections.append("*多个AI独立决策，仅供娱乐和研究，不构成投资建议。*")

    return "\n".join(sections)
