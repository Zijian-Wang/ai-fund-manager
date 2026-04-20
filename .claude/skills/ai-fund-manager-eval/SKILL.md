---
name: ai-fund-manager-eval
description: Use when the user says "start this week's eval", "run eval", "do the fund manager check", or anything indicating the weekly ai-fund-manager evaluation. Drives the full eval end-to-end — fetch market data, freeze briefing, print the webchat prompt for manual agents (Claude/Gemini/GPT/Grok/DeepSeek/Kimi), ingest pasted JSON decisions, render reports.
---

# AI Fund Manager — Weekly Eval

Weekly rebalancing: run this on the first trading day of each ISO week.
The `weekly_cadence` guardrail rejects a second ingestion inside the
same week, so it's safe to trigger early or late in the day.

This skill runs one eval cycle. Most correctness-sensitive logic lives
in Python (`src/*`); this skill is the narrative layer.

## Before you start

- `cd` must be the project root (`/Users/zijian/Developer/ai-fund-manager`).
- `.venv/` exists. Use `.venv/bin/python` directly — no need to activate.
- `.env` has `TUSHARE_TOKEN`. Gemini/GPT/etc API keys are NOT required in
  manual mode (webchat handles those).

## Supported agents (manual mode)

Default agents to prompt the user to evaluate via webchat:
- **claude** (claude.ai)
- **gemini** (gemini.google.com)
- **gpt** (chat.openai.com)
- **grok** (grok.com)
- **deepseek** (chat.deepseek.com)
- **kimi** (kimi.com)

The user can skip any of these per run.

## Reset utility (before a fresh start)

If the user wants to wipe prior records and start over:

```bash
python scripts/reset_agents.py            # dry-run, lists what would go
python scripts/reset_agents.py --confirm  # actually delete
```

This keeps memory files and the market-data cache by default. Add
`--also-memory` or `--also-cache` for a deeper wipe.

## Step 1 — Ask which agents to include

Before fetching anything, ask:

> Which agents today? (default: all six)

Wait for the answer. Store the list as `AGENTS` for the rest of the run.
If the user says "all" or just presses enter, use all six.

## Step 2 — Fetch market data + freeze briefing

Run this Python inline (adjust `AGENTS` to the chosen list):

```bash
.venv/bin/python <<'PY'
from pathlib import Path
import os, json
from datetime import date, timedelta
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(".env"))

from src.data.tushare_client import TuShareClient
from src.data.akshare_client import AKShareClient
from src.data.baostock_client import BaoStockClient
from src.data.eval_date import resolve_eval_date
from src.data.market_data import fetch_market_data
from src.data.news_fetcher import fetch_news
from src.briefing import build_shared_briefing
from src.data.cache import cache_dir_for
from src.portfolio.state import load_state, init_agent_state

cache_root = Path("data_cache")
tushare = TuShareClient(token=os.environ["TUSHARE_TOKEN"], cache_root=cache_root)
akshare = AKShareClient()
baostock = BaoStockClient()

# Refresh trade calendar (covers this year + 60d lookahead)
today = date.today()
tushare.trade_cal_refresh(
    start_date=today.replace(month=1, day=1).strftime("%Y%m%d"),
    end_date=(today + timedelta(days=60)).strftime("%Y%m%d"),
)

eval_date = resolve_eval_date(cache_root=cache_root)
iso = date.fromisoformat(eval_date).isocalendar()
print(f"eval_date = {eval_date}  (ISO week {iso.year}-W{iso.week:02d})")

# Init state for every chosen agent, collect holdings
AGENTS = ["claude", "gemini", "gpt", "grok", "deepseek", "kimi"]  # TODO: replace per user choice
agents_root = Path("agents")
all_holdings = set()
for name in AGENTS:
    st = init_agent_state(
        agent_name=name, agents_root=agents_root,
        template_root=Path("memory_template"), inception_date=eval_date,
    )
    for pos in st.get("positions", []):
        tk = pos["ticker"]
        suffix = ".SH" if tk.startswith(("5","6")) else ".BJ" if tk.startswith(("4","8")) else ".SZ"
        all_holdings.add(f"{tk}{suffix}")

market_data = fetch_market_data(
    eval_date=eval_date, holdings_tickers=list(all_holdings),
    cache_root=cache_root, tushare=tushare, akshare=akshare, baostock=baostock,
)
news = fetch_news(limit=20)

shared = build_shared_briefing(market_data, news)
briefing_path = cache_dir_for(cache_root, eval_date) / "briefing.md"
briefing_path.write_text(shared, encoding="utf-8")
print(f"✓ briefing frozen at {briefing_path}")
print(f"  indices: {len(market_data['indices'])}, sector rows: {len(market_data['sector_ranking']['rows'])}, news: {len(news)}")
PY
```

**On re-run (idempotency):** if ALL chosen agents have
`last_eval_date` inside the same ISO week as `eval_date`, stop with
"本周评估已完成". The `weekly_cadence` guardrail will also reject any
late arrival. If only some agents are done, continue with the missing
ones.

## Step 3 — Print the paste-me-into-webchat prompt

For each webchat agent, the prompt is identical (same briefing, same
portfolio state, same memory — just per-agent's state). Build and show:

```bash
.venv/bin/python <<'PY'
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(".env"))
import json, os
from src.data.tushare_client import TuShareClient
from src.data.akshare_client import AKShareClient
from src.data.baostock_client import BaoStockClient
from src.data.market_data import (
    fetch_market_data, extract_index_close, extract_stock_prices,
)
from src.briefing import build_agent_briefing, build_full_prompt
from src.portfolio.state import (
    load_state, load_agent_memory, load_prev_decision,
)

AGENTS = ["claude", "gemini", "gpt", "grok", "deepseek", "kimi"]  # per user choice
cache_root = Path("data_cache"); agents_root = Path("agents")
eval_date = "<INSERT eval_date>"

shared = (cache_root / eval_date / "briefing.md").read_text(encoding="utf-8")
tushare = TuShareClient(token=os.environ["TUSHARE_TOKEN"], cache_root=cache_root)
akshare = AKShareClient(); baostock = BaoStockClient()
market_data = fetch_market_data(
    eval_date=eval_date, holdings_tickers=[],
    cache_root=cache_root, tushare=tushare, akshare=akshare, baostock=baostock,
)
current_prices = extract_stock_prices(market_data)
benchmark_close = extract_index_close(market_data, "000300.SH")

for name in AGENTS:
    state = load_state(agent_name=name, agents_root=agents_root)
    prev = load_prev_decision(state=state, agent_name=name, agents_root=agents_root)
    incep = state["nav_history"][0].get("benchmark_close") if state["nav_history"] else None
    agent_briefing = build_agent_briefing(
        shared=shared, agent_name=name, state=state, prev_decision=prev,
        current_prices=current_prices, benchmark_close=benchmark_close,
        inception_benchmark_close=incep,
    )
    mem = load_agent_memory(agent_name=name, agents_root=agents_root)
    memory_text = "\n\n".join(f"# {k}\n{v}" for k, v in mem.items())
    portfolio_text = json.dumps({
        "current_cash": state["current_cash"],
        "positions": state["positions"],
        "last_eval_date": state["last_eval_date"],
    }, ensure_ascii=False, indent=2)
    full_prompt = build_full_prompt(
        memory_text=memory_text, portfolio_text=portfolio_text,
        market_briefing=agent_briefing,
    )
    out = cache_root / eval_date / f"prompt_{name}.txt"
    out.write_text(full_prompt, encoding="utf-8")
    print(f"  {name}: data_cache/{eval_date}/prompt_{name}.txt ({len(full_prompt)} bytes)")
PY
```

Then tell the user:

> Prompts written to `data_cache/{eval_date}/prompt_<agent>.txt`. Open each
> in your browser's webchat. You can also use a single shared prompt if
> all portfolios are identical (first eval). Paste the AI's JSON back here
> labeled like `gemini: {...}`, or tell me to read it from a file.

## Step 4 — Ingest each decision

When the user pastes a JSON response (or tells you to read it from a
file), ingest it. For each agent one by one:

```bash
.venv/bin/python <<'PY'
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(".env"))
import json, os
from src.data.tushare_client import TuShareClient
from src.data.akshare_client import AKShareClient
from src.data.baostock_client import BaoStockClient
from src.data.market_data import (
    fetch_market_data, extract_index_close, extract_stock_prices,
    extract_stock_volumes_yuan, get_valid_tickers, fetch_stock_5d,
)
from src.agents.base import extract_json
from src.apply import apply_agent_decision
from src.portfolio.state import load_state, save_state, save_trade_journal

AGENT_NAME = "<NAME>"   # e.g. "gemini"
eval_date = "<EVAL_DATE>"
RAW = r'''<PASTE RAW JSON HERE>'''

cache_root = Path("data_cache"); agents_root = Path("agents")
decision = extract_json(RAW)

tushare = TuShareClient(token=os.environ["TUSHARE_TOKEN"], cache_root=cache_root)
akshare = AKShareClient(); baostock = BaoStockClient()
market_data = fetch_market_data(
    eval_date=eval_date, holdings_tickers=[],
    cache_root=cache_root, tushare=tushare, akshare=akshare, baostock=baostock,
)
current_prices = extract_stock_prices(market_data)
benchmark_close = extract_index_close(market_data, "000300.SH")
valid_tickers = get_valid_tickers(cache_root=cache_root, tushare=tushare)
volumes = extract_stock_volumes_yuan(market_data)

# Pre-fetch price/volume for BUY tickers not in holdings
def _suffix(tk):
    # A-share exchange routing for 6-digit symbols:
    #   5xx / 6xx (incl. 688 STAR, 5xx ETFs)      → Shanghai
    #   4xx / 8xx (Beijing Exchange)               → Beijing
    #   else: 0xx/1xx/3xx (stocks + 159xxx ETFs)   → Shenzhen
    if tk.startswith(("5","6")): return ".SH"
    if tk.startswith(("4","8")): return ".BJ"
    return ".SZ"
for d in decision.get("decisions", []):
    if d.get("action") != "BUY": continue
    tk = d.get("ticker", "")
    if tk in current_prices: continue
    try:
        block = fetch_stock_5d(
            ts_code=f"{tk}{_suffix(tk)}",
            eval_date=eval_date, cache_root=cache_root,
            tushare=tushare, baostock=baostock,
        )
        rows = block.get("rows") or []
        if rows and rows[0].get("close"):
            current_prices[tk] = float(rows[0]["close"])
        if rows and rows[0].get("amount"):
            volumes[tk] = float(rows[0]["amount"]) * 1000
    except Exception as exc:
        print(f"  fetch {tk} failed: {exc}")

state = load_state(agent_name=AGENT_NAME, agents_root=agents_root)
new_state, errors = apply_agent_decision(
    decision=decision, state=state, eval_date=eval_date,
    current_prices=current_prices, valid_tickers=valid_tickers,
    ticker_volumes_yuan=volumes, benchmark_close=benchmark_close,
)

# Always save trade_journal (audit trail)
save_trade_journal(
    agent_name=AGENT_NAME, eval_date=eval_date,
    decision=decision, agents_root=agents_root,
)

if errors:
    print(f"{AGENT_NAME}: REJECTED — {len(errors)} errors")
    for e in errors[:5]:
        print(f"  [{e.rule}] {e.message}")
else:
    save_state(agent_name=AGENT_NAME, state=new_state, agents_root=agents_root)
    buys = sum(1 for d in decision["decisions"] if d.get("action") == "BUY")
    sells = sum(1 for d in decision["decisions"] if d.get("action") == "SELL")
    holds = sum(1 for d in decision["decisions"] if d.get("action") == "HOLD")
    print(f"{AGENT_NAME}: ✓ applied ({buys} buys, {sells} sells, {holds} holds)")
    print(f"  cash=¥{new_state['current_cash']:,.0f}, positions={len(new_state['positions'])}")
PY
```

Summarize to the user after each: agent, pass/fail, trades, errors.

## Step 5 — Render reports

Once the user has ingested everyone they want (or says "that's it"):

```bash
.venv/bin/python <<'PY'
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(".env"))
import os
from src.data.tushare_client import TuShareClient
from src.data.akshare_client import AKShareClient
from src.data.baostock_client import BaoStockClient
from src.data.market_data import (
    fetch_market_data, extract_index_close, extract_stock_prices,
)
from src.data.cache import read_json
from src.portfolio.state import load_state
from src.portfolio.performance import rebuild_track_record, compute_nav
from src.output.renderer import render_agent_report
from src.output.comparison import render_comparison_report

AGENTS = ["claude", "gemini", "gpt", "grok", "deepseek", "kimi"]
eval_date = "<EVAL_DATE>"
cache_root = Path("data_cache"); agents_root = Path("agents")

tushare = TuShareClient(token=os.environ["TUSHARE_TOKEN"], cache_root=cache_root)
akshare = AKShareClient(); baostock = BaoStockClient()
market_data = fetch_market_data(
    eval_date=eval_date, holdings_tickers=[],
    cache_root=cache_root, tushare=tushare, akshare=akshare, baostock=baostock,
)
current_prices = extract_stock_prices(market_data)
benchmark_close = extract_index_close(market_data, "000300.SH")

Path("track_record").mkdir(exist_ok=True)
rebuild_track_record(
    agents_root=agents_root,
    output_path=Path("track_record") / "nav_history.json",
)

DISPLAY_NAMES = {
    "claude": "Claude (webchat)", "gemini": "Gemini 2.5 Pro",
    "gpt": "GPT-5", "grok": "Grok 4", "deepseek": "DeepSeek V3",
    "kimi": "Kimi K2",
}
agent_entries, metrics_agents = {}, {}
for name in AGENTS:
    state = load_state(agent_name=name, agents_root=agents_root)
    decision = read_json(agents_root / name / "trade_journal" / f"{eval_date}.json")
    display = DISPLAY_NAMES.get(name, name)
    if decision is not None:
        nav = compute_nav(state, current_prices=current_prices)
        report = render_agent_report(
            display_name=display, decision=decision, state=state,
            current_prices=current_prices, nav=nav, benchmark_close=benchmark_close,
            inception_benchmark_close=(
                state["nav_history"][0].get("benchmark_close")
                if state["nav_history"] else None
            ),
        )
        out = agents_root / name / "output" / f"{eval_date}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
    agent_entries[name] = {"display_name": display, "decision": decision}
    if state["nav_history"]:
        latest = state["nav_history"][-1]
        prev = state["nav_history"][-2] if len(state["nav_history"]) >= 2 else None
        today_pct = (
            (latest["nav"] - prev["nav"]) / prev["nav"] * 100
            if prev and prev["nav"] else 0.0
        )
        metrics_agents[name] = {
            "nav": latest["nav"], "today_pct": today_pct,
            "cumulative_pct": latest["cumulative_return_pct"] * 100,
            "position_count": latest["position_count"],
        }

inception_bench = None
for name in AGENTS:
    try:
        s = load_state(agent_name=name, agents_root=agents_root)
        if s.get("nav_history") and s["nav_history"][0].get("benchmark_close"):
            inception_bench = s["nav_history"][0]["benchmark_close"]; break
    except FileNotFoundError: pass
bench_cum = (
    (benchmark_close - inception_bench) / inception_bench * 100
    if inception_bench else 0.0
)
idx_rows = market_data["indices"].get("000300.SH", {}).get("rows") or []
bench_today = float(idx_rows[0].get("pct_chg", 0) or 0) if idx_rows else 0.0

comparison = render_comparison_report(
    metrics={
        "eval_date": eval_date,
        "benchmark": {"index": "000300.SH", "close": benchmark_close,
                      "today_pct": bench_today, "cumulative_pct": bench_cum},
        "agents": metrics_agents,
    },
    agent_entries=agent_entries,
)
out_path = Path("output") / f"{eval_date}.md"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(comparison, encoding="utf-8")
print(f"✓ {eval_date}")
print(f"  对比报告：{out_path}")
for name in AGENTS:
    p = agents_root / name / "output" / f"{eval_date}.md"
    if p.exists(): print(f"  {name}: {p}")
PY
```

## Minimum-failure behavior

- **TuShare down:** cache fallback kicks in; `briefing` may have stale
  data but still renders. Note it to the user and proceed.
- **Single agent ingest fails:** log and continue with the rest. That
  agent shows `未评估` in the comparison report.
- **Guardrail rejects decision:** `trade_journal` still saved for
  audit; no state change. User can re-prompt the agent if they want a
  retry, or accept and move on.
- **Session crash mid-run:** safe to restart — frozen briefing on disk,
  idempotent state transitions, agents that already completed are
  skipped by the idempotency check in `apply_agent_decision`.
