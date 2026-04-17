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

详见 `CLAUDE.md`（含 orchestration runbook）。

## 免责声明

AI 的决策是模拟的，不代表真实买卖。**本项目内容不构成投资建议。**
