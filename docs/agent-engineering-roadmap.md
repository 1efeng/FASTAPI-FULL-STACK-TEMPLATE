# Agent Engineering Roadmap

本文件记录 Agent101 课程在本项目中的适配路线。

目标不是逐字复刻课程实现，而是在保留工程学习价值的前提下，使用当前 LangChain / LangGraph 官方能力完成一个可运行、可演示、可面试讲解的 Agent 项目。

## 最终技术主线

```text
React Chat UI
    ↓
FastAPI
    ↓
app/chat
    ↓
LangChain / LangGraph
    ↓
PostgreSQL
```

核心原则：

> LangChain 提供成熟的模型、Tool、Agent 高层能力；LangGraph 是唯一 Agent Runtime；Agent101 用于补充框架没有替应用解决的副作用安全、恢复策略、审计、幂等和必要的分布式执行治理。

---

## Chapter 1 — Model Engineering

### 目标

跑通第一个真实流式 Chat vertical slice。

```text
React
  ↓
POST /chat/stream
  ↓
FastAPI
  ↓
LangChain ChatModel
  ↓
LLM
```

### FRAMEWORK

- LangChain ChatModel
- OpenAI-compatible model configuration
- structured output
- model streaming

### APP / GOVERNANCE

- Skill loading
- request context
- error mapping
- usage / token / latency / cost
- structured logging
- SSE cancellation
- stable application event protocol

### SKIP

- 自研 provider framework
- LLM gateway console
- prompt SaaS
- LiteLLM
- LangSmith

### 建议代码形态

```text
backend/app/chat/
├── api.py
├── schema.py
├── agent.py
├── events.py
└── skills/
```

前端：

```text
frontend/src/
├── components/Chat/
├── hooks/useChatStream.ts
└── routes/_layout/index.tsx
```

---

## Chapter 2 — Tool / Agent Engineering

### 目标

掌握现代 LangChain Agent，并补 Tool Governance。

```text
LangChain create_agent
        ↓
LangGraph-backed Agent Runtime
        ↓
Tools / Middleware / HITL / MCP
```

### FRAMEWORK

- `create_agent`
- `@tool` + Pydantic
- ToolRuntime
- middleware
- Tool call limits
- read/transient retry
- official HITL
- official MCP adapter

### GOVERNANCE

应用层必须理解并根据真实业务实现：

- trusted context injection
- final resource authorization
- Tool risk classification
- side-effect idempotency
- unknown outcome
- reconciliation
- audit

### Retry 原则

```text
READ + transient error
→ 可以按策略 retry

WRITE + timeout
→ 不能默认认为失败
→ UNKNOWN
→ query/reconcile
```

### SKIP

不自研通用：

- ToolRegistry
- ToolExecutor
- Tool Runtime
- Retry Engine
- Approval Runtime
- MCP Transport

### 建议代码形态

少量 Tool：

```text
chat/
+ tools.py
+ middleware.py
```

Tool 数量明显增长后才拆 `tools/`。

---

## Chapter 3 — LangGraph Runtime

### 目标

深入理解 Agent Runtime，而不是创建第二套 Runtime。

先实现最小手写 Graph Agent Loop：

```text
START
  ↓
model_node
  ↓
should_continue
  ├─ ToolNode
  │    ↓
  │  model_node
  └─ END
```

这一步用于理解：

- messages state
- tool_calls
- ToolMessage 回填
- conditional edge
- loop
- termination

Tool 的底层执行仍然复用官方 ToolNode / Tool 机制。

随后再扩展：

```text
plan
 ↓
execute
 ↓
evaluate
 ├─ continue
 ├─ replan
 └─ finish
```

### 深入能力

- State / Node / Edge
- conditional routing
- Agent loop / termination
- Checkpointer
- AsyncPostgresSaver
- interrupt / Command(resume)
- streaming
- replan
- budget
- repetition detection
- convergence
- recovery semantics

### Durable Governance

LangGraph 负责：

- graph execution state
- checkpoint
- resume
- orchestration

应用补充：

- task/run identity（产品真需要时）
- side-effect idempotency
- unknown outcome
- reconciliation
- domain audit
- crash/recovery tests
- recovery policy

### 条件实现

只有真实出现多 Worker 并发竞争接管/stale worker 问题时才考虑：

- lease
- heartbeat
- fencing token
- recovery scanner

不为了课程完整度提前实现。

### 建议代码形态

```text
chat/
+ graph.py
+ state.py
```

只有 graph lifecycle / checkpoint / thread / stream / resume 把 API 明显撑大后，才考虑 `runtime.py`。

---

## PostgreSQL 边界

```text
Application data
SQLAlchemy AsyncSession
    ↓
asyncpg
    ↓
PostgreSQL

LangGraph runtime state
AsyncPostgresSaver
    ↓
psycopg
    ↓
same PostgreSQL
```

不要通过 SQLAlchemy/Alembic 重复管理 LangGraph checkpoint tables。

第一阶段不要同时创建：

- chat_messages
- chat_runs
- chat_steps
- custom checkpoint tables

如果以后产品出现会话列表、标题、owner、搜索、归档，再有意识地添加 application projection / metadata。

---

## 第一阶段明确不做

- RAG / vector database
- Redis
- Celery
- Kafka
- Temporal
- Inngest
- Kubernetes
- LiteLLM
- LangSmith
- 双 Runtime
- 双 checkpoint source of truth
- 复杂旅游业务系统

---

## 推荐实现顺序

### Stage 1

- LangChain model integration
- Travel Skill
- FastAPI SSE
- React streaming Chat
- structured output / error / usage / logging

### Stage 2

- Tool calling
- Tool governance
- HITL
- MCP

### Stage 3

- StateGraph
- manual minimal Agent Loop
- Postgres checkpointer
- interrupt / resume
- replan / budget
- idempotency / unknown outcome / reconciliation
- recovery tests

---

## 面试表达

推荐表述：

> 项目早期普通 Tool Calling 使用 LangChain `create_agent`，避免重复实现成熟 Agent Harness；为了深入理解 Agent Runtime，后续使用 LangGraph `StateGraph + ToolNode` 实现并扩展了 Agent Loop。框架解决 Tool 和 Graph 的通用执行机制，应用层重点实现授权、风险策略、副作用幂等、unknown outcome、reconciliation 和审计。

这比“全部自己手搓”或“只会调用 create_agent”都更能体现 Agent 应用工程能力。