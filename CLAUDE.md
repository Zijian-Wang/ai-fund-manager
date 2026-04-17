# AI基金经理 — A股模拟组合（多Agent版）

## 项目概述

多个AI（Claude、Gemini等）各自独立管理 ¥100,000 A股模拟组合。相同数据输入、不同AI大脑、独立决策。对比结果用于小红书内容发布。

- **初始资金**：每个Agent ¥100,000
- **投资范围**：A股股票、ETF（不做期货/期权）
- **决策频率**：每日（按需触发）
- **执行方式**：Claude Code 为总指挥，API Agent自动运行，Claude通过隔离子Agent决策
- **业绩基准**：CSI 300（沪深300指数）

## 技术架构

**Claude Code 是 orchestrator**。用户说"开始今天的评估"，Claude Code 完成所有工作：
1. 拉取市场数据和新闻
2. 构建冻结的共享简报
3. **生成隔离子Agent**做Claude的决策（只拿到冻结简报，无web访问，无session上下文——技术层面的公平保障）
4. 调用API Agent（Gemini等，使用相同冻结简报）
5. 生成对比报告

**没有独立的 `run_weekly.py` 脚本**——Claude Code 就是流水线本身。

### Claude子Agent

Claude的投资决策由一个**隔离的Claude Code子Agent**执行：
- **模型**：opus（可配置，一行切换到下一代模型如 4.7）
- **输入**：仅冻结简报 + Claude的持仓状态 + 记忆 + system prompt
- **限制**：无web工具、无原始API数据、无其他Agent结果
- **输出**：JSON决策

这确保Claude和API Agent在信息层面完全对等——公平不靠自觉，靠隔离。

## 技术栈

- Python 3.11+
- 数据源：TuShare Pro（主力）、AKShare（备用，版本锁定）、BaoStock（零配置兜底）
- 新闻：Eastmoney JSON API + 财联社 + Claude Code WebSearch
- AI Agent：Gemini API（`google-generativeai`），未来可加 DeepSeek/GPT
- Claude：通过隔离的 Claude Code 子Agent 决策（模型: opus，无需 Anthropic API key）
- 存储：本地 JSON/Markdown 文件

## 项目结构

```
ai-fund-manager/
├── CLAUDE.md                      # 本文件
├── README.md                      # 用户操作指南
├── .env                           # TUSHARE_TOKEN, GEMINI_API_KEY
├── requirements.txt
├── src/
│   ├── data/
│   │   ├── tushare_client.py      # TuShare Pro 封装（含缓存+限速）
│   │   ├── akshare_client.py      # AKShare 备用封装
│   │   ├── baostock_client.py     # BaoStock 零配置兜底
│   │   ├── market_data.py         # 获取+缓存市场数据（指数、板块、持仓）
│   │   └── news_fetcher.py        # Eastmoney JSON API + 财联社结构化新闻
│   ├── agents/
│   │   ├── base.py                # BaseAgent ABC + AgentResult dataclass
│   │   ├── gemini_agent.py        # 调Gemini API，返回AgentResult
│   │   └── registry.py            # Agent注册表：从.env发现活跃Agent
│   ├── portfolio/
│   │   ├── state.py               # 读写每个Agent的portfolio_state.json（原子写入）
│   │   └── performance.py         # NAV计算、收益率、vs CSI 300基准
│   ├── guardrails.py              # 共享风控验证（ticker/手数/T+1/仓位限制）
│   ├── briefing.py                # 组装共享简报（市场数据+新闻+持仓）
│   └── output/
│       ├── renderer.py            # JSON决策 → 单Agent Markdown报告
│       └── comparison.py          # 多Agent对比报告
├── memory_template/               # 模板 — 新Agent初始化时复制
│   ├── portfolio_state.json       # 100%现金起始状态
│   ├── investment_beliefs.md
│   ├── market_regime.md
│   ├── watchlist.json
│   ├── trade_journal/
│   └── lessons/
├── agents/                        # 每个Agent的持久化状态（运行时创建）
│   ├── claude/
│   │   ├── portfolio_state.json
│   │   ├── memory/
│   │   ├── trade_journal/
│   │   └── output/
│   └── gemini/
│       ├── portfolio_state.json
│       ├── memory/
│       ├── trade_journal/
│       └── output/
├── track_record/
│   └── nav_history.json           # 派生文件，从agents/*/portfolio_state.json重建
├── data_cache/                    # 缓存的API响应
│   ├── trade_cal.json             # 交易日历（独立缓存，月度刷新）
│   └── {eval_date}/              # 按交易日分目录
│       ├── *.json                 # 各类市场数据
│       └── briefing.md            # 冻结的简报（crash recovery用）
└── output/                        # 合并对比报告（用于小红书）
    └── 2026-04-17.md
```

## 核心概念

### eval_date（评估日期）

`eval_date` 是最近一个**已收盘**的交易日：
- 交易日15:30后 → eval_date = 今天
- 交易日15:30前或非交易日 → eval_date = 上一个交易日
- 使用 `data_cache/trade_cal.json`（TuShare `trade_cal()`）解析，正确处理调休

所有数据、简报、决策、报告都以 eval_date 为键。

### 公平协议

简报在步骤3冻结并缓存到磁盘。Claude在步骤4先做决策（看不到其他Agent的结果），然后步骤5才运行API Agent。所有Agent收到相同的冻结简报。

Claude的决策由隔离子Agent执行，只接收冻结简报——和API Agent信息对等，技术层面保障公平。

### 幂等性

- 每个决策包含 `eval_date` 字段
- 应用前检查 agent 的 `last_eval_date` — 重复则拒绝
- Session崩溃后重跑是安全的：已完成的Agent被跳过，冻结简报从磁盘加载

## Orchestration 流程

用户说"开始今天的评估"时：

```
1. 解析eval_date（最近已收盘交易日）
2. 拉取数据（市场数据 + 新闻，缓存到 data_cache/{eval_date}/）
3. 构建并冻结简报（缓存到 data_cache/{eval_date}/briefing.md）
4. Claude做决策（使用冻结简报，先于API Agent）
5. 运行API Agent（Gemini等，使用相同冻结简报）
6. 生成报告（对比报告 + 各Agent报告，缺席Agent显示"未评估"）
```

## Agent系统

### AgentResult

```python
@dataclass
class AgentResult:
    status: Literal["decision", "error"]
    decision: dict | None = None
    error: str | None = None
    raw_response: str | None = None
```

### BaseAgent接口

```python
class BaseAgent(ABC):
    name: str
    display_name: str

    @abstractmethod
    def decide(self, briefing: str, portfolio_state: dict, memory: dict) -> AgentResult: ...

    def parse_response(self, raw: str) -> dict:
        """从原始LLM输出中提取JSON。默认：去掉markdown代码块，找第一个有效JSON。"""
        ...
```

Claude不在Python Agent注册表中——由orchestrator生成隔离子Agent处理。状态在 `agents/claude/`，决策逻辑在隔离子Agent中运行（模型: opus，可一行升级）。

### 添加新Agent

1. 在 `src/agents/<provider>_agent.py` 中继承 `BaseAgent`
2. 实现 `decide()` 和可选的 `parse_response()`
3. 在 `.env` 中添加 API key
4. 在 `src/agents/registry.py` 中注册
5. 下次运行时自动从 `memory_template/` 初始化 `agents/<name>/`

## 数据层

### 数据源级联（按数据类型）

| 数据类型 | 主力 | 备用 | 兜底 |
|---------|------|------|------|
| 指数价格 | TuShare `index_daily` | BaoStock | 缓存 |
| 个股价格 | TuShare `daily` | BaoStock | 缓存 |
| 板块排名 | AKShare `stock_board_industry_name_em`（含retry/backoff） | 缓存 | — |
| 北向资金 | TuShare `moneyflow_hsgt` | 缓存 | — |
| 有效ticker | TuShare `stock_basic` | 缓存（周度刷新） | — |
| 新闻 | `news_fetcher.py`（Eastmoney+财联社） | Claude WebSearch | "新闻暂不可用" |

**注**：AKShare 的 northbound 和 fina_indicator 端点（`datacenter-web.eastmoney.com`）在我们的环境中不可达——已从级联中删除。`fina_indicator` 推迟到由 guardrails 实际消费时再加。

### 缓存策略

- 交易日历：`data_cache/trade_cal.json`（独立缓存，月度刷新）
- 市场数据：`data_cache/{eval_date}/*.json`
- 冻结简报：`data_cache/{eval_date}/briefing.md`（crash recovery）
- Ticker列表：周度刷新
- 缓存过期：超过5个交易日的缓存数据用于NAV计算时发出警告

## Guardrails（共享风控）

所有Agent通过相同的 `guardrails.py` 验证：

| 规则 | 值 |
|------|------|
| 单只最大仓位 | 50% |
| 组合回撤熔断 | -15% |
| 单只回撤review | -20% |
| 每日最大交易数 | 10 |
| 最小交易单位 | 100股 |
| T+1 | 不能卖当天买入的 |
| 最低日成交额 | ¥500万 |

### 执行价格

模拟交易使用市场数据中的**最新收盘价**作为执行价格。

## Portfolio State（每Agent独立）

`agents/<name>/portfolio_state.json` 是该Agent历史的**唯一数据源**。
`track_record/nav_history.json` 是**派生文件**，每次评估后从所有Agent状态重建。

## System Prompt

共享模板，所有Agent使用相同的prompt。存放在 `src/briefing.py` 的模板字符串中。

关键变量用 `{placeholder}` 注入：
- `{memory_content}` — 从 agent 的 memory/ 目录读取
- `{portfolio_state}` — 当前持仓明细 + NAV + vs基准
- `{market_briefing}` — 冻结的市场简报

## Agent输出格式

所有Agent必须输出此JSON schema：

```json
{
  "eval_date": "2026-04-17",
  "market_view": "对当前市场的判断",
  "decisions": [
    {
      "action": "BUY/SELL/HOLD",
      "ticker": "300750",
      "name": "宁德时代",
      "quantity": 100,
      "reason": {
        "thesis": "...",
        "catalyst": "...",
        "risk": "...",
        "invalidation": "..."
      }
    }
  ],
  "watchlist_updates": [
    {"ticker": "300308", "name": "中际旭创", "note": "等回调再看"}
  ],
  "reflection": "对上期决策的回顾",
  "note_to_audience": "写给观众的一段话"
}
```

## 反思机制

反思嵌入在简报中，不是独立步骤：
- 每次评估的简报包含"上期回顾"，展示上期决策的实际结果
- Agent在 `reflection` 字段中回顾
- `investment_beliefs.md` 随时间积累更新

## 依赖

```
tushare>=1.4.0
akshare>=1.18,<2           # 1.14.85 在 Python 3.14 上不可用；major 锁定
baostock
google-genai>=1.0           # google-generativeai 的官方继任者
python-dotenv>=1.0.0
requests>=2.31.0
```

## 注意事项

- TuShare Pro 5000积分，200次/分钟限制，做好缓存
- AKShare接口不稳定，用try/except包裹，失败时fallback
- 交易日历用 TuShare `trade_cal()` 解析（处理调休），缓存到 `data_cache/trade_cal.json`
- JSON输出可能格式不对，`parse_response()` 做好容错（提取代码块）
- `portfolio_state.json` 最重要——原子写入（写临时文件再rename）
- 冻结简报缓存到磁盘，确保session崩溃后重跑的一致性

## 完整设计文档

详见 `docs/superpowers/specs/2026-04-17-multi-agent-fund-manager-design.md`

## 评估流程 (Orchestration Runbook)

当用户说"开始今天的评估"时，按以下步骤执行。每一步都包含具体的 Python 调用。

### 前置：激活 venv

```bash
source .venv/bin/activate
# 或每次调用时使用 .venv/bin/python
```

所有代码示例假设 `python` 是 venv 里的那个。

### Step 1 — 解析 eval_date

```python
from pathlib import Path
from src.data.eval_date import resolve_eval_date
from src.data.tushare_client import TuShareClient
import os
from dotenv import load_dotenv

load_dotenv()
cache_root = Path("data_cache")
cache_root.mkdir(exist_ok=True)

tushare = TuShareClient(
    token=os.environ["TUSHARE_TOKEN"], cache_root=cache_root
)

# Refresh calendar if missing or narrow
from datetime import date, timedelta
today = date.today()
start = today.replace(month=1, day=1).strftime("%Y%m%d")
end = (today + timedelta(days=60)).strftime("%Y%m%d")
tushare.trade_cal_refresh(start_date=start, end_date=end)

eval_date = resolve_eval_date(cache_root=cache_root)
# e.g. "2026-04-17"
```

**Idempotency gate:** before proceeding, check every active agent's
`last_eval_date`. If ALL agents have `last_eval_date == eval_date`, stop
with "今日评估已完成". If the briefing file exists, skip re-fetching and
reuse it (see Step 3).

### Step 2 — 拉取数据

```python
from src.data.akshare_client import AKShareClient
from src.data.baostock_client import BaoStockClient
from src.data.market_data import fetch_market_data
from src.data.news_fetcher import fetch_news

akshare = AKShareClient()
baostock = BaoStockClient()

# Gather every active agent's current holdings tickers
# (see Step 4 for loading agent state)
all_holdings = set()  # populated below once agent states are loaded

market_data = fetch_market_data(
    eval_date=eval_date,
    holdings_tickers=list(all_holdings),
    cache_root=cache_root,
    tushare=tushare,
    akshare=akshare,
    baostock=baostock,
)

news = fetch_news(limit=20)
# Optionally supplement with WebSearch/WebFetch for macro context:
# Use Claude Code's WebSearch tool, append items to `news` list under
# a "补充资讯" pseudo-source. Skip if Layer 1 already returned plenty.
```

### Step 3 — 构建并冻结简报

```python
from src.briefing import build_shared_briefing
from src.data.cache import cache_dir_for, write_json_atomic

shared = build_shared_briefing(market_data, news)
briefing_path = cache_dir_for(cache_root, eval_date) / "briefing.md"
briefing_path.parent.mkdir(parents=True, exist_ok=True)
briefing_path.write_text(shared, encoding="utf-8")
```

**On re-run:** if `briefing_path` exists, load it instead of re-building.
This is the frozen briefing — fairness depends on it NOT changing between
Claude's decision (Step 4) and API agents' decisions (Step 5).

### Step 4 — Claude 决策（隔离子Agent）

For each eval, Claude decides FIRST so it cannot see other agents' results.

```python
from src.agents.base import extract_json
from src.briefing import build_agent_briefing, build_full_prompt
from src.data.market_data import (
    extract_index_close, extract_stock_prices, extract_stock_volumes_yuan,
)
from src.guardrails import validate_decision
from src.portfolio.state import (
    apply_buy, apply_sell, init_agent_state, load_agent_memory,
    load_prev_decision, load_state, save_state, save_trade_journal,
)
from src.portfolio.performance import append_nav_entry
from src.data.market_data import get_valid_tickers

# Initialize / load Claude's state
claude_state = init_agent_state(
    agent_name="claude",
    agents_root=Path("agents"),
    template_root=Path("memory_template"),
    inception_date=eval_date,  # only used on first init
)

# Build Claude's per-agent briefing
current_prices = extract_stock_prices(market_data)
benchmark_close = extract_index_close(market_data, "000300.SH")
inception_benchmark_close = None  # read from first nav_history entry if present
if claude_state["nav_history"]:
    inception_benchmark_close = claude_state["nav_history"][0].get("benchmark_close")

prev_claude = load_prev_decision(
    state=claude_state, agent_name="claude", agents_root=Path("agents")
)

agent_briefing = build_agent_briefing(
    shared=shared,
    agent_name="claude",
    state=claude_state,
    prev_decision=prev_claude,
    current_prices=current_prices,
    benchmark_close=benchmark_close,
    inception_benchmark_close=inception_benchmark_close,
)

memory = load_agent_memory(agent_name="claude", agents_root=Path("agents"))
memory_text = "\n\n".join(f"# {k}\n{v}" for k, v in memory.items())

import json
portfolio_text = json.dumps(
    {
        "current_cash": claude_state["current_cash"],
        "positions": claude_state["positions"],
        "last_eval_date": claude_state["last_eval_date"],
    },
    ensure_ascii=False, indent=2,
)

full_prompt = build_full_prompt(
    memory_text=memory_text,
    portfolio_text=portfolio_text,
    market_briefing=agent_briefing,
)
```

Now spawn the subagent via the `Agent` tool:

```
Agent(
    subagent_type="fund-manager-claude",
    description="Claude's trading decision for {eval_date}",
    prompt=full_prompt,
)
```

The subagent returns its final message as text. Extract the JSON:

```python
raw_text = agent_result  # the string returned by the Agent tool
try:
    decision = extract_json(raw_text)
except ValueError as exc:
    # Log + skip Claude for this eval
    print(f"Claude parse failed: {exc}")
    decision = None
```

If `decision` is parsed, validate and apply:

```python
def _ticker_suffix(tk: str) -> str:
    """A-share ticker → exchange suffix.

    6xx/688 → Shanghai (.SH, incl. STAR)
    4xx/8xx → Beijing Exchange (.BJ)
    else    → Shenzhen (.SZ, incl. 000/002/300 ChiNext)
    """
    if tk.startswith("6"):
        return ".SH"
    if tk.startswith(("4", "8")):
        return ".BJ"
    return ".SZ"


if decision is not None:
    valid_tickers = get_valid_tickers(cache_root=cache_root, tushare=tushare)
    volumes = extract_stock_volumes_yuan(market_data)
    # Pre-fetch volumes for any BUY ticker NOT in current holdings
    buy_tickers = {
        d["ticker"] for d in decision.get("decisions", [])
        if d.get("action") == "BUY" and d.get("ticker") not in volumes
    }
    if buy_tickers:
        from src.data.market_data import fetch_stock_5d
        for tk in buy_tickers:
            block = fetch_stock_5d(
                ts_code=f"{tk}{_ticker_suffix(tk)}",
                eval_date=eval_date,
                cache_root=cache_root,
                tushare=tushare,
                baostock=baostock,
            )
            rows = block.get("rows") or []
            if rows and "amount" in rows[0] and rows[0]["amount"]:
                volumes[tk] = float(rows[0]["amount"]) * 1000

    errors = validate_decision(
        decision,
        state=claude_state,
        eval_date=eval_date,
        current_prices=current_prices,
        valid_tickers=valid_tickers,
        ticker_volumes_yuan=volumes,
    )
    if errors:
        print(f"Claude decision rejected: {[e.rule for e in errors]}")
        # Still save the raw decision to trade_journal for the record
        save_trade_journal(
            agent_name="claude", eval_date=eval_date,
            decision=decision, agents_root=Path("agents"),
        )
    else:
        # Apply every trade
        working = claude_state
        for d in decision.get("decisions", []):
            action = d.get("action")
            if action == "BUY":
                working = apply_buy(
                    working,
                    ticker=d["ticker"], name=d["name"],
                    quantity=d["quantity"], price=current_prices[d["ticker"]],
                    eval_date=eval_date,
                    reason_summary=(d.get("reason") or {}).get("thesis", ""),
                )
            elif action == "SELL":
                working = apply_sell(
                    working,
                    ticker=d["ticker"], quantity=d["quantity"],
                    price=current_prices[d["ticker"]], eval_date=eval_date,
                    reason_summary=(d.get("reason") or {}).get("thesis", ""),
                )
            # HOLD: no state change
        working = append_nav_entry(
            working, eval_date=eval_date,
            current_prices=current_prices, benchmark_close=benchmark_close,
        )
        working["last_eval_date"] = eval_date
        save_state(agent_name="claude", state=working, agents_root=Path("agents"))
        save_trade_journal(
            agent_name="claude", eval_date=eval_date,
            decision=decision, agents_root=Path("agents"),
        )
        claude_state = working
```

### Step 5 — API Agents (Gemini, others)

```python
from src.agents.registry import get_active_agents

active = get_active_agents()  # reads .env for each registered agent

for agent in active:
    state = init_agent_state(
        agent_name=agent.name,
        agents_root=Path("agents"),
        template_root=Path("memory_template"),
        inception_date=eval_date,
    )

    prev = load_prev_decision(
        state=state, agent_name=agent.name, agents_root=Path("agents")
    )
    incep_bench = None
    if state["nav_history"]:
        incep_bench = state["nav_history"][0].get("benchmark_close")

    agent_briefing = build_agent_briefing(
        shared=shared,
        agent_name=agent.name,
        state=state,
        prev_decision=prev,
        current_prices=current_prices,
        benchmark_close=benchmark_close,
        inception_benchmark_close=incep_bench,
    )
    mem = load_agent_memory(agent_name=agent.name, agents_root=Path("agents"))

    result = agent.decide(
        briefing=agent_briefing, portfolio_state=state, memory=mem,
    )

    if result.status == "error":
        print(f"{agent.name} errored: {result.error}")
        continue

    # Same validate + apply flow as Claude in Step 4
    # (refactor candidate: extract an apply_agent_decision() helper)
```

**Retry:** API errors (timeout, rate limit) — one retry with 30s backoff
before giving up on the agent for this eval.

### Step 6 — 生成报告

```python
from src.portfolio.performance import (
    compute_cumulative_return_pct, compute_nav, rebuild_track_record,
)
from src.output.renderer import render_agent_report
from src.output.comparison import render_comparison_report

# Rebuild track_record/nav_history.json from all agents
rebuild_track_record(
    agents_root=Path("agents"),
    output_path=Path("track_record") / "nav_history.json",
)

# Per-agent reports
agent_entries: dict[str, dict] = {}
metrics_agents: dict[str, dict] = {}
for agent_name in ["claude"] + [a.name for a in active]:
    state_path = Path("agents") / agent_name / "portfolio_state.json"
    if not state_path.exists():
        agent_entries[agent_name] = {"display_name": agent_name, "decision": None}
        continue
    state = load_state(agent_name=agent_name, agents_root=Path("agents"))
    # Decision is in trade_journal
    from src.data.cache import read_json
    decision = read_json(
        Path("agents") / agent_name / "trade_journal" / f"{eval_date}.json"
    )
    display_name = {
        "claude": "Claude",
        "gemini": "Gemini 2.5 Pro",
    }.get(agent_name, agent_name)

    # Per-agent report (only if decision exists)
    if decision is not None:
        report = render_agent_report(
            display_name=display_name,
            decision=decision,
            state=state,
            current_prices=current_prices,
            benchmark_close=benchmark_close,
            inception_benchmark_close=(
                state["nav_history"][0].get("benchmark_close")
                if state["nav_history"] else None
            ),
        )
        agent_out = Path("agents") / agent_name / "output" / f"{eval_date}.md"
        agent_out.parent.mkdir(parents=True, exist_ok=True)
        agent_out.write_text(report, encoding="utf-8")

    agent_entries[agent_name] = {
        "display_name": display_name,
        "decision": decision,
    }
    # Build comparison metrics for this agent
    if state["nav_history"]:
        latest = state["nav_history"][-1]
        prev = (state["nav_history"][-2]
                if len(state["nav_history"]) >= 2 else None)
        today_pct = (
            (latest["nav"] - prev["nav"]) / prev["nav"] * 100
            if prev and prev["nav"] else 0.0
        )
        metrics_agents[agent_name] = {
            "nav": latest["nav"],
            "today_pct": today_pct,
            "cumulative_pct": latest["cumulative_return_pct"] * 100,
            "position_count": latest["position_count"],
        }

# Benchmark metrics: infer inception close from earliest nav_history entry
inception_bench = None
for s in (claude_state, *[load_state(agent_name=a.name, agents_root=Path("agents"))
                          for a in active]):
    if s.get("nav_history") and s["nav_history"][0].get("benchmark_close"):
        inception_bench = s["nav_history"][0]["benchmark_close"]
        break
bench_cum = (
    (benchmark_close - inception_bench) / inception_bench * 100
    if inception_bench else 0.0
)
# Today's benchmark change comes from market_data
idx_rows = (market_data.get("indices", {}).get("000300.SH", {}).get("rows") or [])
bench_today = float(idx_rows[0]["pct_chg"]) if idx_rows else 0.0

metrics = {
    "eval_date": eval_date,
    "benchmark": {
        "index": "000300.SH",
        "close": benchmark_close,
        "today_pct": bench_today,
        "cumulative_pct": bench_cum,
    },
    "agents": metrics_agents,
}

comparison = render_comparison_report(
    metrics=metrics,
    agent_entries=agent_entries,
)
out_path = Path("output") / f"{eval_date}.md"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(comparison, encoding="utf-8")

print(f"✓ 评估完成 {eval_date}")
print(f"  对比报告：{out_path}")
for name in agent_entries:
    p = Path("agents") / name / "output" / f"{eval_date}.md"
    if p.exists():
        print(f"  {name}: {p}")
```

### 最小失败态

- Data layer 全部失败 → 简报里报 "市场数据暂不可用"，各 agent 只看新闻决策；
  若新闻也全失败，简报说 "数据暂不可用"，agent 几乎一定选择 HOLD/观望。
- 某个 agent 的决策无效 → 只跳过那个 agent；报告里标记 "未评估"。
- Session 中途崩溃 → 重跑安全：冻结简报从磁盘加载；已完成的 agent 被幂等性检查跳过。
