# AGENTS.md

## 项目目标

本仓库正在从通用 FastAPI Full Stack Template 演进为一个用于学习、演示和面试的 **Agent Engineering Platform**。

主技术路线：

- Backend: Python + FastAPI + SQLAlchemy 2 Async + PostgreSQL
- Agent: LangChain + LangGraph
- Frontend: React + TypeScript + TanStack Router/Query + Vercel AI SDK UI
- Transport: REST + AI SDK UI Message Stream over SSE

第一阶段只做一个可运行、可演示的 Chat Agent，`travel-planning` 作为首个业务 Skill。不要把旅行场景扩展成复杂旅游 SaaS。

---

## 总体原则

### 1. 成熟框架负责 Runtime，应用只补治理

优先使用 LangChain / LangGraph 当前官方能力，不重复实现已经成熟的通用 Runtime。

框架负责：

- model abstraction
- tool calling
- ToolMessage / ToolNode
- agent loop（高层场景）
- graph state / node / edge
- interrupt / resume
- persistence / checkpointer
- streaming
- MCP adapter

应用负责：

- authentication / authorization
- business risk policy
- side-effect idempotency
- unknown outcome handling
- reconciliation
- audit
- LangGraph → AI SDK UI stream adaptation
- product-specific business rules

不要因为课程中存在手写实现，就同时维护“课程 Runtime + LangGraph Runtime”两套实现。

### 2. LangGraph 是唯一 Agent Runtime

第三章开始需要低层 orchestration 时，以 LangGraph 为唯一执行 Runtime。

禁止同时维护：

- custom checkpoint + LangGraph checkpoint
- 两套完整 Agent state
- 两套 resume 决策
- 自研 Durable Runtime + LangGraph Runtime

正确方向：

```text
FastAPI
  ↓
LangChain / LangGraph Agent
  ↓
LangGraph Runtime
  ↓
Postgres Checkpointer
```

Agent101 的 durable 内容用于补充副作用安全、恢复策略、审计、幂等和必要的分布式执行治理，而不是再造第二套 Runtime。

### 3. 职责边界不等于代码分层

除非出现真实、独立的业务职责，否则不要为了架构形式创建额外层级。

优先：

```text
FastAPI API boundary
  ↓
Chat Agent / LangGraph
```

避免：

```text
API
  ↓
Facade
  ↓
Application Runtime
  ↓
Chat Service
  ↓
Agent Runtime
  ↓
LangGraph
```

让结构随着真实复杂度自然增长。

### 4. 先检查现有代码，再做最小修改

每次修改前：

1. 阅读当前目录和相关实现。
2. 优先复用已有能力。
3. 保留已有未提交/非相关改动。
4. 不做无关重构。
5. 修改后运行与变更相关的最小测试集，再运行项目已有质量检查。

禁止为了“更漂亮”反复重排目录。

---

## Agent101 适配规则

处理课程内容时，先判断能力归属：

- `FRAMEWORK`: LangChain / LangGraph 已成熟提供，直接使用。
- `APP`: 应用业务能力，项目自己实现。
- `GOVERNANCE`: 框架不会替业务解决的工程治理，项目保留。
- `SKIP`: 当前面试主线收益低或明显增加复杂度，暂不实现。

### Chapter 1

主线：LangChain model layer + LLM engineering governance。

保留：

- provider boundary
- structured output
- error mapping
- usage / token / latency / cost
- streaming / SSE cancellation
- retry / fallback 基本认知
- structured logging

不自研 LLM Framework / Provider Framework / Gateway Platform。

### Chapter 2

主线：LangChain Agent + LangGraph-backed runtime + Tool Governance。

优先使用：

- `create_agent`
- `@tool` + Pydantic
- official middleware
- ToolRuntime / ToolNode
- official HITL
- official MCP adapter

Tool 执行机制交给框架，Tool 治理由应用负责。

必须理解并在需要时实现：

- final resource authorization
- read/write/high-risk classification
- write-side-effect idempotency
- unknown outcome
- reconciliation
- audit

不要自研通用：

- ToolRegistry
- ToolExecutor
- ToolRuntime
- retry engine
- approval runtime
- MCP transport

### Chapter 3

主线：LangGraph StateGraph。

可以为了深入理解自己实现最小 Agent Loop：

```text
model node
  ↓
route
  ├─ ToolNode → model node
  └─ END
```

但 Tool 执行继续复用官方 ToolNode / Tool 机制。

逐步学习：

- State / Node / Edge
- conditional routing
- loop / termination
- checkpointer
- interrupt / resume
- streaming
- replan
- budget / convergence
- recovery semantics

Lease / heartbeat / fencing 只有出现真实多 Worker 竞争接管问题时才实现。

---

## Chat 模块约束

Chat、Agent、Tool、Graph 属于同一个业务 feature，不额外创建全局 `agents/`、`runtime/`、`orchestration/` 层。

结构按需求自然增长：

```text
Ch1
chat/
├── api.py
├── schema.py
├── agent.py
├── events.py
└── skills/

Ch2
+ tools.py       # 少量工具时
+ middleware.py  # 真正出现治理需求时

Ch3
+ graph.py
+ state.py
```

Tool 数量明显增长后，`tools.py` 才拆成 `tools/`。

只有当 API 同时承担 graph lifecycle、thread、checkpoint、stream、interrupt/resume 等明显膨胀时，才考虑 `runtime.py`。

只有出现真实会话产品数据需求（会话列表、标题、owner、搜索、归档）时，才增加 Chat SQLAlchemy model/repository/service。

不要提前创建：

- chat_messages
- chat_runs
- chat_steps
- custom checkpoints

LangGraph execution/message state 优先由 LangGraph checkpointer 管理。

---

## Skill 约束

产品运行时 Skill 放在：

```text
backend/app/chat/skills/
```

例如：

```text
backend/app/chat/skills/travel-planning/SKILL.md
```

`.agents/skills/` 仅用于开发 Agent / Codex 的工作流 Skill，不属于产品运行时。

不要混用两者。

---

## 数据库约束

应用数据使用 SQLAlchemy AsyncSession。

推荐边界：

```text
Application data
SQLAlchemy AsyncSession
  ↓
asyncpg
  ↓
PostgreSQL

LangGraph checkpoints
AsyncPostgresSaver
  ↓
psycopg
  ↓
same PostgreSQL
```

LangGraph checkpoint tables 由 LangGraph saver 自己管理，不建 SQLAlchemy model，不通过 Alembic 重复管理。

Repository 不负责 commit；业务 service / transaction boundary 决定 commit / rollback。

---

## 前后端 Chat 协议

普通 REST 继续使用 OpenAPI generated client。

Agent Chat 前端统一使用：

```text
@ai-sdk/react useChat
  ↓
DefaultChatTransport
  ↓
HTTP POST + SSE
  ↓
FastAPI
```

网络协议使用 **AI SDK UI Message Stream**，后端响应必须遵循当前 AI SDK 协议，例如：

- `Content-Type: text/event-stream`
- `x-vercel-ai-ui-message-stream: v1`
- SSE `data: {JSON}\n\n`
- 最后 `data: [DONE]\n\n`

文本流遵循 `text-start → text-delta → text-end`，同一文本 part 使用稳定 id。

前端使用 AI SDK 的 `UIMessage` / message parts / `ChatStatus`，不要再维护一套自研 `ChatMessage + useChatStream + SSE parser` 状态机。

AI SDK 只承担 **Frontend Chat Protocol / UI abstraction**，不得成为第二套 Agent Runtime。后端仍然只有 FastAPI + LangChain/LangGraph。

前端不得直接依赖 LangChain/LangGraph 原始 stream chunk。FastAPI 在边界处把 LangGraph stream 转换为 AI SDK UI message chunks：

```text
LangGraph internal stream
  ↓
FastAPI chat adapter
  ↓
AI SDK UI Message Stream
  ↓
useChat / UIMessage
  ↓
React UI
```

业务特有的 activity、progress、approval 等信息优先通过 AI SDK typed `data-*` parts 或标准 tool/approval parts 表达，不另造平行事件协议。

---

## 当前明确不引入

除非出现可验证的真实需求，不引入：

- LiteLLM
- LangSmith
- Redis
- Celery
- Kafka
- Temporal
- Inngest
- Kubernetes
- 第二套 durable runtime
- 传统 RAG / 向量数据库（第一阶段）

不要为了简历关键词增加基础设施。

---

## 官方 API 与文档

LangChain / LangGraph / Vercel AI SDK API 变化较快。

实现新能力前必须优先检查 **当前官方文档和当前安装版本**，不要仅凭旧课程、旧示例或模型记忆猜 API。

课程用于理解工程问题；当前官方框架用于决定实际实现方式。

---

## 完成标准

一个修改只有在产生可验证产出时才算完成：

- 代码可运行
- 对应测试通过
- lint/type-check 不因本次改动新增错误
- 架构没有增加重复 source of truth
- 能说明为什么使用框架能力、为什么某些治理需要应用自己实现

优先可运行的面试项目，而不是追求覆盖所有课程章节。
