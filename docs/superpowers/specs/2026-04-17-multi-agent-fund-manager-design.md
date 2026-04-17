# Multi-Agent AI Fund Manager — Design Spec

## Overview

A multi-agent A-share simulated fund manager where multiple AI providers (Claude, Gemini, and future additions) independently manage separate ¥100,000 portfolios. Each agent receives identical market data and makes independent investment decisions. The comparison of their strategies and performance creates compelling content for social media (小红书).

## Constraints

- **No Anthropic API key**. Claude decisions are made interactively via Claude Code sessions.
- **Gemini API key available**. Gemini decisions are made programmatically.
- **Future providers** (DeepSeek, GPT, etc.) should be easy to add.
- **Data sources**: TuShare Pro (primary), AKShare (backup), BaoStock (fallback). TuShare has 5000 credits and 200 calls/min rate limit.
- **Storage**: Local JSON/Markdown files. No database.
- **Decision frequency**: Weekly (weekend analysis, Monday signals).

## Directory Structure

```
ai-fund-manager/
├── CLAUDE.md
├── README.md                      # User-facing instructions (including /decide workflow)
├── .env                           # TUSHARE_TOKEN, GEMINI_API_KEY
├── requirements.txt
├── run_weekly.py                  # Orchestrator: fetch data → run API agents → prep Claude briefing
├── apply_decision.py              # Apply a manually-produced decision (Claude Code flow)
├── src/
│   ├── data/
│   │   ├── tushare_client.py      # TuShare Pro wrapper with caching + rate limiting
│   │   ├── akshare_client.py      # AKShare fallback wrapper
│   │   ├── baostock_client.py     # BaoStock zero-config fallback
│   │   ├── market_briefing.py     # Assemble weekly market briefing from all sources
│   │   └── news_fetcher.py        # Scrape headlines from Eastmoney/Sina
│   ├── agents/
│   │   ├── base.py                # BaseAgent ABC: decide(), name, model info
│   │   ├── gemini_agent.py        # Calls Gemini API, returns JSON decision
│   │   ├── claude_agent.py        # Writes briefing file for Claude Code session
│   │   └── registry.py            # Discovers and configures active agents
│   ├── portfolio/
│   │   ├── state.py               # Read/write per-agent portfolio_state.json
│   │   └── performance.py         # NAV calculation, returns, vs CSI 300 benchmark
│   ├── guardrails.py              # Shared validation: ticker, lot size, T+1, position limits
│   ├── output/
│   │   ├── renderer.py            # JSON decision → Markdown weekly report
│   │   └── comparison.py          # Multi-agent comparison report
│   └── memory/
│       ├── manager.py             # Read/write agent memory files
│       └── reflection.py          # Post-decision reflection + lesson extraction
├── memory/                        # TEMPLATE — copied for each new agent on first run
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
│   ├── nav_history.json           # All agents' NAV time series [{week, date, agents: {name: {nav, return_pct}}}]
│   └── weekly_comparison/         # Side-by-side comparison reports
│       └── week_001.md
├── data_cache/                    # Cached API responses: data_cache/YYYY-MM-DD/*.json
└── output/                        # Final combined output for 小红书
    └── week_001.md
```

## Agent System

### BaseAgent Interface

```python
class BaseAgent(ABC):
    name: str           # e.g. "claude", "gemini"
    display_name: str   # e.g. "Claude (Opus)", "Gemini Pro"
    agent_type: str     # "interactive" or "api"

    @abstractmethod
    def decide(self, briefing: str, portfolio_state: dict, memory: dict) -> dict | None:
        """
        Returns a decision dict (same JSON schema for all agents), or None if
        the agent requires manual interaction (e.g. Claude Code).
        """
        ...
```

### Agent Types

**API agents** (Gemini, future DeepSeek/GPT): `decide()` calls the provider's API and returns the JSON decision directly. `run_weekly.py` handles these automatically.

**Interactive agents** (Claude): `decide()` writes the full briefing + prompt to `agents/claude/pending_briefing.md` and returns `None`. The user then runs a Claude Code session to produce the decision, and feeds it back via `apply_decision.py`.

### Adding a New Agent

1. Subclass `BaseAgent` in `src/agents/<provider>_agent.py`
2. Add the API key to `.env`
3. Register in `src/agents/registry.py`
4. Run `run_weekly.py` — it auto-initializes `agents/<name>/` from the `memory/` template

## Data Layer

### Market Briefing

`market_briefing.py` produces a single Markdown string consumed by all agents. Contents:

- **Index performance**: SSE Composite, SZSE Component, ChiNext, CSI 300 — last 5 trading days
- **Sector performance**: Shenwan L1 industry sectors, ranked by weekly return
- **Northbound flow**: Net buy/sell for the week
- **News digest**: 3-5 headline summaries from Eastmoney
- **Holdings update**: Current price and weekly return for each position held by the requesting agent

### Data Source Cascade

For each data point, try sources in order:
1. TuShare Pro (primary, most reliable)
2. AKShare (free, less stable)
3. BaoStock (zero-config, limited coverage)
4. Cached data from most recent successful fetch (last resort)

All API responses are cached to `data_cache/YYYY-MM-DD/` as JSON.

## Decision Flow

### Automated Path (API agents)

```
run_weekly.py
  → fetch market data (cached)
  → for each API agent:
      → load agent's portfolio state + memory
      → call agent.decide(briefing, state, memory)
      → validate decision through guardrails
      → if valid: update portfolio, record trade, generate report
      → if invalid: log errors, skip agent this week
  → update track_record/nav_history.json
  → generate comparison report
```

### Interactive Path (Claude)

```
run_weekly.py
  → fetch market data (cached)
  → write agents/claude/pending_briefing.md
  → print: "Claude briefing ready. Open Claude Code and follow README instructions."

User in Claude Code:
  → reads pending_briefing.md
  → produces JSON decision (guided by system prompt in the briefing)

python apply_decision.py claude
  → reads agents/claude/pending_decision.json (or stdin)
  → validates through guardrails
  → updates portfolio, records trade, generates report
  → updates track_record
  → regenerates comparison report if all agents have decided
```

## Guardrails (Shared)

All agents go through identical validation. Rules from CLAUDE.md:

| Rule | Value |
|------|-------|
| Max single position | 50% of portfolio |
| Max portfolio drawdown (halt) | -15% |
| Max single stock drawdown (review) | -20% |
| Max trades per week | 10 |
| Round lot | 100 shares |
| T+1 | Cannot sell same-day purchase |
| Min daily volume | ¥5M (exclude illiquid stocks) |

## Portfolio State (Per Agent)

```json
{
  "agent": "claude",
  "inception_date": "2026-04-21",
  "initial_capital": 100000,
  "current_cash": 100000,
  "positions": [
    {
      "ticker": "300750",
      "name": "宁德时代",
      "quantity": 100,
      "avg_cost": 185.50,
      "bought_date": "2026-04-28"
    }
  ],
  "trade_history": [],
  "week_number": 0,
  "nav_history": [
    {"date": "2026-04-21", "nav": 100000, "benchmark_close": null}
  ]
}
```

## Track Record

### nav_history.json

```json
[
  {
    "week": 1,
    "date": "2026-04-25",
    "benchmark": {"index": "000300.SH", "close": 3845.2, "return_pct": 0.012},
    "agents": {
      "claude": {"nav": 100500, "return_pct": 0.005, "trades": 2},
      "gemini": {"nav": 99800, "return_pct": -0.002, "trades": 3}
    }
  }
]
```

This is the source of truth for all charts and summaries. Raw, append-only.

### Weekly Comparison Report

Each week produces `output/week_NNN.md` combining all agents:

```markdown
# AI基金经理大乱斗·第{week}期｜{date}

| 选手 | 净值 | 本周收益 | 累计收益 | vs CSI300 |
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

## System Prompt

Shared template used by all agents (adapted from CLAUDE.md). The prompt is identical so agents compete on reasoning ability, not prompt engineering. Key sections:

- Role: independent fund manager, ¥100k A-share portfolio
- Decision framework: THESIS, CATALYST, RISK, SIZING, INVALIDATION
- Constraints: A-shares + ETF only, T+1, 100-share lots, public reasoning
- Output: structured JSON (same schema for all agents)
- Context injected: `{memory_content}`, `{portfolio_state}`, `{market_briefing}`

## Claude Code Workflow

The `pending_briefing.md` file written for Claude contains:
1. The full system prompt with all context injected
2. Instructions to output a JSON decision block
3. A note to save the output as `agents/claude/pending_decision.json`

README will document:
1. Run `python run_weekly.py`
2. Open Claude Code in the project directory
3. Copy the prompt from `agents/claude/pending_briefing.md` (or Claude Code reads it directly)
4. Claude outputs the decision JSON
5. Save to `agents/claude/pending_decision.json`
6. Run `python apply_decision.py claude`

## Dependencies

```
tushare>=1.4.0
akshare>=1.14.0
baostock
google-generativeai>=0.8.0
python-dotenv>=1.0.0
requests>=2.31.0
```

`anthropic` SDK removed (not needed — Claude operates via Claude Code sessions).
