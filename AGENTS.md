# AGENTS.md

## 项目目标

本仓库正在从通用 FastAPI Full Stack Template 演进为一个以面试为主线、按生产形态收敛的 **Resumable Agent Application**（也是 Agent Engineering Platform 的学习载体）。

主技术路线：

- Backend: Python + FastAPI + SQLAlchemy 2 Async + PostgreSQL
- Agent: LangChain + LangGraph
- Frontend: React + TypeScript + TanStack Router/Query + shadcn/ui
- Agent Runtime (frontend): @langchain/react（LangGraph 官方 React SDK：useStream / StreamProvider / HttpAgentServerAdapter）
- Transport: LangGraph stream protocol over SSE

定位：以面试为主线、按生产形态收敛的 **Resumable Agent Application**；目标设计与验收口径见 `docs/architecture.md`（Aegra 版定稿）。`travel-planning` 是首个业务 Skill，不要扩展成复杂旅游 SaaS。

当前状态：架构已定稿为 **Aegra 自托管 Runtime + 应用补治理**（`docs/architecture.md`）；代码仍处于 P1–P5 过渡实现（`agent_runs` / `agent_events` / 租约 / DB 事件回放 / `tool_invocations`），将按定稿文档收敛移除。本文"约定"与现状冲突时，以"定稿架构 + 收敛顺序"为准：先同步代码/文档，再扩展新机制。

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
- LangGraph stream protocol adaptation
- Agent Chat runtime integration（当前为 @langchain/react）
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

工具副作用幂等是应用责任：`ToolIdempotencyMiddleware` + `tool_invocations` 台账是最小实现，Aegra 不提供，**保留**（`docs/architecture.md` §6.4）。不得无声删除该治理能力。

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

Lease / heartbeat / fencing 已由 Aegra Runtime 提供（PG 原子 lease + 10s heartbeat + reaper），应用不再实现。

---

## Chat 模块约束

Chat、Agent、Tool、Graph 属于同一个业务 feature；Chat 负责交互协议，Agent 负责执行能力。不额外创建全局 `agents/`、`runtime/`、`orchestration/` 层。

结构按需求自然增长，当前实际形态：

```text
agent/
├── agent.py
├── middleware.py        # Skill 目录 + 工具幂等（P4）等横切治理
└── skills/
chat/
├── api.py
├── runs/                # P1–P5 过渡：agent_runs/agent_events/租约/tool_invocations（目标：按 docs/architecture.md 收敛移除）
└── protocol/
    ├── __init__.py
    ├── adapter.py       # LangGraph state/message 序列化边界
    ├── db_stream.py     # SSE 事件回放 + 轮询（过渡；将被 Aegra SSE broker 取代）
    └── schema.py        # LangGraph SDK 传输请求边界
```

后续文件只在真实需求出现时新增：`agent/tools.py`（Tool 明显增多）、`agent/graph.py` / `agent/state.py`（进入低层 orchestration）。

`protocol/` 只解决前后端协议边界（LangGraph stream protocol），不是 Agent Runtime。进入 Chapter 2/3 后在同一目录扩展 tool / reasoning / approval 事件，不再另建第二套事件协议。

Tool 数量明显增长后，`tools.py` 才拆成 `tools/`。

只有当 API 同时承担 graph lifecycle、thread、checkpoint、stream、interrupt/resume 等明显膨胀时，才考虑 `runtime.py`。

只有出现真实会话产品数据需求（会话列表、标题、owner、搜索、归档）时，才增加 Chat SQLAlchemy model/repository/service（`chat_messages` 读模型已延后，见 `docs/architecture.md` §6.3）。

规划中的例外：`chat_messages`（UI 展示读模型）已**延后**（Aegra values 快照可渲染消息）。**尚未建表/迁移**，若落地按 `message_id` 幂等写入；LangGraph execution/message state 仍由 checkpointer 管理，它只是展示投影，不参与执行判断，不是第二套执行状态。

不要新增：

- chat_steps
- custom checkpoints
- 第二套执行状态 / 事件状态机

现有 `chat/runs/`（`agent_runs` / `agent_events` / 租约 / `tool_invocations`）是 P1–P5 过渡实现，**不是最终形态**：目标是在 Aegra Runtime 落地后收敛移除（`docs/architecture.md`）。收敛完成前不得扩展其语义或叠加新机制。

恢复与并发约定（**Aegra 版定稿**，详见 `docs/architecture.md`）：

- 执行状态唯一事实源 = LangGraph checkpoint（AsyncPostgresSaver）。
- PostgreSQL = 数据层（LangGraph checkpoint + Aegra 表 + 业务表）；Redis = Aegra Runtime 依赖（job 队列 + SSE 广播/回放 + cancel），非自研协调层。
- 恢复语义 = 同一 `thread_id` 从 checkpoint 继续执行，绝不重发用户消息。
- 多实例并发推进由 Aegra PG 原子 lease 互斥；重复副作用由幂等工具台账防住。
- 滚动部署 = SIGTERM → `WORKER_DRAIN_TIMEOUT` 排水 → 未完成 run 自动 requeue → 新实例从 checkpoint 续跑。
- 验收口径 = 文字内容完整 + 事件进度展示完整；不要求逐 token 流式。

---

## Skill 约束

产品运行时 Skill 放在 Agent 模块：

```text
backend/app/agent/skills/
```

例如：

```text
backend/app/agent/skills/travel-planning/SKILL.md
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

Agent Chat 前端使用 `@langchain/react`（LangGraph 官方统一 React SDK）作为 Agent Runtime 连接层，shadcn/ui 作为通用 UI 组件库：

```text
Chat 页面（frontend/src/components/Chat/，当前为手写组件）
  ↓
StreamProvider / useStreamContext / HttpAgentServerAdapter（@langchain/react）
  ↓
HTTP POST + LangGraph stream SSE
  ↓
FastAPI + LangGraph
```

前端技术选型约束：

- **@langchain/react**：Agent Runtime 连接层（`useStream` / `useStreamContext` / `StreamProvider` / `HttpAgentServerAdapter`），管理 messages、thread state、streaming、interrupt/resume。不要用 `@ai-sdk/react` 的 `useChat`、DefaultChatTransport 或自研 SSE parser 重建这套连接。
- **assistant-ui**：当前未引入。若未来引入，必须是明确的产品决策并同步更新本文件；不得为了"规范"同时维护两套 Chat 组件。
- **shadcn/ui**：通用 UI（Button、Dialog、Input、Select 等）的唯一组件来源，项目自己的非 Chat 组件统一用它。

后端协议边界固定在：

```text
chat/protocol/
  LangGraph stream events → LangGraph server compatible SSE response
```

网络协议使用 **LangGraph stream protocol**。FastAPI 通过 LangGraph 的 streaming 接口（`astream` / `astream_events`）将 Agent 执行结果以 LangGraph 兼容的 SSE 格式返回，`useStream` 直接消费。

业务特有的 activity、progress、approval 等信息通过 LangGraph stream 的 `custom` mode events 或 `ui_message` generative UI 传递，不另造平行事件协议。

AI SDK（`@ai-sdk/react`、`ai`、`@ai-sdk/*`）不再用于 Agent Chat 前端。仅在普通 REST 表单和 OpenAPI client 中保留 TypeScript 类型。

---

## 基础设施决策原则

任何基础设施由可验证需求驱动，选择当前需求下最简方案，并把决策写入 `docs/architecture.md`；不要为了简历关键词增加基础设施。

已引入 / 已定稿：

- PostgreSQL（数据层：LangGraph checkpoint + Aegra 表 + 业务表）
- Redis（**Aegra Runtime 依赖**：job 队列 + SSE 广播/回放 + cancel；非自研协调层）
- Aegra（自托管 Agent Runtime，实测 0.10.4：worker / lease / reaper / drain / SSE 回放，`docs/aegra-evaluation.md`）

当前未引入（出现真实需求时先评估最小方案，再决定是否引入）：

- LiteLLM / LLM Gateway（自研 provider 框架同样禁止）
- LangSmith（可观测性先用应用内结构化日志 + run 级事件顶住）
- Celery / Kafka / Temporal / DBOS / Inngest / 自研 durable runtime
- 传统 RAG / 向量数据库（第一阶段）
- Vercel AI SDK（@ai-sdk/react / ai）作为 Agent Chat 前端协议

部署形态：不依赖 K8s 平台 API 才能保证正确性；兼容普通服务器与 K8s 滚动发布（draining + 健康检查，见 `docs/architecture.md`）。

---

## 官方 API 与文档

LangChain / LangGraph / @langchain/react API 变化较快。

实现新能力前必须优先检查 **当前官方文档和当前安装版本**，不要仅凭旧课程、旧示例或模型记忆猜 API。

课程用于理解工程问题；当前官方框架用于决定实际实现方式。

---

## 完成标准

一个修改只有在产生可验证产出时才算完成：

- 代码可运行
- 对应测试通过；Agent 行为改动（prompt / graph / tool / 恢复语义）要有回归验证（e2e 或验收清单）
- lint/type-check 不因本次改动新增错误
- 架构没有增加重复 source of truth
- 能说明为什么使用框架能力、为什么某些治理需要应用自己实现
- 文档同步：涉及架构/协议/数据模型的改动，`AGENTS.md` / `docs/architecture.md` 必须与代码一致，不得出现"文档说已落地但代码没有"

Agent 项目特有的验收口径（目标，见 `docs/architecture.md`）：

- 浏览器刷新恢复、SSE 断线重连补事件、多 worker 执行状态一致、滚动部署不丢内容
- 验收 = 文字内容完整 + 事件进度展示完整；不把逐 token 动画当承诺

优先可运行的面试项目，而不是追求覆盖所有课程章节。
