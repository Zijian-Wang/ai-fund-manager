# AI基金经理 — A股模拟组合（多Agent版）

## 项目概述

多个AI（Claude、Gemini等）各自独立管理 ¥100,000 A股模拟组合。相同数据输入、不同AI大脑、独立决策。对比结果用于小红书内容发布。

- **初始资金**：每个Agent ¥100,000
- **投资范围**：A股股票、ETF（不做期货/期权）
- **决策频率**：每日（按需触发）
- **执行方式**：Claude Code 为总指挥，manual-first — 用户把 briefing prompt 粘进各家 webchat，JSON 决策贴回聊天；可选开启隔离 Claude 子 Agent 做 "两个 Claude" 对照
- **业绩基准**：CSI 300（沪深300指数）

## 技术架构

**Claude Code 是 orchestrator**。用户说"开始今天的评估"（或任何触发该意图的话），Claude Code 激活 `ai-fund-manager-eval` skill 并按 skill 的 step-by-step runbook 执行。skill 是叙事层；Python 在 `src/` 下承担正确性敏感的计算。

**评估模式：manual-first**。用户手动把简报 prompt 粘进 Gemini/GPT/Grok/DeepSeek/Claude 的 webchat，拿到 JSON 决策，贴回聊天；Claude Code 用 `apply_agent_decision` 做校验+入账+日志。

- **优点**：webchat 自带 web 工具，news-gathering 本身成为被比较的能力之一；不需要配 API key；模型通常更强。
- **代价**：公平性从技术强制退化为约定（每个 agent 同一段 briefing 文本 + "仅基于简报决策"的提示）。

**可选的 `fund-manager-claude` 子 Agent**（隔离路径）：
- 通过 Claude Code `Agent` 工具启动，`tools: []`（无 web / 无 session context）
- 输入仅为 prompt 中 inline 的 briefing + state + memory
- 输出 JSON 决策，与 webchat agent 同路径 ingest
- 与 webchat Claude 并存时，可作为 "两个 Claude" 对照（一个有 web，一个没有）

**API Agent 路径（dormant）**：`src/agents/gemini_agent.py` 等代码保留但默认不用；把对应 env key 填入 `.env` 并在 runbook 里切换即可恢复自动化。

## 技术栈

- Python 3.11+
- 数据源：TuShare Pro（主力）、AKShare（备用，版本锁定）、BaoStock（零配置兜底）
- 新闻：Eastmoney JSON API + 财联社 + Claude Code WebSearch
- AI Agent：manual webchat（Gemini / GPT / Grok / DeepSeek / Claude.ai）为主；Python API agent 代码保留为 dormant，填 env key 即可启用
- Isolated Claude 子 Agent：可选，通过 Claude Code `Agent` 工具启动（模型 opus，tools: []），用于 "两个 Claude" 对照
- 存储：本地 JSON/Markdown 文件

## 项目结构

```
ai-fund-manager/
├── CLAUDE.md                      # 本文件
├── README.md                      # 用户操作指南
├── .env                           # TUSHARE_TOKEN, GEMINI_API_KEY
├── requirements.txt
├── .claude/
│   ├── agents/
│   │   └── fund-manager-claude.md # 可选的隔离 Claude 子 Agent 定义（tools: []）
│   └── skills/
│       └── ai-fund-manager-eval/
│           └── SKILL.md           # 日评估的完整 runbook（叙事层）
├── src/
│   ├── data/
│   │   ├── tushare_client.py      # TuShare Pro 封装（含缓存+限速）
│   │   ├── akshare_client.py      # AKShare 备用封装
│   │   ├── baostock_client.py     # BaoStock 零配置兜底
│   │   ├── market_data.py         # 获取+缓存市场数据（指数、板块、持仓、ETF/stock universe）
│   │   └── news_fetcher.py        # Eastmoney JSON API + 财联社结构化新闻
│   ├── agents/                    # Python agent 代码（dormant；填 env key 即启用）
│   │   ├── base.py                # BaseAgent ABC + AgentResult + extract_json
│   │   ├── gemini_agent.py        # 调 Gemini API，返回 AgentResult
│   │   └── registry.py            # Agent 注册表：从 .env 发现活跃 agent
│   ├── portfolio/
│   │   ├── state.py               # 读写每个 agent 的 portfolio_state.json（原子写入）+ 记忆/日志辅助
│   │   └── performance.py         # NAV 计算、收益率、vs CSI 300 基准
│   ├── guardrails.py              # 共享风控验证（ticker/手数/T+1/仓位/ETF+股票 universe）
│   ├── briefing.py                # 组装共享简报（市场数据+新闻+持仓）
│   ├── apply.py                   # apply_agent_decision：validate + apply + nav-append（pure）
│   └── output/
│       ├── renderer.py            # JSON 决策 → 单 agent Markdown 报告
│       └── comparison.py          # 多 agent 对比报告
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

简报冻结到 `data_cache/{eval_date}/briefing.md`，所有 agent 收到**完全相同的 briefing 文本**。每个 agent 对应的 prompt 文件独立生成，一并落盘供用户粘贴。

**Manual-first 下公平性的退化**：webchat agent 自带不同的 web 工具、system prompt、记忆；因此技术强制转为约定——每个 agent 拿到同一段 briefing + "仅基于简报决策"的指令。这也是产品特色：**news-gathering 能力本身成为被比较的一部分**。

**若要恢复技术强制公平**：用 `fund-manager-claude` 子 Agent（`tools: []`，无 web）替代 webchat Claude；或把 API agent 填 env key 并在 skill 里切回自动路径。

### 幂等性

- 每个决策包含 `eval_date` 字段
- 应用前检查 agent 的 `last_eval_date` — 重复则拒绝
- Session崩溃后重跑是安全的：已完成的Agent被跳过，冻结简报从磁盘加载

## Orchestration 流程

用户说 "开始今天的评估" 时，Claude Code 激活 **`ai-fund-manager-eval` skill**（在 `.claude/skills/ai-fund-manager-eval/SKILL.md`），skill 是完整 runbook。高层概要：

```
1. 问用户：本期评估哪些 agent？要不要加隔离的 fund-manager-claude 子 agent？
2. 解析 eval_date、拉取市场数据、构建并冻结共享简报
3. (可选) 跑隔离子 agent，获得 Claude 的 "无 web" 决策
4. 为每个 webchat agent 生成 prompt 文件，让用户粘进各家 webchat
5. 用户把 AI 返回的 JSON 决策贴回聊天，Claude Code 用 apply_agent_decision 逐个 ingest
6. 重建 track_record，渲染单 agent 报告 + 对比报告
```

每一步的具体 Python 调用在 skill 里；本文件保持架构总览，不再重复 runbook。

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
