# AGENTS.md — Travel Agent v8.2 Control Tower

> 更新时间：2026-08-13  
> 当前架构 SOT：`docs/架构v8.md`（v8.2 / Accepted / Architecture SOT）  
> 当前代码基线：`travel_agent_v8 @ e9d959e5c250cc8628beac8df642f65b5be71b14`

---

# 1. 开工阅读顺序

每次开工必须按顺序阅读：

1. `AGENTS.md`
2. `docs/架构v8.md`
3. `docs/施工路线图.md`
4. 当前任务对应专项 Contract
5. 当前真实代码
6. `backend/pyproject.toml`
7. `uv.lock`
8. 前端任务额外阅读 `frontend/package.json`
9. Streaming 任务额外阅读 `backend/app/infra/stream_resume/README.md`

如果文档与代码冲突：

```text
先确认真实代码
→ 判断哪个 SOT / Contract 过期
→ 先修正文档或明确 transitional debt
→ 再继续施工
```

禁止根据聊天记忆猜当前项目状态。

---

# 2. 当前真实状态

当前已经落地：

```text
FastAPI Product Runtime
PostgreSQL / Alembic
Auth / User / Item
Conversation / Message / RequestRun
POST /api/v1/chat
GET /api/v1/chat/requests/{request_id}
POST /api/v1/chat/requests/{request_id}/cancel
数据库幂等
Redis rate / quota / concurrency / cancel coordination
Absolute Deadline
LiteLLM Proxy infra
AgentExecutor thin port
RuntimeClock
StreamResumeStore port
RedisStreamResumeStore implementation
stream_resume unit tests + Redis integration test skeleton
React 19 + Vite 8 + TanStack Router / Query + Tailwind 4 / shadcn baseline
```

当前尚未落地：

```text
PydanticAI dependency / executor
AgentExecutionRequest.history
server-authoritative history projection
ExecutionSupervisor
PydanticAI VercelAIAdapter production wiring
@ai-sdk/react / ai
ProductChatTransport / useProductChat
AI Elements selected primitives
M8 full streaming E2E
DBOS / Temporal
```

当前已知 transitional debt：

```text
ChatService 当前仍监听 HTTP disconnect 并取消 execute task
→ M8 必须改为 disconnect 只 detach subscriber

AgentExecutor 当前仍是 thin execute(...) 参数
→ M3 hardening 必须升级为 AgentExecutionRequest(history)

StreamResumeStore 已落地但尚未接 Chat / PydanticAI
```

---

# 3. 当前架构分层

```text
React / Vite
  ↓
FastAPI Product Runtime
  ├ Auth / AuthZ
  ├ Conversation / Message / RequestRun
  ├ Idempotency / Rate / Quota / Concurrency
  ├ Deadline / Product Cancel
  └ Usage / Billing / Audit
  ↓
ExecutionSupervisor                 ← M8 target
  ↓
AgentExecutor                       ← framework-neutral port
  ↓
PydanticAI                          ← target execution engine
  ↓
LiteLLM
  ↓
Providers
```

Streaming side path：

```text
PydanticAI events
  ↓
VercelAIAdapter
  ↓
Lifecycle-aware Terminal Gate
  ↓
opaque encoded SSE chunks
  ↓
StreamResumeStore
  ↓
RedisStreamResumeStore
  ↓
FastAPI subscriber
  ↓
AI SDK ChatTransport / useChat
```

---

# 4. Ownership 强制规则

```text
FastAPI Product Runtime
→ Product lifecycle / AuthZ / Idempotency / RequestRun / Billing / durable history

AgentExecutor
→ 唯一 Product → Agent execution port

PydanticAI
→ agent loop / model calls / tools / MCP / structured output / capabilities

LiteLLM
→ production provider routing / credentials / fallback / gateway policy

PostgreSQL
→ Business SOT

Redis
→ distributed coordination

StreamResumeStore
→ active HTTP/UI stream re-attachment only

DBOS/Temporal future
→ process-crash execution durability
```

最重要的不变量：

```text
Business Conversation != Agent Runtime Thread
RequestRun != StreamState
StreamResumeStore != Execution Durability
Network disconnect != Product Cancel
Product Stop != AI SDK browser abort
Product DB 不出现 framework-specific identity
stream_id = str(request_id)
```

---

# 5. Durability 三分

```text
Business Durability
→ PostgreSQL

Active Stream Resume
→ StreamResumeStore
→ current RedisStreamResumeStore
   Redis KV state + Pub/Sub + producer-memory replay

Execution Durability
→ 当前无
→ future DBOS / Temporal
```

禁止把 Redis Pub/Sub、Redis Streams、Agent checkpoint 或 DBOS 混成一套统一“持久化”。

---

# 6. Streaming 强制规则

M8 production flow 必须满足：

```text
Product Start TX COMMIT
→ ExecutionSupervisor owns task
→ AgentExecutor
→ PydanticAI
→ VercelAIAdapter

non-terminal events
→ 可以实时发往 StreamResumeStore

Agent final
→ Product Success TX
→ INSERT assistant final
→ RequestRun running → completed CAS
→ COMMIT
→ 才允许 success terminal UI event
```

也就是：

> **UI success terminal event 永远不得早于 Product COMMIT。**

Transport emit 在 COMMIT 之后失败：

```text
PostgreSQL 仍然是 SOT
→ 不回滚 Product completed
→ reconnect / status / durable history 负责 reconciliation
```

---

# 7. Product Stop

唯一正确语义：

```text
POST /api/v1/chat/requests/{request_id}/cancel
→ ownership check
→ RequestRun running → cancelled CAS
→ publish Product cancellation signal
→ PydanticAI first-party cancellation
→ late final 不再 commit-eligible
```

禁止：

```text
useChat.stop() == Product Stop
browser fetch abort == Product Stop
StreamResumeStore.close() == Product Stop
HTTP disconnect == Product Stop
```

---

# 8. 当前 M0-M11

| Milestone | 状态 | 说明 |
|---|---|---|
| M0 Engineering Baseline | ✅ | Template / Python 3.14 / tests / Playwright |
| M1 Product / Infra Settings | ✅ | clean baseline |
| M2 Redis + LiteLLM | ✅/🟡 | Redis coordination ✅；LiteLLM gateway infra ✅，application wiring 🚧（属 Step 3） |
| M3 Generic Chat Agent Port | 🟡 | AgentExecutor 已有；history contract + PydanticAI 待接 |
| M4 Business Persistence | ✅ | Conversation / Message / RequestRun |
| M5 LangGraph Persistence | **SUPERSEDED** | 不再迁移 |
| M6 Product Lifecycle | ✅ / M8 harden | disconnect 行为仍需修正 |
| M7 Business Usage | 🚧 | usage / cost attribution |
| M8-Infra Stream Resume | ✅ LANDED | `infra/stream_resume` 已落地 |
| M8 AI Streaming | 🚧 | PydanticAI + AI SDK + supervisor + terminal gate |
| M9 C-End Generic Chat | 🚧 | UI / reconnect / Stop / reconciliation |
| M10 Observability / Security / Eval | 🚧 | |
| M11 Production Gate | 🚧 | multi-replica / failure drills / HA |

---

# 9. 当前施工顺序

```text
Step 1  StreamResumeStore boundary + real Redis hardening
Step 2  AgentExecutor history contract
Step 3  PydanticAI Core
Gate A  Generic non-streaming Chat
Step 4  AI SDK + Pydantic VercelAdapter compatibility spike
Step 5  ExecutionSupervisor
Step 6  lifecycle-aware streaming + terminal gate
Step 7  ProductChatTransport / reconnect
Gate B  M8 Production Streaming
Step 8  Harness capabilities
Step 9  M7/M9/M10/M11
Travel Domain only after Generic Chat production gate
```

---

# 10. 禁止事项

```text
❌ 再引入 DeepAgents / LangGraph / LangChain runtime
❌ 恢复 langgraph_thread_id 或新增 pydantic_thread_id
❌ Redis Streams 重新成为默认 Browser/Product contract
❌ Product code 直接拼 stream_resume private Redis keys
❌ StreamResumeStore 解析/重写 Vercel AI protocol
❌ PydanticAIExecutor 反向查询 Product repository
❌ Browser messages 直接作为 authoritative Agent history
❌ HTTP disconnect 取消 Agent execution
❌ Product Stop 直接调用 useChat.stop()
❌ success finish 早于 Product COMMIT
❌ StreamState 作为 RequestRunStatus
❌ 为 resume 新建 business stream_id
❌ 同时引入第二套 assistant/chat runtime
❌ 当前阶段宣称 producer process crash 可无损恢复
```

---

# 11. Codex 每轮执行规则

```text
1. 阅读 AGENTS.md + 架构 SOT + 当前 Contract
2. 检查当前真实代码
3. 明确 CURRENT / TARGET
4. 一轮只做一个最小架构任务
5. 增加 contract / integration / failure test
6. 跑相关 ruff / mypy / ty / pytest / frontend build / Playwright
7. 更新 docs/施工路线图.md
8. 如果改变 ownership / contract，同步更新对应 Markdown
9. 未验证能力不得标 ✅
10. 汇报下一步最小任务
```
