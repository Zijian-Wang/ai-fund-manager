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
# 编辑 .env，填入 TUSHARE_TOKEN（必须）
# GEMINI_API_KEY 等 API agent keys 在 manual-first 模式下不需要

# 5) 运行测试，确认一切就绪
pytest
```

## 运行每日评估

在 Claude Code 会话里对 Claude 说：

> 开始今天的评估

Claude Code 会激活 `ai-fund-manager-eval` skill，按以下流程驱动：

1. **选 agent**：问你本期评估哪些 agent（Claude/Gemini/GPT/Grok/DeepSeek），要不要开隔离的 `fund-manager-claude` 子 agent
2. **拉数据 + 冻结简报**：TuShare/AKShare/BaoStock + 新闻 → `data_cache/{eval_date}/briefing.md`
3. **（可选）隔离子 agent 决策**：通过 Claude Code `Agent` 工具启动 `fund-manager-claude`（无 web，仅看简报），直接拿 JSON
4. **生成 webchat prompts**：每个 agent 一份 `data_cache/{eval_date}/prompt_<agent>.txt`
5. **你手动跑 webchat**：
   - 打开 `claude.ai` / `gemini.google.com` / `chat.openai.com` / `grok.com` / `chat.deepseek.com`
   - 粘贴对应 prompt，等 AI 返回 JSON 决策
6. **粘回聊天**：把每家 AI 的 JSON 贴回 Claude Code 聊天（"gemini: {...}"），Claude Code 逐个 ingest：校验 guardrails → 应用到 portfolio state → 存 trade journal
7. **生成报告**：重建 track_record，渲染单 agent 报告 + 对比报告

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

### Manual 模式（默认）

只需加到 skill 的 `AGENTS` 列表即可（`.claude/skills/ai-fund-manager-eval/SKILL.md`）。
系统在首次出现时从 `memory_template/` 初始化 `agents/<name>/`，之后你手动把
briefing prompt 粘进那家 AI 的 webchat。零代码。

### API 模式（dormant，按需启用）

1. 在 `src/agents/` 新建 `<provider>_agent.py`，继承 `BaseAgent`
2. 实现 `decide(briefing, portfolio_state, memory) -> AgentResult`
3. 在 `.env` 中添加 API key（例如 `DEEPSEEK_API_KEY=...`）
4. 在 `src/agents/registry.py` 的 `AGENTS` 字典中注册
5. 在 skill 里切换对应 agent 到 API 路径

## 设计文档

详见 `CLAUDE.md`（含 orchestration runbook）。

## 免责声明

AI 的决策是模拟的，不代表真实买卖。**本项目内容不构成投资建议。**
