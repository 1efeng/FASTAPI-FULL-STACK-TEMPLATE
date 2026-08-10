# AGENTS.md — Travel Agent v7 Codex Control Tower

> 更新时间：2026-08-11  
> 当前仓库已经基于 `FASTAPI-FULL-STACK-TEMPLATE`。  
> Python 基线：3.14。  
> 当前施工策略：**先完成通用 AI Chat 生产底座，再完善 Travel 专业能力。**

---

# 1. 开工阅读顺序

每次 Codex / Coding Agent 开工必须按顺序阅读：

1. `AGENTS.md`
2. `IMPLEMENTATION_NOTES.md`
3. `docs/文档体系.md`
4. `docs/架构v7.md`
5. `docs/开发文档.md`
6. `docs/施工路线图.md`
7. 当前任务对应 Contract
8. 当前真实代码
9. `backend/pyproject.toml`
10. `uv.lock`
11. 前端任务额外阅读 `docs/前端架构与开发设计.md`

如果文档与代码冲突：

```text
先确认真实代码
→ 判断哪个 SOT 过期
→ 修正文档
→ 再继续开发
```

禁止根据聊天记忆猜当前项目状态。

---

# 2. 当前真实阶段

当前已经存在：

```text
FASTAPI-FULL-STACK-TEMPLATE
Python 3.14
FastAPI
PostgreSQL / Alembic
Auth / User
Item Reference Module
React / Vite
Redis Runtime
LiteLLM Proxy
Deep Agents
Minimal Main Agent
RuntimeClock
POST /api/v1/chat
FastAPI → ChatService → Deep Agents → LiteLLM → Provider
```

当前尚未完整存在：

```text
Business Conversation / Messages / RequestRun
AsyncPostgresSaver runtime wiring
Idempotency
Business Rate / Quota / Concurrency
Agent Streaming Adapter
Travel Chat frontend
完整 Travel Skill / Researcher / Tools
Travel Research Trust
Production multi-instance release gate
```

不要把 v6 Cognitive Core 当作 v7 已实现事实。

---

# 3. 当前施工策略

## Phase A — Base Chat Platform

先完成：

```text
普通问答
→ Conversation / Messages / RequestRun
→ AsyncPostgresSaver
→ AuthZ
→ Idempotency
→ Rate / Quota / Concurrency
→ Deadline / Cancellation
→ Usage Attribution
→ Agent Streaming
→ C-End Chat
→ LangSmith / Security / Eval
→ Multi-instance / Backup / Load Test
```

形成：

```text
基础 Chat 平台完成 Gate
```

## Phase B — Travel Domain

Gate 之后才继续：

```text
Travel Planning Skill
Markdown Contract
Budget
Search
Maps
Weather
travel-researcher
Research Findings
Research Trust
完整 Planning / Modification
Travel UI
Travel Eval
```

除非项目 Owner 明确改变施工策略，否则 **不得跳过 Base Chat Platform Gate 提前做复杂 Travel Research**。

---

# 4. Framework Ownership

```text
Travel Agent
→ Product semantics
→ Business state
→ AuthZ
→ Idempotency
→ Request lifecycle
→ Research trust
→ Business usage attribution

Deep Agents
→ Agent Harness
→ SubAgent
→ Context isolation / built-in context capabilities

LangGraph
→ Agent Runtime
→ Thread
→ Checkpoint
→ Resume

LiteLLM
→ LLM routing
→ retry
→ fallback
→ health
→ cooldown
→ per-call limits
→ spend/cost source

LangSmith
→ AI semantic trace
→ Dataset
→ Eval
→ Experiment

FastAPI
→ Product HTTP
→ Validation
→ Auth integration
→ Product Request Lifecycle
→ Agent Streaming Adapter

PostgreSQL
→ Business Durable State

Redis
→ Business Shared Runtime State

@langchain/react
→ Frontend Agent Reactive Runtime

assistant-ui
→ Preferred Chat UX / Components

TanStack Query
→ Non-stream Business REST State
```

---

# 5. Frontend Runtime 决策

P0 核心：

```text
@langchain/react
```

首选 UI：

```text
assistant-ui
@assistant-ui/react-langchain
```

但 assistant-ui 是**首选实现层，不是不可替换的系统 Owner**。

正式接入前必须经过 Streaming / Adapter Spike。

如果 assistant-ui Spike 失败：

```text
保留 @langchain/react
保留 FastAPI Agent Streaming Adapter
替换 Presentation Layer
```

不得因为 UI 库变化推翻后端架构。

P0 不同时维护：

```text
@ai-sdk/react
+
@langchain/react
```

两套 Chat Runtime。

---

# 6. FastAPI Agent Streaming Adapter

项目中统一使用：

> **FastAPI Agent Streaming Adapter**

不要把它描述为“第二个 Custom Backend”。

职责：

```text
@langchain/react
↕
官方 LangChain/LangGraph Agent Streaming Protocol
↕
FastAPI Product Lifecycle
↕
Travel Agent / LangGraph
```

必须优先复用官方协议能力 / bindings / adapter / primitives。

禁止自研：

```text
CustomAgentProtocolServer
CustomReplayEngine
CustomCheckpointWireFormat
CustomToolLifecycleProtocol
CustomSSEChatFramework
```

---

# 7. Product Lifecycle 不允许被绕过

生产 C-End 请求必须经过：

```text
Authentication
→ Resource Authorization
→ Rate / Quota / Concurrency
→ Idempotency
→ request_id
→ persist user message + request_run
→ Agent under deadline
→ persist assistant final + request_run completed
→ COMMIT
→ stream completion
```

浏览器不得为了使用 `@langchain/react` 绕过 FastAPI Product Lifecycle 直接访问生产 Agent Runtime。

如果未来考虑 Agent Server-first：

```text
必须先 ADR
```

---

# 8. Business Conversation != LangGraph Thread

```text
Business Conversation
→ Product resource / ownership / history

LangGraph Thread
→ Agent runtime / checkpoint
```

服务端维护映射。

客户端提供的：

```text
conversation_id
thread_id
request_id
user_id
```

都不是授权证明。

---

# 9. v6 Cognitive Core 不变量

后续进入 Travel Phase 时保持：

```text
Main
→ 必要澄清
→ travel-planning Skill
→ travel-researcher
→ Research Findings
→ Main Final Decisions
→ Budget（按需）
→ Markdown Contract
→ Main Final
```

Main 是唯一最终语义 Owner。

默认禁止新增：

```text
Planner Agent
Writer Agent
Validator Agent
Budget Agent
Currency Agent
Weather Agent
Visa Agent
```

---

# 10. 禁止重复造轮子

未经 ADR 证明框架缺口，不得新增：

```text
CustomCircuitBreaker
ProviderRouter
RetryBudgetManager
ProviderHealthManager
LLMCostCalculator
CheckpointRepository
CustomLangGraphCheckpointSchema
ConversationSummarizer
GenericContextCompactor
EvalDashboard
ExperimentPlatform
TraceIdManager
CustomChatStateMachine
CustomAgentStreamingProtocol
CustomThreadRuntime
CustomSSEDeltaParser
```

---

# 11. Python / Dependency 规则

Python 3.14 已是当前基线。

禁止：

```text
为了旧文档主动降级 Python
```

版本事实：

```text
pyproject.toml
→ compatibility declaration

uv.lock
→ exact Python runtime SOT

frontend lockfile
→ exact frontend dependency SOT

LiteLLM image digest
→ exact gateway runtime SOT
```

涉及 Deep Agents / LangGraph / LangChain / `@langchain/react` / assistant-ui 的能力，必须检查**当前锁定版本**，不能直接按最新文档猜 API。

---

# 12. Item Reference Module

`backend/app/modules/item` 保留为简单 CRUD Reference。

它：

```text
是 Module 示例
不是 Travel Agent 核心业务
```

不得机械要求 conversation/chat/request_run 全部复制 Item 的 model/repository/service 结构。

---

# 13. Reverse Proxy

当前实现优先沿用模板 Traefik。

架构层统一称：

```text
Reverse Proxy / Load Balancer
```

不要默认：

```text
Nginx → Traefik → FastAPI
```

双代理叠加。

---

# 14. Observability

P0 主 AI Trace：

```text
LangSmith
```

LiteLLM：

```text
provider / model / retry / fallback / call id / tokens / cost
```

OpenTelemetry：

```text
按需补 FastAPI / HTTP / DB / Redis infrastructure spans
```

不建设第二套 Trace Platform。

---

# 15. Codex 每轮执行规则

每轮只做下一个前置依赖已经满足的最小任务。

必须：

```text
1. 阅读 SOT
2. 检查真实代码
3. 确认当前 Milestone
4. 只做一个最小任务
5. 增加测试
6. 跑相关检查
7. 更新 IMPLEMENTATION_NOTES.md
8. 更新 docs/施工路线图.md
9. 未验证能力不得标记完成
10. 汇报下一步最小任务
```

禁止：

```text
顺手提前做未来 Travel Tool
顺手重构无关模块
因为 UI 需求绕过 Persistence
因为 Streaming 需求绕过 Request Lifecycle
把 Spike 当正式实现
```
