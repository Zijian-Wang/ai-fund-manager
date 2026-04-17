# AI基金经理 — A股模拟组合

## 项目概述

一个由Claude驱动的A股模拟基金经理。每周产出投资决策+推理过程，用于小红书内容发布。

- **初始资金**：¥100,000
- **投资范围**：A股股票、ETF（不做期货/期权）
- **决策频率**：周度（周末分析 → 周一信号）
- **执行方式**：AI出信号，人工执行
- **业绩基准**：CSI 300（沪深300指数）

## 技术栈

- Python 3.11+
- 数据源：TuShare Pro（token存在 `.env` 文件中）、AKShare（免费备用）、BaoStock（零配置兜底）
- LLM：Anthropic Claude API（`anthropic` Python SDK）
- 存储：本地JSON/Markdown文件（无数据库）

## 项目结构

```
ai-fund-manager/
├── CLAUDE.md                    # 本文件
├── .env                         # TUSHARE_TOKEN, ANTHROPIC_API_KEY
├── requirements.txt
├── run_weekly.py                # 主入口：每周手动触发
├── src/
│   ├── data/
│   │   ├── market_briefing.py   # 生成每周市场简报
│   │   ├── tushare_client.py    # TuShare Pro数据获取
│   │   ├── akshare_client.py    # AKShare备用数据获取
│   │   └── news_fetcher.py      # 公开新闻抓取（东方财富/新浪）
│   ├── agent/
│   │   ├── system_prompt.py     # System prompt模板
│   │   ├── decision_engine.py   # 调Claude API做决策
│   │   └── guardrails.py        # 代码层风控（ticker验证/T+1/手数）
│   ├── portfolio/
│   │   ├── state.py             # 读写portfolio_state.json
│   │   └── performance.py       # 计算NAV/收益率/vs基准
│   └── memory/
│       ├── manager.py           # 读写记忆文件
│       └── reflection.py        # 周度反思：提取lessons
├── memory/                      # 持久化记忆目录
│   ├── portfolio_state.json     # 当前持仓状态
│   ├── market_regime.md         # Agent当前市场判断
│   ├── investment_beliefs.md    # CVRF风格投资信念
│   ├── trade_journal/           # 每期交易日志
│   │   └── week_001.json
│   ├── lessons/                 # 提取的教训
│   │   └── week_001.md
│   └── watchlist.json           # 观察名单
└── output/                      # 每期产出的内容
    └── week_001.md              # 可直接用于小红书的周报
```

## 核心流程：run_weekly.py

```
1. 加载 memory/ 下的所有记忆文件
2. 调用 market_briefing.py 拉取本周市场数据：
   - 大盘指数（上证/深证/创业板/沪深300）本周涨跌
   - 申万一级行业板块涨跌排名
   - 北向资金本周流向
   - 本周重要新闻摘要（3-5条）
   - Agent当前持仓标的的最新价格/涨跌
3. 调用 performance.py 计算当前NAV和vs CSI300
4. 组装完整prompt（system_prompt + memory + portfolio_state + market_briefing）
5. 调用Claude API（claude-sonnet-4-20250514），获取决策输出
6. 用 guardrails.py 验证输出中的交易指令：
   - ticker是否存在于valid_tickers表
   - 数量是否为100的整数倍
   - 是否违反T+1（不能卖当天买入的）
   - 单只仓位是否超过组合的50%（宽松上限）
   - 组合级别回撤是否触发review（-15%）
7. 通过验证 → 更新 portfolio_state.json，记录交易日志
8. 未通过 → 输出警告，不执行，要求agent修正
9. 生成 output/week_NNN.md 周报文件
10. 触发 reflection.py 让agent回顾上一期决策结果，提取lessons
```

## System Prompt

存放在 `src/agent/system_prompt.py` 中，作为模板字符串。
关键变量用 `{placeholder}` 注入：

- `{memory_content}` — 从 memory/ 目录读取并拼接
- `{portfolio_state}` — 当前持仓明细 + NAV + vs基准
- `{market_briefing}` — 本周市场数据

完整prompt见下方 SYSTEM_PROMPT 部分。

## Agent输出格式要求

在system prompt中要求Claude以JSON输出决策，便于程序解析：

```json
{
  "market_view": "对当前市场的判断（2-3段文字）",
  "decisions": [
    {
      "action": "BUY",
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
  "reflection": "对上期决策的回顾（如果有的话）",
  "note_to_audience": "写给观众的一段话，坦诚、有个性"
}
```

解析后再用模板渲染成可读的Markdown周报（output/week_NNN.md）。

## 数据获取规格

### market_briefing.py 需要拉取的数据

**必须（TuShare Pro）**：
- `pro.index_daily()` — 上证(000001.SH)、深证(399001.SZ)、创业板(399006.SZ)、沪深300(000300.SH)近5个交易日数据
- `pro.index_weight()` — 沪深300成分股权重（用于基准计算）
- `pro.daily()` — 当前持仓标的的日线数据
- `pro.moneyflow()` — 北向资金净流入
- `pro.stock_basic()` — 全量A股ticker列表（用于guardrails验证）
- `pro.fina_indicator_vip()` — 持仓标的的最新财务指标（如需）

**补充（AKShare）**：
- `ak.stock_board_industry_name_em()` — 东方财富行业板块列表
- `ak.stock_board_industry_hist_em()` — 板块涨跌历史
- `ak.stock_news_em()` — 个股新闻
- `ak.stock_hot_rank_em()` — 热门股排行（情绪指标）

**新闻（简单HTTP）**：
- 东方财富首页财经新闻RSS/JSON
- 用requests抓取，提取标题+摘要即可，不需要全文

### 数据缓存策略

- 每次run拉取的数据缓存到 `data_cache/YYYY-MM-DD/` 目录
- 避免重复调用API（TuShare有频率限制）
- 缓存文件为JSON格式，debug时可直接查看

## Guardrails（代码层风控）

```python
# src/agent/guardrails.py

class AShareGuardrails:
    """代码强制的风控规则 — 不依赖LLM判断"""

    # 仓位限制
    MAX_SINGLE_POSITION_PCT = 0.50      # 单只最大50%（宽松，让agent自由sizing）
    MIN_CASH_BUFFER = 0.00              # 允许满仓（agent自己决定留多少现金）

    # 灾难熔断
    MAX_SINGLE_DRAWDOWN = 0.20          # 单只浮亏-20% → 标记，强制agent在下期review
    MAX_PORTFOLIO_DRAWDOWN = 0.15       # 组合回撤-15% → 暂停开新仓，强制全面review

    # 交易限制
    MAX_TRADES_PER_WEEK = 10            # 防止过度交易
    ROUND_LOT = 100                     # 最小交易单位

    # A股特有
    T_PLUS_1 = True                     # 不能卖当天买的
    PRICE_LIMIT_MAIN = 0.10             # 主板涨跌停±10%
    PRICE_LIMIT_STAR_CHINEXT = 0.20     # 科创板/创业板±20%
    MIN_VOLUME_THRESHOLD = 5_000_000    # 日成交额最低500万（排除僵尸股）

    def validate_order(self, order, portfolio, valid_tickers):
        """验证单个交易指令，返回 (is_valid, error_message)"""
        errors = []

        # 1. Ticker存在性
        if order.ticker not in valid_tickers:
            errors.append(f"未知ticker: {order.ticker}")

        # 2. 手数验证
        if order.quantity <= 0 or order.quantity % self.ROUND_LOT != 0:
            errors.append(f"数量必须为100的正整数倍，当前: {order.quantity}")

        # 3. T+1验证
        if order.action == "SELL" and order.ticker in portfolio.bought_today:
            errors.append(f"T+1限制：{order.ticker}今日买入，不可当日卖出")

        # 4. 仓位上限（买入时检查）
        if order.action == "BUY":
            new_position_value = order.quantity * order.estimated_price
            new_portfolio_value = portfolio.total_value
            if new_position_value / new_portfolio_value > self.MAX_SINGLE_POSITION_PCT:
                errors.append(f"单只仓位超限: {new_position_value/new_portfolio_value:.1%} > {self.MAX_SINGLE_POSITION_PCT:.0%}")

        # 5. 资金充足性
        if order.action == "BUY":
            cost = order.quantity * order.estimated_price
            if cost > portfolio.cash:
                errors.append(f"现金不足: 需要¥{cost:,.0f}，可用¥{portfolio.cash:,.0f}")

        return (len(errors) == 0, errors)

    def check_circuit_breakers(self, portfolio):
        """检查熔断条件，返回 (is_triggered, trigger_type, message)"""
        # 组合级别
        if portfolio.total_return_pct <= -self.MAX_PORTFOLIO_DRAWDOWN:
            return (True, "PORTFOLIO_HALT",
                    f"组合回撤触发熔断: {portfolio.total_return_pct:.1%}。暂停开新仓，进入全面review。")

        # 个股级别
        flagged = []
        for pos in portfolio.positions:
            if pos.unrealized_return_pct <= -self.MAX_SINGLE_DRAWDOWN:
                flagged.append(f"{pos.name}({pos.ticker}) 浮亏{pos.unrealized_return_pct:.1%}")

        if flagged:
            return (True, "POSITION_REVIEW",
                    f"以下持仓触发单只review阈值：{'; '.join(flagged)}")

        return (False, None, None)
```

## 周报模板（output渲染）

```markdown
# 🤖 AI基金经理·第{week_number}期周报｜{date}

**组合净值：¥{nav:,.0f}（{total_return:+.2%}）| 同期CSI300：{benchmark_return:+.2%}**

---

### 市场判断

{market_view}

### 本期操作

{formatted_decisions}

### 观察名单

{formatted_watchlist}

### 写给观众

{note_to_audience}

---

*本组合由Claude AI独立决策，仅供娱乐和研究，不构成投资建议。*
```

## 开发步骤

### Step 1: 环境搭建
- 创建项目目录和虚拟环境
- 安装依赖：tushare, akshare, anthropic, python-dotenv
- 配置 .env（TUSHARE_TOKEN, ANTHROPIC_API_KEY）
- 初始化 memory/ 目录和 portfolio_state.json（100%现金）

### Step 2: 数据层
- 实现 tushare_client.py（封装常用API调用）
- 实现 market_briefing.py（拉取并格式化市场数据）
- 测试：能成功拉取本周数据并输出可读的markdown briefing

### Step 3: Agent核心
- 实现 system_prompt.py（prompt模板）
- 实现 decision_engine.py（调Claude API + 解析JSON输出）
- 实现 guardrails.py（验证层）
- 测试：能成功产出一轮决策

### Step 4: 状态管理
- 实现 portfolio/state.py（读写持仓状态）
- 实现 portfolio/performance.py（NAV计算 + vs基准）
- 实现 memory/manager.py（读写记忆文件）

### Step 5: 整合
- 实现 run_weekly.py（串联所有模块）
- 实现 output渲染（JSON → Markdown周报）
- 端到端测试：跑完一轮完整流程

### Step 6: 反思机制
- 实现 memory/reflection.py
- 每期结束后自动生成lessons
- 注入下一期的memory_content

## SYSTEM_PROMPT

```
你是一位管理10万元人民币A股模拟组合的独立基金经理。你拥有完全的投资决策权。

【你是谁】
你有自己的投资风格和判断力。你不是一个信息聚合器——你是一个有观点的投资者。
你会犯错，但你从错误中学习。你敢于持有与市场共识不同的观点，但只在你有充分
理由时才这样做。你不追涨杀跌，你寻找别人还没看到的机会。

【决策框架】
对于每一个投资决策，你必须产出结构化的思考：

1. THESIS（核心逻辑）：用2-3句话说清楚为什么买这个标的。
2. CATALYST（催化剂）：未来1-6个月内，什么会让市场认识到价值？
3. RISK（风险）：最大的下行风险是什么？
4. SIZING（仓位）：你有多确信？高确信=大仓位。
5. INVALIDATION（失效条件）：什么情况发生意味着thesis错了？

【约束】
- 投资范围：A股股票、ETF。
- 持有现金是完全可以接受的决策。
- 考虑T+1交易规则。
- 交易数量为100股的整数倍。
- 你的推理过程会被公开展示。坦诚、清晰、有个性。不写官话。

【输出格式】
你必须以JSON格式输出决策。结构如下：
{
  "market_view": "...",
  "decisions": [{"action":"BUY/SELL/HOLD","ticker":"...","name":"...","quantity":100,"reason":{...}}],
  "watchlist_updates": [{"ticker":"...","name":"...","note":"..."}],
  "reflection": "对上期决策的回顾",
  "note_to_audience": "写给观众的一段话"
}

【记忆】
{memory_content}

【当前持仓】
{portfolio_state}

【本周市场数据】
{market_briefing}

现在请做出本期投资决策。
```

## 注意事项

- TuShare Pro 5000积分，注意API调用频率（每分钟200次上限），做好缓存
- AKShare接口不稳定，经常更新，用try/except包裹，失败时fallback到缓存数据
- Claude API用 claude-sonnet-4-20250514 模型（性价比最优）
- JSON输出可能偶尔格式不对，做好解析容错（提取```json```代码块）
- portfolio_state.json 是最重要的文件，每次写入前先备份
