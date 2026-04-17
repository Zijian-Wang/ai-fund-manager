# Phase 3 — Orchestration + Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Phase 1 (data) and Phase 2 (agents/portfolio/briefing/guardrails) into a runnable eval loop. Add the glue helpers (price extraction, trade journal I/O, memory loading), the two Markdown renderers (per-agent + multi-agent comparison), the Claude decision-subagent definition for technically-enforced fairness, and the runbook in `CLAUDE.md` that Claude Code follows when the user says "start today's eval".

**Architecture:**
- **Orchestration lives in `CLAUDE.md`**, not in a Python `run_eval.py` script. Claude Code *is* the pipeline; it calls the Python helpers in order per the runbook.
- **Claude's decision is made by an isolated Claude Code subagent** spawned via the `Agent` tool with a custom `subagent_type` (`fund-manager-claude`). It receives ONLY the frozen briefing + portfolio state + memory as part of its prompt — no web tools, no session context, no knowledge of other agents' output. This is the technical fairness guarantee.
- **API agents** (Gemini) are called via their Python classes (`src/agents/gemini_agent.py`) — fast, no subagent overhead, same information.
- **Output is two Markdown files per eval**: `agents/<name>/output/{eval_date}.md` (per-agent, rich) and `output/{eval_date}.md` (multi-agent comparison, for 小红书).

**Tech Stack:** Python 3.11+ (we're on 3.14), `pytest`. Reuses all Phase 1+2 modules unchanged.

**Spec reference:** `docs/superpowers/specs/2026-04-17-multi-agent-fund-manager-design.md` — Sections "Orchestration Flow", "Briefing Format", "Comparison Report", "Fairness Protocol".

**Assumes Phase 1 + 2 shipped:**
- Data layer (TuShare/AKShare/BaoStock, market_data orchestrator, news_fetcher, eval_date resolver, cache utilities) — ✅
- Agent system (BaseAgent + AgentResult, GeminiAgent, registry) — ✅
- Portfolio (state I/O, apply_buy/sell, performance metrics, track_record rebuild) — ✅
- Guardrails (9 rules incl. idempotency) — ✅
- Briefing (shared + per-agent + system prompt template) — ✅

---

## Conventions

- All paths relative to repo root `/Users/zijian/Developer/ai-fund-manager/`.
- All `pytest` commands run from repo root.
- Each task ends with one commit using the suggested message verbatim unless noted.
- Tests use `unittest.mock` (stdlib). No `pytest-mock` needed.
- For any new module, tests live at `tests/<same-path>/test_<name>.py`.

**min_volume tech-debt note:** guardrail's `min_volume` rule skips when `ticker_volumes_yuan` isn't provided. Task 9 (runbook) specifies that the orchestrator pre-fetches daily amount for every BUY ticker in a decision and passes it to `validate_decision`. With that, the rule becomes fully enforced without changing guardrails.py.

---

## File Map

### New files

| Path | Responsibility |
|------|----------------|
| `tests/output/__init__.py` | Marks package |
| `src/output/__init__.py` | Marks package |
| `src/output/renderer.py` | Per-agent Markdown report from decision + state |
| `tests/output/test_renderer.py` | |
| `src/output/comparison.py` | Multi-agent comparison report |
| `tests/output/test_comparison.py` | |
| `.claude/agents/fund-manager-claude.md` | Claude decision-subagent definition (restricted tools, dedicated system prompt) |
| `README.md` | User-facing setup + usage |

### Modified files

| Path | Change |
|------|--------|
| `src/data/market_data.py` | Add `extract_stock_prices`, `extract_index_close`, `extract_stock_volumes_yuan` helpers |
| `tests/data/test_market_data.py` | Tests for the three helpers |
| `src/portfolio/state.py` | Add `save_trade_journal`, `load_prev_decision`, `load_agent_memory` |
| `tests/portfolio/test_state.py` | Tests for the three helpers |
| `src/agents/base.py` | Extract `extract_json` to module-level (reused by Claude subagent output parsing); `BaseAgent.parse_response` calls it |
| `tests/agents/test_base.py` | Keep existing tests green; the module-level function is already exercised |
| `CLAUDE.md` | Append "评估流程" runbook with numbered steps + exact Python calls + subagent spawn instructions |

### Files NOT touched in Phase 3

- Every file under `src/data/` except `market_data.py`
- Every file under `src/agents/` except `base.py`
- `src/portfolio/performance.py`, `src/guardrails.py`, `src/briefing.py`
- `memory_template/*`

---

## Task 1: Scaffolding — output package + Claude subagent dir

**Files:**
- Create: `src/output/__init__.py` (empty)
- Create: `tests/output/__init__.py` (empty)
- Create: `.claude/agents/` (directory; file added in Task 8)

- [ ] **Step 1: Create package markers**

```bash
mkdir -p /Users/zijian/Developer/ai-fund-manager/src/output /Users/zijian/Developer/ai-fund-manager/tests/output /Users/zijian/Developer/ai-fund-manager/.claude/agents
touch /Users/zijian/Developer/ai-fund-manager/src/output/__init__.py /Users/zijian/Developer/ai-fund-manager/tests/output/__init__.py
```

- [ ] **Step 2: Verify pytest still green**

Run: `.venv/bin/pytest`
Expected: `157 passed, 1 warning in 0.X s`

- [ ] **Step 3: Commit**

```bash
git add src/output tests/output
git commit -m "chore(output): scaffold output package + subagent dir for phase 3"
```

(`.claude/agents/` directory is created but empty — git won't track it yet. Task 8 adds the first file.)

---

## Task 2: Price + volume extraction helpers in `market_data.py`

**Files:**
- Modify: `src/data/market_data.py`
- Modify: `tests/data/test_market_data.py`

**Background:** Downstream (briefing, guardrails, reports) needs quick-access maps from the unified market data dict. Three helpers:
- `extract_stock_prices(market_data) -> dict[str, float]` — key = 6-digit symbol (e.g. `"300750"`), value = latest close
- `extract_index_close(market_data, ts_code) -> float | None` — latest close of the named index (e.g. `"000300.SH"`)
- `extract_stock_volumes_yuan(market_data) -> dict[str, float]` — key = 6-digit symbol, value = latest daily amount (¥, converted from TuShare's 千元 unit)

All three use `market_data["holdings"]` / `market_data["indices"]` with the same shape Phase 1 produces.

- [ ] **Step 1: Write failing tests**

Append to `tests/data/test_market_data.py`:

```python
from src.data.market_data import (
    extract_index_close,
    extract_stock_prices,
    extract_stock_volumes_yuan,
)


def test_extract_stock_prices_strips_suffix():
    md = {
        "holdings": {
            "300750.SZ": {"source": "tushare", "rows": [
                {"trade_date": "20260417", "close": 192.30, "amount": 5_000_000}
            ]},
            "000001.SZ": {"source": "tushare", "rows": [
                {"trade_date": "20260417", "close": 12.50, "amount": 1_000_000}
            ]},
        },
    }
    prices = extract_stock_prices(md)
    assert prices == {"300750": 192.30, "000001": 12.50}


def test_extract_stock_prices_skips_empty_rows():
    md = {
        "holdings": {
            "300750.SZ": {"source": "error", "rows": []},
            "000001.SZ": {"source": "tushare", "rows": [
                {"trade_date": "20260417", "close": 12.50}
            ]},
        },
    }
    prices = extract_stock_prices(md)
    assert prices == {"000001": 12.50}


def test_extract_index_close_returns_latest():
    md = {
        "indices": {
            "000300.SH": {"source": "tushare", "rows": [
                {"trade_date": "20260417", "close": 4728.67},
                {"trade_date": "20260416", "close": 4736.61},
            ]},
        },
    }
    assert extract_index_close(md, "000300.SH") == 4728.67


def test_extract_index_close_returns_none_when_missing():
    md = {"indices": {"000300.SH": {"source": "error", "rows": []}}}
    assert extract_index_close(md, "000300.SH") is None
    assert extract_index_close({}, "000300.SH") is None


def test_extract_stock_volumes_yuan_converts_from_qianyuan():
    """TuShare's `amount` field is 千元; return it as ¥."""
    md = {
        "holdings": {
            "300750.SZ": {"source": "tushare", "rows": [
                # 5000 千元 = ¥5,000,000
                {"trade_date": "20260417", "close": 192.30, "amount": 5000}
            ]},
        },
    }
    vols = extract_stock_volumes_yuan(md)
    assert vols == {"300750": 5_000_000.0}


def test_extract_stock_volumes_yuan_skips_when_amount_missing():
    md = {
        "holdings": {
            "300750.SZ": {"source": "baostock", "rows": [
                # BaoStock doesn't always have amount
                {"date": "2026-04-17", "close": 192.30}
            ]},
        },
    }
    assert extract_stock_volumes_yuan(md) == {}
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/pytest tests/data/test_market_data.py -v`
Expected: ImportError on the three new names.

- [ ] **Step 3: Implement**

Append to `src/data/market_data.py` (below `get_valid_tickers`):

```python
def extract_stock_prices(market_data: dict) -> dict[str, float]:
    """Return {six_digit_symbol: latest_close} from market_data.holdings."""
    out: dict[str, float] = {}
    for ts_code, block in (market_data.get("holdings") or {}).items():
        rows = block.get("rows") or []
        if not rows:
            continue
        close = rows[0].get("close")
        if close is None:
            continue
        try:
            out[ts_code.split(".")[0]] = float(close)
        except (TypeError, ValueError):
            pass
    return out


def extract_index_close(market_data: dict, ts_code: str) -> float | None:
    """Return the latest close for ``ts_code`` (e.g. '000300.SH'), or None."""
    block = (market_data.get("indices") or {}).get(ts_code)
    if not block:
        return None
    rows = block.get("rows") or []
    if not rows:
        return None
    close = rows[0].get("close")
    if close is None:
        return None
    try:
        return float(close)
    except (TypeError, ValueError):
        return None


def extract_stock_volumes_yuan(market_data: dict) -> dict[str, float]:
    """Return {six_digit_symbol: latest_daily_amount_in_yuan}.

    TuShare's ``amount`` column is in 千元; we multiply by 1000 to get ¥.
    Skips tickers where amount is absent (e.g. BaoStock fallback rows
    without amount). Orchestrator passes this to guardrails to enforce
    the min_volume rule.
    """
    out: dict[str, float] = {}
    for ts_code, block in (market_data.get("holdings") or {}).items():
        rows = block.get("rows") or []
        if not rows:
            continue
        amount = rows[0].get("amount")
        if amount is None:
            continue
        try:
            out[ts_code.split(".")[0]] = float(amount) * 1000
        except (TypeError, ValueError):
            pass
    return out
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/pytest tests/data/test_market_data.py -v`
Expected: all tests pass (prior + 6 new).

- [ ] **Step 5: Commit**

```bash
git add src/data/market_data.py tests/data/test_market_data.py
git commit -m "feat(data): add price/volume extraction helpers

extract_stock_prices and extract_index_close give downstream consumers
(briefing, reports) a ticker->price map. extract_stock_volumes_yuan
converts TuShare's 千元 unit to ¥ so guardrails can enforce min_volume."
```

---

## Task 3: Trade journal + prev-decision helpers in `state.py`

**Files:**
- Modify: `src/portfolio/state.py`
- Modify: `tests/portfolio/test_state.py`

**Background:** The trade journal is `agents/<name>/trade_journal/{eval_date}.json` — per-eval, one file each. The briefing's 上期回顾 reads this to show what the agent did last time.

- [ ] **Step 1: Write failing tests**

Append to `tests/portfolio/test_state.py`:

```python
from src.portfolio.state import (
    load_prev_decision,
    save_trade_journal,
)


def test_save_trade_journal_writes_dated_file(template_root, agents_root):
    init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-17",
    )
    decision = {"eval_date": "2026-04-17", "market_view": "neutral", "decisions": []}
    save_trade_journal(
        agent_name="gemini",
        eval_date="2026-04-17",
        decision=decision,
        agents_root=agents_root,
    )
    path = agents_root / "gemini" / "trade_journal" / "2026-04-17.json"
    assert path.exists()
    import json
    assert json.loads(path.read_text(encoding="utf-8")) == decision


def test_save_trade_journal_creates_dir_if_missing(agents_root, tmp_path):
    # Bypass init — test that the helper creates trade_journal/ on demand
    (agents_root / "newbie").mkdir()
    decision = {"eval_date": "2026-04-17", "decisions": []}
    save_trade_journal(
        agent_name="newbie",
        eval_date="2026-04-17",
        decision=decision,
        agents_root=agents_root,
    )
    assert (agents_root / "newbie" / "trade_journal" / "2026-04-17.json").exists()


def test_load_prev_decision_returns_entry_matching_last_eval_date(
    template_root, agents_root
):
    init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-10",
    )
    prev = {"eval_date": "2026-04-10", "decisions": [
        {"action": "BUY", "ticker": "300750", "name": "宁德时代",
         "quantity": 100, "reason": {}}
    ]}
    save_trade_journal(
        agent_name="gemini",
        eval_date="2026-04-10",
        decision=prev,
        agents_root=agents_root,
    )
    state = load_state(agent_name="gemini", agents_root=agents_root)
    state["last_eval_date"] = "2026-04-10"

    got = load_prev_decision(state=state, agent_name="gemini", agents_root=agents_root)
    assert got == prev


def test_load_prev_decision_returns_none_when_no_prior_eval(
    template_root, agents_root
):
    init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-17",
    )
    state = load_state(agent_name="gemini", agents_root=agents_root)
    # last_eval_date is None — first eval
    assert load_prev_decision(
        state=state, agent_name="gemini", agents_root=agents_root
    ) is None


def test_load_prev_decision_returns_none_when_file_missing(
    template_root, agents_root
):
    init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-10",
    )
    state = load_state(agent_name="gemini", agents_root=agents_root)
    state["last_eval_date"] = "2026-04-99"  # file doesn't exist
    assert load_prev_decision(
        state=state, agent_name="gemini", agents_root=agents_root
    ) is None
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/pytest tests/portfolio/test_state.py -v`
Expected: ImportError on `save_trade_journal`, `load_prev_decision`.

- [ ] **Step 3: Implement**

Append to `src/portfolio/state.py`:

```python
def _trade_journal_path(
    agent_name: str, eval_date: str, agents_root: Path
) -> Path:
    return Path(agents_root) / agent_name / "trade_journal" / f"{eval_date}.json"


def save_trade_journal(
    *,
    agent_name: str,
    eval_date: str,
    decision: dict,
    agents_root: Path,
) -> None:
    """Write the raw decision to ``agents/<name>/trade_journal/{eval_date}.json``.

    Creates the trade_journal/ dir if it doesn't exist. Atomic write.
    """
    path = _trade_journal_path(agent_name, eval_date, agents_root)
    write_json_atomic(path, decision)


def load_prev_decision(
    *,
    state: dict,
    agent_name: str,
    agents_root: Path,
) -> dict | None:
    """Return the agent's previous decision (keyed by state['last_eval_date']).

    Returns None on first eval (last_eval_date is None) or if the file
    doesn't exist (e.g. the prior eval errored before save).
    """
    last = state.get("last_eval_date")
    if not last:
        return None
    return read_json(_trade_journal_path(agent_name, last, agents_root))
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/pytest tests/portfolio/test_state.py -v`
Expected: all tests pass (12 prior + 5 new = 17).

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/state.py tests/portfolio/test_state.py
git commit -m "feat(portfolio): add trade journal save + prev-decision load

save_trade_journal writes agents/<name>/trade_journal/{eval_date}.json
(atomic). load_prev_decision reads the entry matching state.last_eval_date
for the briefing's 上期回顾 section."
```

---

## Task 4: Memory loader helper in `state.py`

**Files:**
- Modify: `src/portfolio/state.py`
- Modify: `tests/portfolio/test_state.py`

**Background:** Each agent has `agents/<name>/investment_beliefs.md`, `market_regime.md`, `watchlist.json`. The agent needs these as a dict for `decide()`. The helper reads all top-level files (skipping `portfolio_state.json` and directories like `trade_journal/`) and returns `{basename: content}`.

- [ ] **Step 1: Write failing tests**

Append to `tests/portfolio/test_state.py`:

```python
from src.portfolio.state import load_agent_memory


def test_load_agent_memory_reads_md_and_json_files(template_root, agents_root):
    # Seed the template with the memory files the spec describes
    (template_root / "investment_beliefs.md").write_text(
        "# 投资信念\n\nbuy low sell high", encoding="utf-8"
    )
    (template_root / "market_regime.md").write_text(
        "# 市场体制\n\nbull market", encoding="utf-8"
    )
    (template_root / "watchlist.json").write_text(
        '{"watchlist": []}', encoding="utf-8"
    )
    (template_root / "trade_journal").mkdir()

    init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-17",
    )
    memory = load_agent_memory(agent_name="gemini", agents_root=agents_root)
    assert "investment_beliefs" in memory
    assert memory["investment_beliefs"].startswith("# 投资信念")
    assert "market_regime" in memory
    assert "watchlist" in memory


def test_load_agent_memory_excludes_portfolio_state_and_dirs(
    template_root, agents_root
):
    (template_root / "investment_beliefs.md").write_text("...", encoding="utf-8")
    (template_root / "trade_journal").mkdir()
    (template_root / "lessons").mkdir()
    init_agent_state(
        agent_name="gemini",
        agents_root=agents_root,
        template_root=template_root,
        inception_date="2026-04-17",
    )
    memory = load_agent_memory(agent_name="gemini", agents_root=agents_root)
    # portfolio_state is structured state, not memory
    assert "portfolio_state" not in memory
    # Directories aren't memory entries
    assert "trade_journal" not in memory
    assert "lessons" not in memory


def test_load_agent_memory_returns_empty_when_agent_dir_missing(agents_root):
    memory = load_agent_memory(agent_name="noone", agents_root=agents_root)
    assert memory == {}
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/pytest tests/portfolio/test_state.py -v`
Expected: ImportError on `load_agent_memory`.

- [ ] **Step 3: Implement**

Append to `src/portfolio/state.py`:

```python
_MEMORY_EXCLUDE_NAMES = {"portfolio_state", "portfolio_state.json"}
_MEMORY_INCLUDE_SUFFIXES = {".md", ".json", ".txt"}


def load_agent_memory(*, agent_name: str, agents_root: Path) -> dict[str, str]:
    """Return {basename: file_content} for the agent's memory files.

    Includes top-level .md / .json / .txt files. Excludes portfolio_state.json
    (that's state, not memory) and directories like trade_journal/.
    """
    agent_dir = Path(agents_root) / agent_name
    if not agent_dir.is_dir():
        return {}

    memory: dict[str, str] = {}
    for entry in sorted(agent_dir.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix not in _MEMORY_INCLUDE_SUFFIXES:
            continue
        if entry.stem in _MEMORY_EXCLUDE_NAMES or entry.name in _MEMORY_EXCLUDE_NAMES:
            continue
        memory[entry.stem] = entry.read_text(encoding="utf-8")
    return memory
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/pytest tests/portfolio/test_state.py -v`
Expected: 3 more passing.

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/state.py tests/portfolio/test_state.py
git commit -m "feat(portfolio): add load_agent_memory helper

Reads agents/<name>/*.{md,json,txt} (excluding portfolio_state.json and
subdirs) into a {basename: content} dict for the agent's decide() call."
```

---

## Task 5: Promote `extract_json` to module-level in `agents/base.py`

**Files:**
- Modify: `src/agents/base.py`
- Verify: `tests/agents/test_base.py` (existing tests continue to pass; no new tests required but add one for the module-level function)

**Background:** The Claude subagent (Task 8 + 9) returns raw text from the `Agent` tool call. We need to parse the JSON out of it using the same logic as `BaseAgent.parse_response`. Promote the logic to a module-level function `extract_json(raw: str) -> dict` and have `BaseAgent.parse_response` call it. No behavior change; pure refactor.

- [ ] **Step 1: Add a direct test for the module-level function**

Append to `tests/agents/test_base.py`:

```python
from src.agents.base import extract_json


def test_extract_json_module_function_works_standalone():
    assert extract_json('{"action": "BUY"}') == {"action": "BUY"}


def test_extract_json_module_function_handles_markdown_fence():
    assert extract_json('```json\n{"x": 1}\n```') == {"x": 1}


def test_extract_json_module_function_raises_on_no_json():
    with pytest.raises(ValueError):
        extract_json("plain text")
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/pytest tests/agents/test_base.py -v`
Expected: ImportError on `extract_json`.

- [ ] **Step 3: Refactor `base.py`**

Edit `src/agents/base.py`. Keep the current module content, but:
1. Move the body of `BaseAgent.parse_response` into a new module-level function `extract_json(raw: str) -> dict`.
2. Make `BaseAgent.parse_response(self, raw)` a one-line call to `extract_json(raw)`.

Full replacement for the relevant section:

```python
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

    start = raw.find("{")
    if start == -1:
        raise ValueError("no JSON object found in response")
    depth = 0
    in_string = False
    escaped = False
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
                candidate = raw[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"JSON parse failed: {exc.msg} in {candidate[:80]!r}"
                    ) from exc
    raise ValueError("unbalanced braces in response")


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
```

- [ ] **Step 4: Run — expect pass (existing + new)**

Run: `.venv/bin/pytest tests/agents/ -v`
Expected: all existing tests pass, plus 3 new for `extract_json`.

- [ ] **Step 5: Commit**

```bash
git add src/agents/base.py tests/agents/test_base.py
git commit -m "refactor(agents): promote extract_json to module-level function

Claude's subagent returns raw text from the Agent tool — the orchestrator
reuses this parser. BaseAgent.parse_response now delegates to it for
consistency. Pure refactor; no behavior change."
```

---

## Task 6: Per-agent Markdown renderer

**Files:**
- Create: `src/output/renderer.py`
- Create: `tests/output/test_renderer.py`

**Background:** Per spec comparison-report section and 小红书 formatting, each agent gets a rich Markdown report at `agents/<name>/output/{eval_date}.md` summarizing its market view, decisions with reasoning, current portfolio, watchlist updates, and reflections. The renderer is pure — in: decision dict, state, market_data, current_prices, benchmark_close, inception_benchmark_close, agent display name; out: Markdown string.

- [ ] **Step 1: Write failing tests**

Create `tests/output/test_renderer.py`:

```python
"""Tests for the per-agent Markdown report renderer."""
from __future__ import annotations

from src.output.renderer import render_agent_report


def _decision_sample() -> dict:
    return {
        "eval_date": "2026-04-17",
        "market_view": "当前市场震荡，结构性行情为主。新能源和医药有轮动机会。",
        "decisions": [
            {
                "action": "BUY",
                "ticker": "300750",
                "name": "宁德时代",
                "quantity": 100,
                "reason": {
                    "thesis": "新能源长期趋势 + Q1业绩催化",
                    "catalyst": "Q1财报 + 海外订单落地",
                    "risk": "欧美关税不确定性",
                    "invalidation": "Q1净利润不及预期",
                },
            },
            {
                "action": "HOLD",
                "ticker": "600519",
                "name": "贵州茅台",
            },
        ],
        "watchlist_updates": [
            {"ticker": "300308", "name": "中际旭创", "note": "等回调再看"}
        ],
        "reflection": "上期买入 300750 判断基本正确，涨幅 3.7%。",
        "note_to_audience": "市场在这个位置，别慌。",
    }


def _state_sample() -> dict:
    return {
        "agent": "claude",
        "inception_date": "2026-04-01",
        "initial_capital": 100000,
        "current_cash": 81450,
        "last_eval_date": "2026-04-17",
        "positions": [
            {"ticker": "300750", "name": "宁德时代", "quantity": 100,
             "avg_cost": 185.50, "bought_date": "2026-04-17"},
        ],
        "trade_history": [],
        "nav_history": [],
    }


def test_report_starts_with_agent_header():
    out = render_agent_report(
        display_name="Claude",
        decision=_decision_sample(),
        state=_state_sample(),
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=4671.00,
    )
    # Title line
    first_line = out.splitlines()[0]
    assert "Claude" in first_line
    assert "2026-04-17" in first_line


def test_report_includes_market_view():
    out = render_agent_report(
        display_name="Claude",
        decision=_decision_sample(),
        state=_state_sample(),
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=4671.00,
    )
    assert "市场判断" in out
    assert "当前市场震荡" in out


def test_report_groups_decisions_by_action():
    out = render_agent_report(
        display_name="Claude",
        decision=_decision_sample(),
        state=_state_sample(),
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=4671.00,
    )
    assert "买入" in out
    assert "持有" in out or "HOLD" in out
    assert "宁德时代" in out
    # Each reason bullet point rendered
    assert "新能源长期趋势" in out
    assert "Q1财报" in out
    assert "Q1净利润不及预期" in out


def test_report_renders_current_portfolio_table():
    out = render_agent_report(
        display_name="Claude",
        decision=_decision_sample(),
        state=_state_sample(),
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=4671.00,
    )
    assert "当前组合" in out or "持仓" in out
    # Cash shown
    assert "81,450" in out


def test_report_includes_watchlist_updates():
    out = render_agent_report(
        display_name="Claude",
        decision=_decision_sample(),
        state=_state_sample(),
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=4671.00,
    )
    assert "观察" in out or "watchlist" in out.lower()
    assert "中际旭创" in out
    assert "等回调再看" in out


def test_report_includes_reflection_and_audience_note():
    out = render_agent_report(
        display_name="Claude",
        decision=_decision_sample(),
        state=_state_sample(),
        current_prices={"300750": 192.30},
        benchmark_close=4728.67,
        inception_benchmark_close=4671.00,
    )
    assert "反思" in out
    assert "上期买入 300750 判断基本正确" in out
    assert "致观众" in out or "观众" in out
    assert "别慌" in out


def test_report_handles_no_decisions_gracefully():
    decision = {
        "eval_date": "2026-04-17",
        "market_view": "观望",
        "decisions": [],
        "watchlist_updates": [],
        "reflection": "",
        "note_to_audience": "",
    }
    state = {
        "agent": "claude",
        "initial_capital": 100000,
        "current_cash": 100000,
        "positions": [],
        "trade_history": [],
        "nav_history": [],
        "inception_date": "2026-04-17",
    }
    out = render_agent_report(
        display_name="Claude",
        decision=decision,
        state=state,
        current_prices={},
        benchmark_close=None,
        inception_benchmark_close=None,
    )
    assert "Claude" in out
    assert "2026-04-17" in out
    # No crash on empty decisions; shows "无操作" or similar marker
    assert "无操作" in out or "暂无" in out
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/pytest tests/output/test_renderer.py -v`
Expected: ImportError on `src.output.renderer`.

- [ ] **Step 3: Implement**

Create `src/output/renderer.py`:

```python
"""Per-agent Markdown report renderer.

Input: one agent's decision dict + state + pre-extracted prices + benchmarks.
Output: a Markdown string suitable for writing to
``agents/<name>/output/{eval_date}.md``.

Reuses briefing's format helpers for pct/yuan formatting to stay
consistent with how the input briefing is presented.
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

    # Compute portfolio metrics
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

    # ---- assemble sections ----
    sections: list[str] = []
    sections.append(f"# AI基金经理 · {display_name}｜{eval_date}")
    sections.append("")

    # Market view
    mv = (decision.get("market_view") or "").strip()
    sections.append("## 市场判断")
    sections.append(mv if mv else "（未提供）")
    sections.append("")

    # Operations
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

    # Current portfolio
    sections.append("## 当前组合")
    sections.append(_holdings_table(positions, current_prices))
    sections.append("")
    sections.append(f"现金：{_yuan(cash)}")
    sections.append(f"组合净值：{_yuan(nav)}（{_pct(cum_return_pct)}）")
    sections.append(f"累计收益：{_pct(cum_return_pct)}")
    if bench_return_pct is not None:
        sections.append(f"同期CSI300：{_pct(bench_return_pct)}")
    sections.append("")

    # Watchlist
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

    # Reflection
    reflection = (decision.get("reflection") or "").strip()
    sections.append("## 反思")
    sections.append(reflection if reflection else "（未提供）")
    sections.append("")

    # Audience
    note = (decision.get("note_to_audience") or "").strip()
    sections.append("## 致观众")
    sections.append(note if note else "（未提供）")
    sections.append("")

    sections.append("---")
    sections.append("*AI独立决策，仅供娱乐和研究，不构成投资建议。*")

    return "\n".join(sections)
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/pytest tests/output/test_renderer.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/output/renderer.py tests/output/test_renderer.py
git commit -m "feat(output): per-agent Markdown report renderer

Groups decisions by BUY/SELL/HOLD, renders full reason blocks, current
portfolio table, cumulative return vs CSI 300, watchlist updates,
reflection, and audience note."
```

---

## Task 7: Multi-agent comparison report

**Files:**
- Create: `src/output/comparison.py`
- Create: `tests/output/test_comparison.py`

**Background:** For `output/{eval_date}.md` — the 小红书-ready comparison of N agents. Input: a dict of `{agent_name: {display_name, decision, state}}` for every agent that completed this eval, plus a track-record summary (for "today's" + "cumulative" returns) and benchmark data. Output: a leaderboard table + each agent's market view + operation summary + the legal footer.

- [ ] **Step 1: Write failing tests**

Create `tests/output/test_comparison.py`:

```python
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
    assert "AI" in first_line  # some brand-y header


def test_comparison_table_lists_all_agents_and_benchmark():
    out = render_comparison_report(
        metrics=_metrics_sample(),
        agent_entries={
            "claude": _agent_entry("Claude", "mv-claude"),
            "gemini": _agent_entry("Gemini 2.5 Pro", "mv-gemini"),
        },
    )
    # Leaderboard-style table
    assert "Claude" in out
    assert "Gemini 2.5 Pro" in out
    assert "CSI" in out  # benchmark row labeled as CSI 300 / CSI300
    # Formatted percentages present
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
    # Each agent's operations summarized
    assert "宁德时代" in out


def test_comparison_includes_vs_benchmark_column():
    out = render_comparison_report(
        metrics=_metrics_sample(),
        agent_entries={
            "claude": _agent_entry("Claude", "x"),
            "gemini": _agent_entry("Gemini 2.5 Pro", "y"),
        },
    )
    # vs CSI 300 column: claude cumulative 0.5% - benchmark 1.2% = -0.70%
    assert "-0.70" in out
    # gemini cumulative -0.2% - benchmark 1.2% = -1.40%
    assert "-1.40" in out


def test_comparison_missing_agent_shown_as_skipped():
    """If an agent didn't complete this eval, it still appears as 未评估."""
    metrics = _metrics_sample()
    metrics["agents"] = {
        "claude": metrics["agents"]["claude"],
        # gemini missing entirely
    }
    out = render_comparison_report(
        metrics=metrics,
        agent_entries={
            "claude": _agent_entry("Claude", "x"),
            "gemini": {"display_name": "Gemini 2.5 Pro", "decision": None},
        },
    )
    # Skipped agent row rendered
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
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/pytest tests/output/test_comparison.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `src/output/comparison.py`:

```python
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

    # ---- Leaderboard table ----
    sections.append("| 选手 | 净值 | 今日收益 | 累计收益 | vs CSI300 |")
    sections.append("|------|------|---------|---------|-----------|")
    # Agents in the order they appear in agent_entries
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
    # Benchmark row
    sections.append(
        f"| CSI 300 | — | {_pct(bench.get('today_pct', 0))} | "
        f"{_pct(bench_cum)} | — |"
    )
    sections.append("")

    # ---- Per-agent narrative ----
    for name, entry in agent_entries.items():
        display = entry.get("display_name", name)
        decision = entry.get("decision")
        if decision is None:
            # Skipped — no narrative
            continue
        sections.append(f"## {display} 的判断")
        mv = (decision.get("market_view") or "").strip()
        sections.append(mv if mv else "（未提供）")
        sections.append("")
        sections.append("### 操作")
        sections.append(_summarize_decisions(decision))
        sections.append("")

    # ---- Footer ----
    sections.append("---")
    sections.append("*多个AI独立决策，仅供娱乐和研究，不构成投资建议。*")

    return "\n".join(sections)
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/pytest tests/output/test_comparison.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/output/comparison.py tests/output/test_comparison.py
git commit -m "feat(output): multi-agent comparison report renderer

Leaderboard table (nav, today, cumulative, vs CSI300) + each agent's
market view + operation summary. Dynamically handles N agents.
Missing agents render as 未评估."
```

---

## Task 8: Claude decision-subagent definition

**Files:**
- Create: `.claude/agents/fund-manager-claude.md`

**Background:** Per spec's Fairness Protocol, Claude's decision is made by an **isolated Claude Code subagent** — not the orchestrator session. The `Agent` tool spawns this subagent with a specific `subagent_type` that the user (or orchestrator) defines in `.claude/agents/`. The subagent:
- Has NO access to Web* tools (no `WebFetch`/`WebSearch`) — cannot look up extra data.
- Has NO session context from the orchestrator.
- Receives ONLY what the orchestrator puts in its prompt (briefing + portfolio state + memory + system prompt).
- Returns a JSON decision as its final text message.

Tools allowed: empty — the subagent has everything it needs in its prompt. (If future needs arise, `Read` could be allowed for reading the frozen briefing from disk instead of inlining it in the prompt.)

- [ ] **Step 1: Verify `.claude/agents/` exists**

From Task 1, the dir should already exist (git doesn't track empty dirs, so re-create if gone):

```bash
mkdir -p /Users/zijian/Developer/ai-fund-manager/.claude/agents
```

- [ ] **Step 2: Create the subagent definition**

Create `.claude/agents/fund-manager-claude.md`:

```markdown
---
name: fund-manager-claude
description: Makes an independent A-share trading decision given a frozen market briefing, portfolio state, and memory. Receives ONLY what is inlined in the prompt — no web, no session context, no external tools. Returns a single JSON decision as its final message.
tools: []
---

You are invoked by the AI Fund Manager orchestrator to produce Claude's
independent trading decision for today's eval.

**Hard rules:**

1. You have NO tools. Do not attempt to fetch any external data. Do not
   hallucinate numbers that aren't in the prompt.
2. Everything you need — market briefing, your holdings, your memory,
   and the full system prompt from the orchestrator — is in the user
   message you receive. Read it carefully.
3. Output EXACTLY one JSON object matching the schema specified in the
   prompt's 【输出格式】 section. No preamble, no commentary, no code
   fences. The final message you send is the JSON and nothing else.
4. If you cannot produce a valid decision from the given inputs, output
   a minimal valid decision with `"decisions": []` and explain the
   problem in `market_view`.

The orchestrator will validate your output against shared guardrails
(ticker existence, T+1, position limits, etc.) before applying it. If
your decision is rejected, you'll see that in the next eval's 上期回顾.
```

- [ ] **Step 3: Smoke-test that Claude Code sees the subagent**

Run: `ls /Users/zijian/Developer/ai-fund-manager/.claude/agents/`
Expected: `fund-manager-claude.md`

(Claude Code picks up project-scoped subagents automatically on session start. The runbook in Task 9 invokes the `Agent` tool with `subagent_type="fund-manager-claude"` to use it.)

- [ ] **Step 4: Commit**

```bash
git add .claude/agents/fund-manager-claude.md
git commit -m "feat: add fund-manager-claude subagent for isolated decisions

Restricts tools to [] — the subagent receives everything it needs
inlined in the prompt. This is the spec's 'technical fairness guarantee':
Claude sees the same frozen inputs as API agents, no web, no session
context, no knowledge of other agents' output."
```

---

## Task 9: Orchestration runbook in `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` (append a new "## 评估流程 (Orchestration Runbook)" section)

**Background:** This is the biggest Phase 3 piece that isn't Python code — the step-by-step the orchestrator session follows when the user says "start today's eval". Each step specifies the exact Python call (or `Agent` tool call for the subagent) with its inputs and outputs.

No tests — this is documentation. Validation is manual: the new session runs the runbook end-to-end and verifies the produced artifacts.

- [ ] **Step 1: Append the runbook to CLAUDE.md**

At the end of CLAUDE.md (after "## 完整设计文档"), append:

````markdown

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
            # Assume .SZ / .SH suffix — resolve via stock_basic or convention.
            # For a six-digit ticker starting with 0/3 → .SZ, with 6 → .SH.
            suffix = ".SH" if tk.startswith("6") else ".SZ"
            block = fetch_stock_5d(
                ts_code=f"{tk}{suffix}",
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
````

- [ ] **Step 2: Verify CLAUDE.md parses and tests still green**

Run: `.venv/bin/pytest`
Expected: `157 passed, 1 warning` (no source changes; this is just doc + tests green check).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add orchestration runbook to CLAUDE.md

Step-by-step for 'start today's eval': resolve eval_date, fetch data,
freeze briefing, run Claude via isolated subagent, run API agents,
rebuild track record, render reports. Each step has the exact Python
calls and the Agent-tool spawn for Claude's subagent."
```

---

## Task 10: README.md

**Files:**
- Create: `README.md`

**Background:** User-facing setup + usage, separate from CLAUDE.md (which is for Claude in future sessions). Covers install, .env, how to trigger an eval, where to find reports, and how to add a new agent.

- [ ] **Step 1: Create README.md**

```markdown
# AI 基金经理 · 多 Agent A 股模拟组合

多个 AI（Claude、Gemini 等）各自独立管理 ¥100,000 A 股模拟组合。相同数据输入、不同 AI 大脑、独立决策。结果用于小红书内容发布。

## 快速开始

```bash
# 1) 克隆 + 进入
git clone <this-repo>
cd ai-fund-manager

# 2) 创建 venv（Python 3.11+）
python3 -m venv .venv
source .venv/bin/activate

# 3) 安装依赖
pip install -r requirements.txt -r requirements-dev.txt

# 4) 配置 API Keys
cp .env.example .env
# 编辑 .env，填入 TUSHARE_TOKEN 和（可选）GEMINI_API_KEY

# 5) 运行测试，确认一切就绪
pytest
```

## 运行每日评估

在 Claude Code 会话里对 Claude 说：

> 开始今天的评估

Claude Code 会按 `CLAUDE.md` 的 Orchestration Runbook 执行：
1. 解析 eval_date（最近已收盘交易日）
2. 拉取数据 + 新闻
3. 构建并冻结共享简报
4. 生成隔离子 Agent 做 Claude 的决策
5. 调用 Gemini 等 API Agent
6. 生成对比报告和每个 Agent 的报告

### 输出文件

| 路径 | 内容 |
|------|------|
| `output/{eval_date}.md` | 多 Agent 对比报告（小红书版本） |
| `agents/<name>/output/{eval_date}.md` | 单 Agent 详细报告 |
| `agents/<name>/portfolio_state.json` | 该 Agent 的持仓和历史 |
| `agents/<name>/trade_journal/{eval_date}.json` | 原始决策 JSON |
| `track_record/nav_history.json` | 合并后的净值曲线（用于作图） |
| `data_cache/{eval_date}/*.json` | 当期缓存数据 |
| `data_cache/{eval_date}/briefing.md` | 冻结的简报 |

## 添加新 Agent

1. 在 `src/agents/` 新建 `<provider>_agent.py`，继承 `BaseAgent`
2. 实现 `decide(briefing, portfolio_state, memory) -> AgentResult`
3. 在 `.env` 中添加 API key（例如 `DEEPSEEK_API_KEY=...`）
4. 在 `src/agents/registry.py` 的 `AGENTS` 字典中注册：
   ```python
   "deepseek": {
       "class": "src.agents.deepseek_agent.DeepSeekAgent",
       "env_key": "DEEPSEEK_API_KEY",
   },
   ```
5. 下次评估时自动从 `memory_template/` 初始化 `agents/<name>/`

## 设计文档

详见 `docs/superpowers/specs/2026-04-17-multi-agent-fund-manager-design.md`
和 `CLAUDE.md`（含 orchestration runbook）。

## 免责声明

AI 的决策是模拟的，不代表真实买卖。**本项目内容不构成投资建议。**
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup + usage + adding new agent"
```

---

## Task 11: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full test suite green**

Run: `.venv/bin/pytest`
Expected: 157 (Phase 1+2) + new Phase 3 tests pass. Rough count:
- Task 2: +6 tests (price/volume extractors)
- Task 3: +5 tests (trade journal + prev decision)
- Task 4: +3 tests (memory loader)
- Task 5: +3 tests (extract_json module-level)
- Task 6: +7 tests (agent report renderer)
- Task 7: +6 tests (comparison renderer)

Total expected: **~187 tests pass**, 1 upstream warning.

- [ ] **Step 2: Manual smoke — run one end-to-end eval**

Follow the runbook in CLAUDE.md from Step 1 through Step 6 in a Claude Code session. Verify the output files exist and look sensible:

```bash
ls output/               # expect YYYY-MM-DD.md
ls agents/claude/output/ # expect YYYY-MM-DD.md
ls agents/claude/trade_journal/
cat track_record/nav_history.json | head -20
```

If no `GEMINI_API_KEY` is set, only Claude runs and the comparison report shows Gemini as 未评估. That's valid.

- [ ] **Step 3: Spec coverage check**

Walk through the spec's "Orchestration Flow" section 1–6 and confirm each step maps to a Task 9 runbook step:

| Spec step | Runbook step |
|-----------|--------------|
| 1. Resolve eval_date | Step 1 |
| 2. Fetch data | Step 2 |
| 3. Build + freeze briefing | Step 3 |
| 4. Claude decides (isolated subagent) | Step 4 + Task 8 subagent |
| 5. Run API agents | Step 5 |
| 6. Generate reports | Step 6 |

Spec § Fairness Protocol: technically enforced via Task 8's `fund-manager-claude` subagent (tools: `[]`, no web, no context). ✓
Spec § Crash Recovery: frozen briefing on disk + idempotency check. ✓
Spec § Reflection: embedded in briefing via `load_prev_decision` (Task 3). ✓

---

## Out-of-scope (documented for Phase 4+)

- `fina_indicator` data (TuShare works, but nothing consumes it yet — no guardrail rule uses it today).
- Charts from `track_record/nav_history.json` (equity curve PNG). Data is ready; visualizer is future.
- Periodic `investment_beliefs.md` updates (manual for Claude, summary prompt for API agents).
- Scheduling via `/loop` or CoWork for automated daily runs.
- 小红书 summary mode for 4+ agents (table + one-line highlight each).
- "Claude Pro mode" (opt-in unfair advantage variant).
- Gemini JSON-mode via `response_mime_type="application/json"` + optional `response_schema`.

## Definition of Done

- ~187 tests green.
- One end-to-end eval run produces `output/{eval_date}.md`, `agents/claude/output/{eval_date}.md`, and (if Gemini key present) `agents/gemini/output/{eval_date}.md`.
- `track_record/nav_history.json` exists and is valid JSON.
- `CLAUDE.md` runbook matches the actual code (no drift).
- 11 new commits on `main`, one per task.
