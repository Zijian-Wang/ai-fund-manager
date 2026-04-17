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
google-generativeai>=0.8.0  # 上游已弃用，需迁移到 google.genai
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
