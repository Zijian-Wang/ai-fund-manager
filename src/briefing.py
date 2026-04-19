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

import math


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

【决策频率】
本项目采用**周度再平衡**：每个ISO周的第一个交易日调仓一次，下次决策在下周。
你每周看一次行情、做一次决策；之间不操作。考虑到这个节奏，仓位请面向「持有
一周以上」设计，不要做"赌今晚新闻"的超短线。

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
5. INVALIDATION（失效条件）：什么情况发生意味着thesis错了？**这就是你的止损。
   系统没有自动熔断——跌多少都不会强制平仓。invalidation 是你的纪律。**

【约束】
- 投资范围：A股股票、ETF。不做期货/期权。
- 持有现金是完全可以接受的决策。
- **单只标的最大配置 ≤ 50%（allocation_pct 上限）**。
- 没有组合级熔断，没有家长式保护。风控由你的 invalidation 和仓位决定。
- 你的推理过程会被公开展示。坦诚、清晰、有个性。不写官话。

【重要：你不负责计算股数】
用 allocation_pct（0–50 的整数）表达你对每个标的的目标仓位比例。
不要自己计算股数、总成本或验证资金是否充足。
一个独立的验证系统会把百分比转换为具体股数并检查可执行性。
如果总配置超过 100% 或违反其他规则，系统会告诉你，你再调整。

示例：
- "对宁德时代非常有 conviction" → allocation_pct: 40
- "小仓位试探性建仓" → allocation_pct: 10
- "清仓" → allocation_pct: 0
- "不操作的标的" → 不需要出现在 decisions 里

【输出格式】
你必须以JSON格式输出决策。结构如下：
{{
  "eval_date": "YYYY-MM-DD",
  "market_view": "对当前市场的判断（2-3段文字）",
  "decisions": [
    {{
      "action": "BUY",
      "ticker": "300750",
      "name": "宁德时代",
      "allocation_pct": 40,
      "reason": {{
        "thesis": "...",
        "catalyst": "...",
        "risk": "...",
        "invalidation": "..."
      }}
    }},
    {{
      "action": "SELL",
      "ticker": "600036",
      "name": "招商银行",
      "allocation_pct": 0,
      "reason": {{
        "thesis": "thesis已失效，清仓",
        "invalidation": "已触发"
      }}
    }}
  ],
  "watchlist_updates": [
    {{"ticker": "300308", "name": "中际旭创", "note": "等回调再看"}}
  ],
  "reflection": "对上期决策的回顾（基于简报中的上期回顾数据）",
  "note_to_audience": "写给观众的一段话，坦诚、有个性"
}}

注意：eval_date 必须与简报日期一致。不操作的持仓不需要出现在 decisions 里。

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

def _window_return_pct(rows: list[dict], window: int) -> float | None:
    """Return pct change between rows[0] (latest) and rows[window-1] (or oldest).

    Assumes rows are sorted latest-first (TuShare convention; BaoStock is
    normalized to match)."""
    if not rows:
        return None
    latest = _safe_float(rows[0].get("close"))
    oldest_idx = min(window - 1, len(rows) - 1)
    oldest = _safe_float(rows[oldest_idx].get("close"))
    if latest is None or oldest is None or oldest == 0:
        return None
    return (latest - oldest) / oldest * 100


def _render_index_row(code: str, rows: list[dict]) -> str:
    name = INDEX_DISPLAY_NAMES[code]
    if not rows:
        return f"| {name} | — | — | — | — |"
    latest_close = _safe_float(rows[0].get("close"))
    today_pct = _safe_float(rows[0].get("pct_chg"))
    five_day_pct = _window_return_pct(rows, 5)
    twenty_day_pct = _window_return_pct(rows, 20)

    latest_str = f"{latest_close:,.2f}" if latest_close is not None else "—"
    today_str = _pct(today_pct) if today_pct is not None else "—"
    five_str = _pct(five_day_pct) if five_day_pct is not None else "—"
    twenty_str = _pct(twenty_day_pct) if twenty_day_pct is not None else "—"
    return f"| {name} | {latest_str} | {today_str} | {five_str} | {twenty_str} |"


def _render_indices_section(indices: dict, eval_date: str) -> str:
    lines = [
        f"## 大盘指数（截至 {eval_date}，约 20 个交易日回顾）",
        "| 指数 | 收盘 | 当日涨跌 | 近 5 日 | 近 20 日 |",
        "|------|------|---------|---------|----------|",
    ]
    for code in INDEX_ORDER:
        block = indices.get(code, {"rows": []})
        lines.append(_render_index_row(code, block.get("rows", [])))
    return "\n".join(lines)


def _render_sector_section(sector_block: dict, eval_date: str, top_n: int = 5) -> str:
    lines = [
        f"## 行业板块排名（{eval_date} 收盘）",
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


def _render_northbound_section(north_block: dict, eval_date: str) -> str:
    lines = [f"## 北向资金（截至 {eval_date}）"]
    rows = north_block.get("rows", []) or []
    if not rows:
        lines.append("数据暂不可用")
        return "\n".join(lines)

    def _sum_yi(n: int) -> float:
        total_wan = 0.0
        for row in rows[:n]:
            v = _safe_float(row.get("north_money"))
            if v is not None:
                total_wan += v
        return total_wan / 10000

    five_yi = _sum_yi(5)
    twenty_yi = _sum_yi(20)
    lines.append(
        f"- 近 5 日 {'净流入' if five_yi >= 0 else '净流出'}："
        f"{abs(five_yi):.2f} 亿元"
    )
    lines.append(
        f"- 近 20 日 {'净流入' if twenty_yi >= 0 else '净流出'}："
        f"{abs(twenty_yi):.2f} 亿元"
    )
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
        _render_indices_section(market_data.get("indices", {}), eval_date),
        "",
        _render_sector_section(market_data.get("sector_ranking", {}), eval_date),
        "",
        _render_northbound_section(market_data.get("northbound", {}), eval_date),
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
    lines = ["## 上周决策回顾"]
    eval_date = prev_decision.get("eval_date", "?")
    lines.append(f"上周({eval_date}) 你的操作：")
    decisions = prev_decision.get("decisions", []) or []
    if not decisions:
        lines.append("- 无操作")
        return "\n".join(lines)
    for d in decisions:
        action = d.get("action", "?")
        ticker = d.get("ticker", "")
        name = d.get("name", "")
        if action == "HOLD":
            lines.append("- HOLD")
            continue
        pct = d.get("allocation_pct")
        pct_str = f" allocation_pct={pct}%" if pct is not None else ""
        line = f"- {action} {name}({ticker}){pct_str}"
        cur = current_prices.get(ticker)
        if cur is not None:
            line += f" → 现价 ¥{cur:.2f}"
        lines.append(line)
    lines.append("（请基于一周后的结果反思你的判断。）")
    return "\n".join(lines)


def _render_trading_constraints(
    nav: float, positions: list[dict], current_prices: dict[str, float]
) -> str:
    max_price = nav / 100
    lines = [
        "【交易约束提醒】",
        f"组合规模：¥{nav:,.0f}。A股最小交易单位100股。",
        f"股价超过¥{max_price:.0f}的标的无法买入（任何 allocation_pct 都不够买一手）。",
        "买入100股（一手）股价为P的标的所需最小 allocation_pct = ⌈P × 100 ÷ NAV × 100⌉%。",
    ]
    if nav <= 0:
        return "\n".join(lines)
    expensive = []
    for pos in positions:
        price = current_prices.get(pos["ticker"])
        if price and price > 0:
            min_alloc = math.ceil(price * 100 / nav * 100)
            if min_alloc >= 10:
                name = pos.get("name", pos["ticker"])
                expensive.append(
                    f"  - {name}({pos['ticker']}) @¥{price:.2f} → 最小 allocation_pct = {min_alloc}%"
                )
    if expensive:
        lines.append("当前持仓需注意：")
        lines.extend(expensive)
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

    sections.extend([
        "",
        _render_trading_constraints(nav, positions, current_prices),
    ])

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
