# Multi-Agent AI Fund Manager — Design Spec (v2.1)

## Overview

A multi-agent A-share simulated fund manager where multiple AI providers independently manage separate ¥100,000 portfolios. Each agent receives identical market data and makes independent investment decisions. The comparison of their strategies and performance creates compelling content for social media (小红书).

**Orchestrator**: Claude Code session. The user triggers a daily evaluation by asking Claude Code to run it. Claude Code fetches data, calls API agents, makes its own decision, and produces all reports. No standalone `run_weekly.py` pipeline — Claude Code *is* the pipeline.

**Cadence**: Daily on-demand (user triggers). Future: scheduled via CoWork or `/loop`.

## Constraints

- **No Anthropic API key**. Claude decisions are made by the orchestrating Claude Code session itself.
- **Gemini API key available**. Gemini decisions are made programmatically via Python.
- **Future providers** (DeepSeek, GPT, etc.) should be easy to add.
- **Data sources**: TuShare Pro (primary), AKShare (backup), BaoStock (fallback). TuShare has 5000 credits and 200 calls/min rate limit.
- **Storage**: Local JSON/Markdown files. No database.

## Orchestration Flow

When the user says "start today's eval":

```
1. RESOLVE EVAL DATE
   Determine the eval_date = the most recent COMPLETED trading day:
   - After 15:30 Beijing time on a trading day → eval_date = today
   - Before 15:30 or on a non-trading day → eval_date = previous trading day
   - Use cached trade_cal.json (see Caching section) to resolve holidays
   Check idempotency: if all agents already have last_eval_date == eval_date, stop.

2. FETCH DATA
   Claude Code runs Python data scripts to pull:
   - Index data, sector rankings, northbound flow (TuShare/AKShare/BaoStock)
   - Current prices for all agents' holdings
   All structured data cached to data_cache/{eval_date}/
   Claude Code runs news_fetcher.py to pull structured news:
   - Eastmoney JSON API headlines
   - 财联社 telegraph items
   Claude Code uses WebSearch/WebFetch for supplementary context:
   - Macro policy news, breaking stories, market sentiment
   All news merged and deduplicated.

3. BUILD + FREEZE BRIEFING
   Assemble a single Markdown briefing from all fetched data.
   Save frozen briefing to data_cache/{eval_date}/briefing.md
   >>> BRIEFING FROZEN HERE — no more web fetches after this point <<<
   On re-run: if briefing.md already exists, load it instead of re-assembling.

4. CLAUDE DECIDES (before API agents — no information advantage)
   Using the frozen briefing + own portfolio state + memory:
   - Produce JSON decision
   - Save raw decision to agents/claude/trade_journal/{eval_date}.json
   - Validate through guardrails
   - If valid: update portfolio state
   - If invalid: log errors, skip Claude for this eval

5. RUN API AGENTS
   For each API agent (Gemini, future others):
   - Load agent's portfolio state + memory
   - Call agent.decide(briefing, state, memory) via Python
   - Parse response via agent's parse_response() method
   - Save raw response to agents/{name}/trade_journal/{eval_date}.json
   - Validate through shared guardrails
   - If valid: update portfolio, record trade
   - If invalid: log errors, skip this agent today
   One retry with 30s backoff on transient API errors (timeout, rate limit).

6. GENERATE REPORTS
   - Update each agent's track record
   - Rebuild track_record/nav_history.json from all agents' states
   - Generate comparison report to output/ (with whatever agents completed)
   - Generate per-agent reports to agents/<name>/output/
   Reports are generated even if some agents failed — show "未评估" for missing agents.
```

### Fairness Protocol

The shared briefing is frozen after step 3 and cached to disk. Claude decides **before** API agents (step 4 before step 5), so Claude cannot see other agents' decisions. All agents receive the identical frozen briefing.

**Honest limitation**: Claude Code is the orchestrator, so it inherently has richer session context (it ran the data scripts, saw raw API responses, etc.) than API agents who only see the formatted briefing string. This is an honor-system constraint — Claude uses only the frozen briefing for its decision, but this is not technically enforced. For an entertainment/research project, this is acceptable. The "Claude Pro mode" (see Future Considerations) may later opt in to using this extra context explicitly.

### Crash Recovery

If a Claude Code session dies mid-eval:
- **Steps 1-3** are safe to redo — data is cached, and the frozen `briefing.md` is reused on re-run.
- **Steps 4-5**: The idempotency check (`last_eval_date`) prevents double-application for agents that already completed. Agents that hadn't started yet run normally.
- **Step 6**: Reports regenerate from current state, so they are always correct after re-run.

The key invariant: **the frozen briefing is cached to disk before any decisions are made**. This ensures a re-run produces the same briefing, maintaining fairness even across session crashes.

## Directory Structure

```
ai-fund-manager/
├── CLAUDE.md                      # Project instructions (updated for multi-agent)
├── README.md                      # User-facing instructions
├── .env                           # TUSHARE_TOKEN, GEMINI_API_KEY
├── requirements.txt
├── src/
│   ├── data/
│   │   ├── tushare_client.py      # TuShare Pro wrapper with caching + rate limiting
│   │   ├── akshare_client.py      # AKShare fallback wrapper
│   │   ├── baostock_client.py     # BaoStock zero-config fallback
│   │   ├── market_data.py         # Fetch + cache market data (indices, sectors, holdings)
│   │   └── news_fetcher.py        # Eastmoney JSON API + 财联社 for API agents
│   ├── agents/
│   │   ├── base.py                # BaseAgent ABC + AgentResult dataclass
│   │   ├── gemini_agent.py        # Calls Gemini API, returns AgentResult
│   │   └── registry.py            # Agent registry: discovers active agents from .env
│   ├── portfolio/
│   │   ├── state.py               # Read/write per-agent portfolio_state.json (atomic writes)
│   │   └── performance.py         # NAV calculation, returns, vs CSI 300 benchmark
│   ├── guardrails.py              # Shared validation: ticker, lot size, T+1, position limits
│   ├── briefing.py                # Assemble shared briefing from market data + news + holdings
│   └── output/
│       ├── renderer.py            # JSON decision → per-agent Markdown report
│       └── comparison.py          # Multi-agent comparison report
├── memory_template/               # TEMPLATE — copied for each new agent on init
│   ├── portfolio_state.json       # 100% cash starting state
│   ├── investment_beliefs.md
│   ├── market_regime.md
│   ├── watchlist.json
│   ├── trade_journal/
│   └── lessons/
├── agents/                        # Per-agent persistent state (created at runtime)
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
│   └── nav_history.json           # DERIVED from agents/*/portfolio_state.json
├── data_cache/                    # Cached API responses: data_cache/{trading_date}/*.json
└── output/                        # Combined comparison reports (for 小红书)
    └── 2026-04-17.md
```

### Key Changes from v1

- Removed `run_weekly.py` and `apply_decision.py` — Claude Code orchestrates directly
- Removed `src/agents/claude_agent.py` — Claude Code *is* the Claude agent
- Renamed `memory/` → `memory_template/` to avoid confusion with runtime state
- Removed `track_record/weekly_comparison/` — consolidated into `output/`
- Output files named by date (`2026-04-17.md`) not week number
- Removed `src/memory/` — reflection is embedded in next-session briefing

## Agent System

### AgentResult Dataclass

```python
@dataclass
class AgentResult:
    status: Literal["decision", "error"]
    decision: dict | None = None       # The JSON decision if successful
    error: str | None = None           # Error message if failed
    raw_response: str | None = None    # Raw LLM output for debugging
```

No more `None`-means-interactive ambiguity. Claude Code doesn't go through the `BaseAgent` interface — it makes decisions directly in the session.

### BaseAgent Interface

```python
class BaseAgent(ABC):
    name: str               # e.g. "gemini"
    display_name: str       # e.g. "Gemini 2.5 Pro"

    @abstractmethod
    def decide(self, briefing: str, portfolio_state: dict, memory: dict) -> AgentResult:
        """Call the provider's API and return a structured result."""
        ...

    def parse_response(self, raw: str) -> dict:
        """Extract JSON from raw LLM output. Override per provider.
        Default: strips markdown code fences, finds first valid JSON block."""
        ...
```

### Adding a New Agent

1. Subclass `BaseAgent` in `src/agents/<provider>_agent.py`
2. Implement `decide()` and optionally `parse_response()`
3. Add the API key to `.env` (e.g. `DEEPSEEK_API_KEY=...`)
4. Register in `src/agents/registry.py`
5. On next run, Claude Code auto-initializes `agents/<name>/` from `memory_template/`

### Agent Registry

Simple and explicit — no magic discovery:

```python
# src/agents/registry.py
AGENTS = {
    "gemini": {
        "class": "src.agents.gemini_agent.GeminiAgent",
        "env_key": "GEMINI_API_KEY",
    },
    # "deepseek": {
    #     "class": "src.agents.deepseek_agent.DeepSeekAgent",
    #     "env_key": "DEEPSEEK_API_KEY",
    # },
}

def get_active_agents() -> list[BaseAgent]:
    """Return agents whose API keys are present in .env."""
    ...
```

Claude is NOT in the registry — it's the orchestrator, not a registered agent. Its state lives in `agents/claude/` but its decision logic lives in the Claude Code session.

## Data Layer

### Market Data (`market_data.py`)

Fetches and caches structured market data. NOT the briefing — just raw data.

**Data points:**
- Index daily: SSE (000001.SH), SZSE (399001.SZ), ChiNext (399006.SZ), CSI 300 (000300.SH) — last 5 trading days
- Sector performance: Shenwan L1 industries, ranked by return
- Northbound flow: Net buy/sell
- All agents' holdings: current price, daily/weekly return
- Valid ticker list: for guardrails validation (cache weekly, not daily)

**Benchmark**: Use `index_daily(ts_code='000300.SH')` close price directly. No need for `index_weight()` component weights.

### Data Source Cascade (per data type)

Not all sources can provide all data types. Cascade is data-type-specific:

| Data Type | Primary | Fallback | Last Resort |
|-----------|---------|----------|-------------|
| Index prices | TuShare `index_daily` | BaoStock | Cache |
| Stock prices | TuShare `daily` | BaoStock | Cache |
| Sector rankings | AKShare `stock_board_industry_*_em` | Cache | — |
| Northbound flow | TuShare `moneyflow_hsgt` | AKShare | Cache |
| Financial indicators | TuShare `fina_indicator` (NOT `_vip`) | AKShare | Cache |
| Valid tickers | TuShare `stock_basic` | Cache (weekly refresh) | — |

### Caching

- **`eval_date`** is always the most recent **completed** trading day (see step 1 of Orchestration Flow). This is the trading date, NOT the calendar/run date. All data, briefings, and decisions are keyed by `eval_date`.
- Cache directory: `data_cache/{eval_date}/` — keyed by eval_date
- **Trading calendar**: `data_cache/trade_cal.json` is cached separately (not under a date-keyed dir — avoids chicken-and-egg). Refreshed monthly or when it doesn't cover the current date range. Uses TuShare `trade_cal()` which handles Chinese holidays and compensatory workdays (调休) correctly. Simple weekend checks are insufficient for A-share markets.
- Cache files are JSON, human-readable for debugging
- `stock_basic` (ticker list) cached weekly, not daily — it changes rarely
- **Frozen briefing**: `data_cache/{eval_date}/briefing.md` — the assembled briefing is cached after step 3. On re-run, this file is loaded instead of re-assembling, ensuring idempotent re-runs produce the same briefing.
- **Cache staleness**: If no primary or fallback source can provide data and cache is older than 5 trading days, the eval should warn and proceed with partial data rather than silently using stale prices for NAV calculation.
- Atomic writes: write to temp file, then rename, to prevent partial reads

### News Fetching

News is assembled in two layers with a clear merge order:

**Layer 1 — Structured news** (`news_fetcher.py`, primary):
- Eastmoney JSON API (`newsapi.eastmoney.com/kuaixun/v1/getlist_*`) — returns clean JSON, no scraping
- 财联社 (cls.cn) telegraph — timestamped rapid news
- Returns a structured list of `{title, summary, source, timestamp}`
- This is the baseline news that ALL agents see

**Layer 2 — Supplementary context** (Claude Code web tools, additive):
- Claude Code uses `WebSearch`/`WebFetch` for macro policy news, breaking stories, market sentiment
- These are appended to the briefing under a separate "补充资讯" heading
- Only added if Layer 1 succeeds — web tools do NOT replace structured news
- If Layer 1 fails entirely, Claude Code web tools become the sole news source

**Merge order in briefing**: Layer 1 headlines first (under "新闻摘要"), Layer 2 items second (under "补充资讯"). This makes it clear what is structured data vs. supplementary.

**Graceful degradation**: If both layers fail, briefing says "新闻数据暂不可用" and agents decide on price data alone. News is supplementary — agents can make sound decisions from price and sector data.

## Briefing Format

`briefing.py` assembles the briefing in two parts via explicit functions:

```python
def build_shared_briefing(market_data: dict, news: list) -> str:
    """Build the shared market section. Same for all agents."""
    ...

def build_agent_briefing(shared: str, agent_name: str, state: dict, prev_trades: list) -> str:
    """Append per-agent holdings, performance, and 上期回顾 to the shared briefing."""
    ...
```

Split into two parts:

### Shared Section (identical for all agents)

```markdown
# 市场简报 | {date}

## 大盘指数（近5个交易日）
| 指数 | 最新 | 涨跌幅 | 5日涨跌 |
|------|------|--------|---------|
| 上证综指 | 4,027.21 | +0.01% | -0.5% |
| ...

## 行业板块排名（本周）
| 排名 | 板块 | 涨跌幅 |
|------|------|--------|
| 1 | 医药生物 | +3.2% |
| ...

## 北向资金
本周净流入：¥52.3亿

## 新闻摘要
1. 国务院发布药品价格形成机制新政...
2. ...
```

### Per-Agent Section (appended per agent)

```markdown
## 你的持仓
| 标的 | 持仓 | 成本 | 现价 | 浮盈 |
|------|------|------|------|------|
| 宁德时代 (300750) | 100股 | ¥185.50 | ¥192.30 | +3.7% |
| ...

当前现金：¥81,450
组合净值：¥100,680（+0.68%）
同期CSI300：+1.20%

## 上期回顾
上期你买入了宁德时代(300750) 100股 @ ¥185.50。
该股本周涨幅 +3.7%，你的判断目前看是对的。
（这里展示上期决策的实际结果，供你反思。）
```

This solves:
- **H4**: Shared base + per-agent holdings, no contradiction
- **M6**: Reflection embedded naturally — agent sees its own track record and last period's results in every briefing

## Guardrails (Shared)

All agents go through identical validation in `guardrails.py`:

| Rule | Value |
|------|-------|
| Max single position | 50% of portfolio |
| Max portfolio drawdown (halt) | -15% |
| Max single stock drawdown (review) | -20% |
| Max trades per day | 10 |
| Round lot | 100 shares |
| T+1 | Cannot sell same-day purchase |
| Min daily volume | ¥5M (exclude illiquid stocks) |

### Idempotency (C2 fix)

Each decision includes an `eval_date` field — the **trading date** (most recent completed trading day), resolved in step 1 of the orchestration flow. Before applying any decision:

1. Check decision's `eval_date` matches the current eval's resolved trading date
2. Check agent's `last_eval_date` in portfolio state — reject if already evaluated for this date
3. After successful application, set `last_eval_date = eval_date`
4. Trade journal entry named `{eval_date}.json`, not sequential

This prevents double-application and stale decision application. On session crash + re-run, agents that already completed are safely skipped.

### Execution Price

Trades use the **latest close price** from market data as the simulated execution price. Since this is a simulation with human execution on the next trading day, close price is a reasonable approximation. The actual execution price (if the user executes manually) may differ slightly.

## Portfolio State (Per Agent)

```json
{
  "agent": "claude",
  "inception_date": "2026-04-21",
  "initial_capital": 100000,
  "current_cash": 100000,
  "last_eval_date": null,
  "positions": [
    {
      "ticker": "300750",
      "name": "宁德时代",
      "quantity": 100,
      "avg_cost": 185.50,
      "bought_date": "2026-04-28"
    }
  ],
  "trade_history": [
    {
      "eval_date": "2026-04-28",
      "action": "BUY",
      "ticker": "300750",
      "name": "宁德时代",
      "quantity": 100,
      "price": 185.50,
      "reason_summary": "新能源长期趋势 + Q1业绩催化"
    }
  ],
  "nav_history": [
    {"date": "2026-04-21", "nav": 100000, "cash_pct": 1.0, "position_count": 0, "benchmark_close": null}
  ]
}
```

### Source of Truth (C3 fix)

**Per-agent `portfolio_state.json` is the single source of truth** for that agent's history.

`track_record/nav_history.json` is a **derived file** — rebuilt by reading all `agents/*/portfolio_state.json` files and merging their `nav_history` arrays. It is regenerated at the end of every eval, never manually edited.

### NAV History Fields (enhanced for charting)

Each `nav_history` entry includes:
- `date` — evaluation date
- `nav` — total portfolio value
- `cash_pct` — percentage in cash
- `position_count` — number of holdings
- `benchmark_close` — CSI 300 close price
- `cumulative_return_pct` — computed at write time, avoids re-derivation

### Atomic Writes

`state.py` writes portfolio state via write-to-temp-then-rename:

```python
def save_state(agent_name: str, state: dict):
    path = f"agents/{agent_name}/portfolio_state.json"
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)  # atomic on POSIX
```

### Gap Handling

If an agent has no eval for one or more days (skipped, failed, or market closed):
- NAV is recomputed from current market prices on next eval
- No "phantom" entries are inserted for skipped days — `nav_history` only contains dates where an eval actually ran
- `track_record/nav_history.json` naturally handles gaps since it merges from per-agent data
- Comparison reports show "未评估" for agents missing from a given date

## Track Record

### nav_history.json (derived)

```json
[
  {
    "date": "2026-04-25",
    "benchmark": {"index": "000300.SH", "close": 3845.2, "cumulative_return_pct": 0.012},
    "agents": {
      "claude": {"nav": 100500, "cumulative_return_pct": 0.005, "cash_pct": 0.75, "position_count": 2},
      "gemini": {"nav": 99800, "cumulative_return_pct": -0.002, "cash_pct": 0.60, "position_count": 3}
    }
  }
]
```

Rebuilt from all `agents/*/portfolio_state.json` on every eval. Source of truth for charts and summaries.

### Comparison Report (`output/{date}.md`)

```markdown
# AI基金经理大乱斗｜{date}

| 选手 | 净值 | 今日收益 | 累计收益 | vs CSI300 |
|------|------|---------|---------|-----------|
| Claude | ¥100,500 | +0.50% | +0.50% | -0.70% |
| Gemini | ¥99,800 | -0.20% | -0.20% | -1.40% |
| CSI 300 | — | +1.20% | +1.20% | — |

## Claude 的判断
{claude_market_view}
### 操作
{claude_decisions}

## Gemini 的判断
{gemini_market_view}
### 操作
{gemini_decisions}

---
*多个AI独立决策，仅供娱乐和研究，不构成投资建议。*
```

Dynamically renders N agents — no hardcoding. Late-joining agents show "---" for dates before their inception.

## System Prompt

Shared template used by all agents. Identical input ensures fair competition on reasoning ability.

```
你是一位管理10万元人民币A股模拟组合的独立基金经理。你拥有完全的投资决策权。

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
{
  "eval_date": "YYYY-MM-DD",
  "market_view": "对当前市场的判断（2-3段文字）",
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
  "reflection": "对上期决策的回顾（基于简报中的上期回顾数据）",
  "note_to_audience": "写给观众的一段话，坦诚、有个性"
}

注意：eval_date 必须与简报日期一致。HOLD 表示继续持有现有仓位，不需要指定quantity。

【记忆】
{memory_content}

【当前持仓与业绩】
{portfolio_state}

【市场简报】
{market_briefing}

现在请做出本期投资决策。
```

## Reflection Mechanism

Reflection is **not a separate step** — it's embedded in the flow:

1. Each eval's briefing includes a "上期回顾" section showing the agent's last decisions and their actual outcomes (price changes, P&L)
2. The system prompt asks the agent to include a `reflection` field in its JSON output
3. The reflection text is stored in the trade journal alongside the decision
4. Over time, `investment_beliefs.md` is updated based on accumulated reflections (manually for Claude, via a summary prompt for API agents periodically)

This keeps reflection lightweight and avoids extra API calls.

## Dependencies

```
tushare>=1.4.0
akshare==1.14.85           # Pinned — AKShare breaks between versions
baostock
google-generativeai>=0.8.0
python-dotenv>=1.0.0
requests>=2.31.0
```

- `anthropic` removed (Claude operates via Claude Code session)
- `akshare` pinned to tested version (update deliberately after testing)

## Decision JSON Schema

All agents must output this exact schema. `parse_response()` handles provider-specific quirks (markdown fences, commentary, etc.).

```json
{
  "eval_date": "2026-04-17",
  "market_view": "string",
  "decisions": [
    {
      "action": "BUY | SELL | HOLD",
      "ticker": "string (6-digit code)",
      "name": "string (Chinese name)",
      "quantity": "integer, multiple of 100 (omit for HOLD)",
      "reason": {
        "thesis": "string",
        "catalyst": "string",
        "risk": "string",
        "invalidation": "string"
      }
    }
  ],
  "watchlist_updates": [
    {"ticker": "string", "name": "string", "note": "string"}
  ],
  "reflection": "string",
  "note_to_audience": "string"
}
```

## Future Considerations

- **Scheduling**: CoWork or `/loop` for automated daily runs
- **More agents**: DeepSeek, GPT, Qwen — just subclass + register
- **Charts**: Generate equity curves from `track_record/nav_history.json` (matplotlib or HTML)
- **小红书 formatting**: Summary mode for 4+ agents (table + one highlight each)
- **Claude Pro mode**: A variant where Claude gets extra web access beyond the shared briefing (opt-in, clearly labeled in reports)
