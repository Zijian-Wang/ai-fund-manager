"""Per-agent Markdown report renderer.

Input: one agent's decision dict + state + pre-extracted prices + benchmarks.
Output: a Markdown string suitable for writing to
``agents/<name>/output/{eval_date}.md``.
"""
from __future__ import annotations


def _pct(value: float) -> str:
    return f"{value:+.2f}%" if value != 0 else "0.00%"


def _yuan(value: float) -> str:
    return f"¥{value:,.0f}"


def _bullet_decisions(decisions: list[dict], *, action: str) -> str:
    items = [d for d in decisions if d.get("action") == action]
    if not items:
        return "无"
    lines = []
    for d in items:
        ticker = d.get("ticker", "")
        name = d.get("name", "")
        qty = d.get("quantity")
        header = f"- {name}" + (f" ({ticker})" if ticker else "")
        if qty:
            header += f" {qty}股"
        lines.append(header)
        reason = d.get("reason") or {}
        for label, key in (
            ("Thesis", "thesis"),
            ("Catalyst", "catalyst"),
            ("Risk", "risk"),
            ("Invalidation", "invalidation"),
        ):
            val = reason.get(key)
            if val:
                lines.append(f"  - **{label}**: {val}")
    return "\n".join(lines)


def _holdings_table(
    positions: list[dict], current_prices: dict[str, float]
) -> str:
    if not positions:
        return "暂无持仓（100% 现金）"
    lines = [
        "| 标的 | 持仓 | 成本 | 现价 | 浮盈 |",
        "|------|------|------|------|------|",
    ]
    for pos in positions:
        ticker = pos["ticker"]
        name = pos.get("name", "")
        qty = pos["quantity"]
        cost = pos["avg_cost"]
        price = current_prices.get(ticker)
        if price is None:
            lines.append(f"| {name} ({ticker}) | {qty}股 | ¥{cost:.2f} | — | — |")
        else:
            pnl_pct = (price - cost) / cost * 100 if cost else 0
            lines.append(
                f"| {name} ({ticker}) | {qty}股 | ¥{cost:.2f} | "
                f"¥{price:.2f} | {_pct(pnl_pct)} |"
            )
    return "\n".join(lines)


def render_agent_report(
    *,
    display_name: str,
    decision: dict,
    state: dict,
    current_prices: dict[str, float],
    benchmark_close: float | None,
    inception_benchmark_close: float | None,
) -> str:
    """Render the full per-agent Markdown report."""
    eval_date = decision.get("eval_date", "?")

    positions = state.get("positions", [])
    cash = float(state.get("current_cash", 0))
    initial = float(state.get("initial_capital", 0))
    nav = cash
    for pos in positions:
        price = current_prices.get(pos["ticker"], pos["avg_cost"])
        nav += pos["quantity"] * price
    cum_return_pct = (nav - initial) / initial * 100 if initial else 0.0

    bench_return_pct = None
    if (benchmark_close is not None
            and inception_benchmark_close is not None
            and inception_benchmark_close != 0):
        bench_return_pct = (
            (benchmark_close - inception_benchmark_close)
            / inception_benchmark_close * 100
        )

    decisions = decision.get("decisions", []) or []
    buys = [d for d in decisions if d.get("action") == "BUY"]
    sells = [d for d in decisions if d.get("action") == "SELL"]
    holds = [d for d in decisions if d.get("action") == "HOLD"]

    watchlist = decision.get("watchlist_updates", []) or []

    sections: list[str] = []
    sections.append(f"# AI基金经理 · {display_name}｜{eval_date}")
    sections.append("")

    mv = (decision.get("market_view") or "").strip()
    sections.append("## 市场判断")
    sections.append(mv if mv else "（未提供）")
    sections.append("")

    sections.append("## 本期操作")
    if not decisions:
        sections.append("无操作（观望）")
    else:
        sections.append(f"### 买入 ({len(buys)})")
        sections.append(_bullet_decisions(decisions, action="BUY"))
        sections.append("")
        sections.append(f"### 卖出 ({len(sells)})")
        sections.append(_bullet_decisions(decisions, action="SELL"))
        sections.append("")
        if holds:
            sections.append(f"### 持有 ({len(holds)})")
            sections.append(_bullet_decisions(decisions, action="HOLD"))
    sections.append("")

    sections.append("## 当前组合")
    sections.append(_holdings_table(positions, current_prices))
    sections.append("")
    sections.append(f"现金：{_yuan(cash)}")
    sections.append(f"组合净值：{_yuan(nav)}（{_pct(cum_return_pct)}）")
    sections.append(f"累计收益：{_pct(cum_return_pct)}")
    if bench_return_pct is not None:
        sections.append(f"同期CSI300：{_pct(bench_return_pct)}")
    sections.append("")

    sections.append("## 观察名单")
    if not watchlist:
        sections.append("暂无更新")
    else:
        for item in watchlist:
            t = item.get("ticker", "")
            n = item.get("name", "")
            note = item.get("note", "")
            sections.append(f"- {n} ({t}) — {note}")
    sections.append("")

    reflection = (decision.get("reflection") or "").strip()
    sections.append("## 反思")
    sections.append(reflection if reflection else "（未提供）")
    sections.append("")

    note = (decision.get("note_to_audience") or "").strip()
    sections.append("## 致观众")
    sections.append(note if note else "（未提供）")
    sections.append("")

    sections.append("---")
    sections.append("*AI独立决策，仅供娱乐和研究，不构成投资建议。*")

    return "\n".join(sections)
