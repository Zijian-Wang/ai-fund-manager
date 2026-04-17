"""Briefing assembly + system prompt template.

Two-layer briefing per spec:

1. ``build_shared_briefing(market_data, news)`` — identical for all agents
   (indices, sector rankings, northbound, news).

2. ``build_agent_briefing(shared, ...)`` — appends the agent's holdings,
   NAV, vs-benchmark, and 上期回顾 (last decision review).

The full prompt is rendered by ``build_full_prompt(memory, portfolio, briefing)``
which fills the placeholders in ``SYSTEM_PROMPT_TEMPLATE``.
"""
from __future__ import annotations


INDEX_DISPLAY_NAMES = {
    "000001.SH": "上证综指",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000300.SH": "沪深300",
}

# Render order — matches the table in the spec.
INDEX_ORDER = ("000001.SH", "399001.SZ", "399006.SZ", "000300.SH")


# Identical to spec § "System Prompt", with three injection points.
SYSTEM_PROMPT_TEMPLATE = """你是一位管理10万元人民币A股模拟组合的独立基金经理。你拥有完全的投资决策权。

【你是谁】
你有自己的投资风格和判断力。你不是一个信息聚合器——你是一个有观点的投资者。
你会犯错，但你从错误中学习。你敢于持有与市场共识不同的观点，但只在你有充分
理由时才这样做。你不追涨杀跌，你寻找别人还没看到的机会。

【决策框架】
对于每一个投资决策，你必须产出结构化的思考：

1. THESIS（核心逻辑）：用2-3句话说清楚为什么买/卖/持有这个标的。
2. CATALYST（催化剂）：未来1-6个月内，什么会让市场认识到价值？
3. RISK（风险）：最大的下行风险是什么？
4. SIZING（仓位）：你有多确信？高确信=大仓位。
5. INVALIDATION（失效条件）：什么情况发生意味着thesis错了？

【约束】
- 投资范围：A股股票、ETF。不做期货/期权。
- 持有现金是完全可以接受的决策。
- 考虑T+1交易规则。
- 交易数量为100股的整数倍。
- 你的推理过程会被公开展示。坦诚、清晰、有个性。不写官话。

【输出格式】
你必须以JSON格式输出决策。结构如下：
{{
  "eval_date": "YYYY-MM-DD",
  "market_view": "对当前市场的判断（2-3段文字）",
  "decisions": [
    {{
      "action": "BUY/SELL/HOLD",
      "ticker": "300750",
      "name": "宁德时代",
      "quantity": 100,
      "reason": {{
        "thesis": "...",
        "catalyst": "...",
        "risk": "...",
        "invalidation": "..."
      }}
    }}
  ],
  "watchlist_updates": [
    {{"ticker": "300308", "name": "中际旭创", "note": "等回调再看"}}
  ],
  "reflection": "对上期决策的回顾（基于简报中的上期回顾数据）",
  "note_to_audience": "写给观众的一段话，坦诚、有个性"
}}

注意：eval_date 必须与简报日期一致。HOLD 表示继续持有现有仓位，不需要指定quantity。

【记忆】
{memory_content}

【当前持仓与业绩】
{portfolio_state}

【市场简报】
{market_briefing}

现在请做出本期投资决策。
"""


# ---- formatting helpers ----

def _pct(value: float) -> str:
    """Format as percent with sign: +1.23% / -2.34% / 0.00%."""
    return f"{value:+.2f}%" if value != 0 else "0.00%"


def _yuan(value: float) -> str:
    """Format as ¥X,XXX (no decimals)."""
    return f"¥{value:,.0f}"


def _yi_from_wan(wan_total: float) -> str:
    """Convert sum of 万元 to 亿元 string with 2 decimals."""
    return f"{wan_total / 10000:.2f}"


def _safe_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---- shared briefing ----

def _render_index_row(code: str, rows: list[dict]) -> str:
    name = INDEX_DISPLAY_NAMES[code]
    if not rows:
        return f"| {name} | — | — | — |"
    latest = rows[0]
    latest_close = _safe_float(latest.get("close"))
    today_pct = _safe_float(latest.get("pct_chg"))
    # 5-day return: latest vs 5 trading days back (or oldest available)
    oldest_idx = min(4, len(rows) - 1)
    oldest_close = _safe_float(rows[oldest_idx].get("close"))
    five_day_pct: float | None = None
    if (latest_close is not None and oldest_close is not None
            and oldest_close != 0):
        five_day_pct = (latest_close - oldest_close) / oldest_close * 100

    latest_str = f"{latest_close:,.2f}" if latest_close is not None else "—"
    today_str = _pct(today_pct) if today_pct is not None else "—"
    five_str = _pct(five_day_pct) if five_day_pct is not None else "—"
    return f"| {name} | {latest_str} | {today_str} | {five_str} |"


def _render_indices_section(indices: dict) -> str:
    lines = [
        "## 大盘指数（近5个交易日）",
        "| 指数 | 最新 | 今日涨跌 | 5日涨跌 |",
        "|------|------|---------|---------|",
    ]
    for code in INDEX_ORDER:
        block = indices.get(code, {"rows": []})
        lines.append(_render_index_row(code, block.get("rows", [])))
    return "\n".join(lines)


def _render_sector_section(sector_block: dict, top_n: int = 5) -> str:
    lines = [
        "## 行业板块排名（今日）",
        "| 排名 | 板块 | 涨跌幅 |",
        "|------|------|--------|",
    ]
    rows = sector_block.get("rows", []) or []
    if not rows:
        lines.append("| — | 板块数据暂不可用 | — |")
        return "\n".join(lines)
    # Sort by change_pct desc, take top_n
    sorted_rows = sorted(
        rows, key=lambda r: r.get("change_pct", 0.0), reverse=True
    )
    for i, row in enumerate(sorted_rows[:top_n], 1):
        lines.append(
            f"| {i} | {row.get('name', '—')} | {_pct(float(row.get('change_pct', 0)))} |"
        )
    return "\n".join(lines)


def _render_northbound_section(north_block: dict) -> str:
    lines = ["## 北向资金（近5日）"]
    rows = north_block.get("rows", []) or []
    if not rows:
        lines.append("数据暂不可用")
        return "\n".join(lines)
    total_wan = 0.0
    for row in rows[:5]:
        v = _safe_float(row.get("north_money"))
        if v is not None:
            total_wan += v
    yi_value = total_wan / 10000
    direction = "净流入" if yi_value >= 0 else "净流出"
    lines.append(f"近5日{direction}：{abs(yi_value):.2f} 亿元")
    return "\n".join(lines)


def _render_news_section(news: list[dict], top_n: int = 8) -> str:
    if not news:
        return "## 新闻摘要\n新闻数据暂不可用"
    lines = ["## 新闻摘要"]
    for i, item in enumerate(news[:top_n], 1):
        lines.append(f"{i}. {item.get('title', '').strip()}")
    return "\n".join(lines)


def build_shared_briefing(market_data: dict, news: list[dict]) -> str:
    """Build the shared market section of the briefing."""
    eval_date = market_data.get("eval_date", "?")
    sections = [
        f"# 市场简报 | {eval_date}",
        "",
        _render_indices_section(market_data.get("indices", {})),
        "",
        _render_sector_section(market_data.get("sector_ranking", {})),
        "",
        _render_northbound_section(market_data.get("northbound", {})),
        "",
        _render_news_section(news),
    ]
    return "\n".join(sections)


# ---- per-agent briefing ----

def _render_holdings_table(
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
            lines.append(
                f"| {name} ({ticker}) | {qty}股 | ¥{cost:.2f} | — | — |"
            )
        else:
            pnl_pct = (price - cost) / cost * 100 if cost else 0
            lines.append(
                f"| {name} ({ticker}) | {qty}股 | ¥{cost:.2f} | "
                f"¥{price:.2f} | {_pct(pnl_pct)} |"
            )
    return "\n".join(lines)


def _render_prev_review(
    prev_decision: dict, current_prices: dict[str, float]
) -> str:
    lines = ["## 上期回顾"]
    eval_date = prev_decision.get("eval_date", "?")
    lines.append(f"上期({eval_date}) 你的操作：")
    decisions = prev_decision.get("decisions", []) or []
    if not decisions:
        lines.append("- 无操作")
        return "\n".join(lines)
    for d in decisions:
        action = d.get("action", "?")
        ticker = d.get("ticker", "")
        name = d.get("name", "")
        if action == "HOLD":
            lines.append(f"- HOLD")
            continue
        qty = d.get("quantity", "?")
        # Extract avg cost from the actual trade — for review we use what's in
        # the decision; price discovery happens via current_prices.
        line = f"- {action} {name}({ticker}) {qty}股"
        cur = current_prices.get(ticker)
        if cur is not None:
            line += f" → 现价 ¥{cur:.2f}"
        lines.append(line)
    lines.append("（请基于结果反思你的判断。）")
    return "\n".join(lines)


def build_agent_briefing(
    *,
    shared: str,
    agent_name: str,
    state: dict,
    prev_decision: dict | None,
    current_prices: dict[str, float],
    benchmark_close: float | None,
    inception_benchmark_close: float | None,
) -> str:
    """Append the per-agent section to the shared briefing."""
    positions = state.get("positions", [])
    cash = float(state.get("current_cash", 0))
    initial = float(state.get("initial_capital", 0))

    nav = cash
    for pos in positions:
        price = current_prices.get(pos["ticker"], pos["avg_cost"])
        nav += pos["quantity"] * price
    cum_return_pct = (nav - initial) / initial * 100 if initial else 0.0

    sections = [
        shared,
        "",
        "---",
        "",
        "## 你的持仓",
        _render_holdings_table(positions, current_prices),
        "",
        f"当前现金：{_yuan(cash)}",
        f"组合净值：{_yuan(nav)}（{_pct(cum_return_pct)}）",
    ]

    if (benchmark_close is not None
            and inception_benchmark_close is not None
            and inception_benchmark_close != 0):
        bench_return_pct = (
            (benchmark_close - inception_benchmark_close)
            / inception_benchmark_close * 100
        )
        sections.append(f"同期CSI300：{_pct(bench_return_pct)}")

    if prev_decision:
        sections.extend(["", _render_prev_review(prev_decision, current_prices)])

    return "\n".join(sections)


# ---- system prompt rendering ----

def build_full_prompt(
    *, memory_text: str, portfolio_text: str, market_briefing: str
) -> str:
    """Render the system prompt with all three injection points filled."""
    return SYSTEM_PROMPT_TEMPLATE.format(
        memory_content=memory_text or "（暂无记忆）",
        portfolio_state=portfolio_text,
        market_briefing=market_briefing,
    )
