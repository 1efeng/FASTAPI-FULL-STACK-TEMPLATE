# AGENTS.md — Travel Agent v7 Codex Control Tower

> 当前仓库已经基于 `1efeng/FASTAPI-FULL-STACK-TEMPLATE`。
> 当前 Python 基线已经升级到 **3.14**。
> 不要重新搭模板，不要无证据降级 Python。

## 开工阅读顺序

1. `AGENTS.md`
2. `CODEX_HANDOFF.md`
3. `IMPLEMENTATION_NOTES.md`
4. `docs/文档体系.md`
5. `docs/路线图.md`
6. `docs/施工路线图.md`
7. 当前任务对应 Contract
8. 当前真实代码
9. `pyproject.toml`
10. `uv.lock`

## 当前已知事实

- 当前项目底座：FASTAPI-FULL-STACK-TEMPLATE
- 当前 Python：3.14
- v6 Cognitive Core 是迁移来源，不是 v7 当前实现事实

未知项必须先检查：
- item 标准业务 Module 参考实现是否保持可运行
- Redis / LiteLLM / LangGraph / LangSmith / OTel 是否已接入
- Agent 是否已迁移
- 当前测试是否通过

## Framework Ownership

```text
Travel Agent  → 产品逻辑 / 业务状态 / AuthZ / Idempotency / Request Lifecycle
Deep Agents   → Agent Harness / SubAgent / Context
LangGraph     → Checkpoint / Thread / Resume
LiteLLM       → LLM routing / retry / fallback / health / cost
LangSmith     → AI Trace / Dataset / Eval / Experiment
OpenTelemetry → 基础设施 span 标准协议 / Instrumentation（不建设独立平台）
FastAPI       → HTTP / Validation / Native SSE
PostgreSQL    → Durable State
Redis         → Shared Runtime State
```

## v6 Cognitive Core 不变量

```text
Main
→ 必要澄清
→ travel-planning Skill
→ travel-researcher
→ Research Findings
→ Main Final Decisions
→ Budget / FX
→ Markdown Contract
→ Main Final
```

Main 是唯一最终语义 Owner。

默认禁止新增 Planner / Writer / Validator / Budget / Currency / Weather / Visa Agent。

## 10,000 DAU 基线

默认：

```text
模块化业务单体
+ stateless app instances
+ shared PostgreSQL
+ shared Redis
+ LiteLLM HA
```

10,000 DAU 不是容量承诺，最终容量由压测和灰度指标决定。

## 禁止重复造轮子

未经 ADR 证明框架缺口，不得新增：

```text
CustomCircuitBreaker
ProviderRouter
RetryBudgetManager
LLMCostCalculator
CheckpointRepository
CustomLangGraphCheckpointSchema
ConversationSummarizer
GenericContextCompactor
SSEEncoderFramework
TraceIdManager
EvalDashboard
ExperimentPlatform
```

## Python 3.14 规则

Python 3.14 已是当前基线。
不要为了匹配旧文档或旧 v6 依赖主动降级。
任何框架 API 使用前先看 `uv.lock` 中实际版本。

## Full-Stack Template 规则

模板是工程底座，不是架构 Source of Truth。

优先保留：
- FastAPI
- async SQLAlchemy / PostgreSQL
- Alembic
- Auth / User
- Docker / Compose
- backend tests
- frontend auth/account
- generated API client
- Playwright / CI

保留并明确边界：
- `item` 作为标准业务 Module 模板 / 参考实现
- Items UI 作为对应的全栈参考实现
- `item` 不属于 Travel Agent 核心业务，不应进入旅行领域模型
- 修正与 Travel Agent 文档冲突的模板说明

## Request Lifecycle

```text
AuthN
→ Resource AuthZ
→ business rate/quota/concurrency
→ Idempotency
→ request_id + OTel root span
→ persist request_run + user message
→ Agent under E2E deadline
   ├── LangGraph checkpoints
   ├── LiteLLM
   └── Tools
→ business transaction:
   assistant final + request_run completed
→ COMMIT
→ SSE final
```

LangGraph checkpoint transaction != business final transaction。

## Codex 第一动作

不要立即大规模重构。
先执行 `CODEX_START_PROMPT.md` 的审计流程，更新 `IMPLEMENTATION_NOTES.md`，
再从 `docs/施工路线图.md` 找到第一个真正未完成且前置依赖已满足的小任务。
