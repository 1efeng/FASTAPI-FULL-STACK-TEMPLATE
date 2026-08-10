# CODEX_HANDOFF.md — ChatGPT → Codex

## 1. 项目演进

v6 已验证 Travel Agent Cognitive Core：

```text
Main Agent
Travel Planning Skill
Travel Researcher
Search / Maps / Weather
Budget
Currency
Runtime Clock
Markdown Contract
LangGraph execution guard
```

随后完成架构重审，最终结论：

> 保留认知核心，生产 Runtime 围绕成熟框架 Owner 重建。

之后又做出工程决策：

> v7 使用 `1efeng/FASTAPI-FULL-STACK-TEMPLATE`
> 作为 Application Runtime 底座，不再从空项目重复搭 FastAPI/Auth/DB/Docker/Frontend。

当前 Codex 项目已经采用该模板，并已升级到 Python 3.14。

## 2. 最终认知架构

### Main
唯一负责：
- 用户入口
- 必要澄清
- 最终路线/节奏/方案取舍
- 最终回答

### Travel Planning Skill
负责完整规划方法与 Markdown Contract，不是 Planner Agent。

### travel-researcher
负责 Search / Maps / Weather / 当前旅行事实。
返回 `Research Findings`，不输出最终完整计划。

### Deterministic tools
Budget / FX 保持确定性 Tool。

## 3. Framework Ownership

```text
Travel Agent  → Product / Business
Deep Agents   → Agent Harness / Context
LangGraph     → Checkpoint / Resume
LiteLLM       → LLM Infrastructure
LangSmith     → AI Trace / Eval
OpenTelemetry → Distributed Trace
FastAPI       → HTTP / Native SSE
PostgreSQL    → Durable State
Redis         → Shared Runtime State
```

## 4. 已废弃旧方案

以下旧方向不再有效：

```text
自研 CLOSED/OPEN/HALF_OPEN Circuit Breaker
自研 Provider Router
自研 Retry Budget
自研 LLM Pricing Engine
自研 Checkpoint Schema
自研通用 Conversation Summarizer
自研 Trace ID System
自研 SSE Framework
自研 Eval Platform
```

正确 Owner：

```text
LLM retry/fallback/health/cooldown → LiteLLM
E2E request deadline              → Application
Checkpoint                        → LangGraph
Context                           → Deep Agents
AI trace/eval                     → LangSmith
Distributed trace                 → OpenTelemetry
SSE transport                     → FastAPI
LLM cost/spend                    → LiteLLM
Business cost attribution         → Travel Agent
```

## 5. 生产拓扑

```text
C-End Client
→ Reverse Proxy / Load Balancer
→ FastAPI replicas
→ Travel Agent
→ LiteLLM
→ Providers

Shared:
Business PostgreSQL
LangGraph PostgreSQL persistence domain
LiteLLM PostgreSQL persistence domain
Redis
LangSmith
OpenTelemetry
```

模板已有 Traefik 时，不必为了旧文档强换 Nginx。
统一写 `Reverse Proxy / Load Balancer`。

## 6. 数据边界

Business DB：

```text
users
conversations
messages
request_runs
business_llm_usage
```

LangGraph：
官方 PostgreSQL checkpointer。

LiteLLM：
自己的 key / budget / spend / gateway state。

三者 migration ownership 分离。

## 7. v6 迁移策略

保留语义：
- Travel Planning Skill
- Markdown Contract
- Main prompt / policy
- Researcher prompt / policy
- Budget algorithm
- RuntimeClock
- 有价值的 Tool provider knowledge

不要整文件复制：
- old agent composition root
- old models/factory.py
- old config.py
- old .env.example
- old cli.py
- old direct-provider retry
- old InMemorySaver production assumption
- old exception-to-string Tool boundary
- logs

## 8. Full-Stack Template 改造方向

推荐：

```text
backend/app/
├── main.py
├── core/
├── infra/
├── modules/
│   ├── auth/
│   ├── user/
│   ├── conversation/
│   ├── chat/
│   ├── request_run/
│   └── usage/
└── agents/
    └── travel/
        ├── agent.py
        ├── subagents/
        ├── skills/
        ├── middleware/
        └── tools/
```

不要一次提前建满所有空目录。

## 9. 当前已知实现状态

只确认：

```text
Full-Stack Template → 已采用
Python 3.14         → 已采用
```

其他必须从当前代码检查后再打勾。

## 10. 下一步

先执行仓库审计。
更新 `IMPLEMENTATION_NOTES.md`。
然后按 `docs/施工路线图.md` 做第一个 dependency-valid 小任务。
