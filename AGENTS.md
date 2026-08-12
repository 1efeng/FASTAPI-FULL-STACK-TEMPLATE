# AGENTS.md — Travel Agent v8 Control Tower

> 更新时间：2026-08-13
> 当前架构 SOT：`docs/架构v8.md`（v8 clean baseline，Post-PydanticAI 前状态）

---

# 1. 开工阅读顺序

每次开工必须按顺序阅读：

1. `AGENTS.md`
2. `docs/架构v8.md`
3. `docs/施工路线图.md`
4. `docs/产品运行时契约.md`（如存在）
5. 当前任务对应 Contract
6. 当前真实代码
7. `backend/pyproject.toml`
8. `uv.lock`
9. 前端任务额外阅读 `frontend/package.json`

如果文档与代码冲突：

```text
先确认真实代码
→ 判断哪个 SOT 过期
→ 修正文档
→ 再继续开发
```

禁止根据聊天记忆猜当前项目状态。历史实现只从 `travel_agent_v7` Git 历史查阅，不把历史文档当作当前事实。

---

# 2. 当前真实状态（v8 Clean Baseline）

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
Business Conversation / Messages / RequestRun
AuthZ / Idempotency
Redis Rate / Quota / Concurrency
Absolute Deadline / Explicit Cancellation
POST /api/v1/chat
FastAPI → ChatService → AgentExecutor → 未配置实现
RuntimeClock（纯函数，`app/agent/context/runtime_clock.py`）
```

当前 **没有** Agent Framework 实现：Deep Agents / LangGraph / LangChain / LangSmith
已从代码、依赖、Settings、数据库 schema 中移除。`/api/v1/chat` 返回
503 `AgentRuntimeNotConfigured`，直到 Pydantic AI executor 接入（下一 milestone）。

---

# 3. M0–M6 状态矩阵

| Milestone | v8 状态 | 说明 |
|---|---|---|
| M0 工程基线 | ✅ | 模板 / Python 3.14 / Alembic / 测试 / Playwright / Item / Docker / Traefik |
| M1 Settings | ✅ | 已删除 LangGraph / LangSmith settings，保留 Product / Infra settings |
| M2 Redis | ✅ | `infra/redis.py` + `modules/chat/runtime.py` 原样保留 |
| M2 LiteLLM | ✅ | Gateway 保留；`infra/llm.py`（LangChain adapter）已删除 |
| M3 Generic Chat | 🟡→✅ | Product 语义保留；Agent 实现暂缺，PydanticAI 后恢复 ✅ |
| M3 RuntimeClock | ✅ | 纯函数保留，LangChain middleware 已删除 |
| M4 Business Persistence | ✅ | Conversation / Message / RequestRun 保留，`langgraph_thread_id` 已删 |
| M5 LangGraph Persistence | **SUPERSEDED** | 正式废弃：checkpoint / thread 映射 / 相关配置与依赖全部移除 |
| M6 Product Lifecycle | ✅ | AuthZ / Idempotency / Rate / Quota / Concurrency / Deadline / Cancel 完整保留 |

M5 的"需求"（restart survival / multi-instance / durable execution）并未消失，
重新分配为：Conversation durability → PostgreSQL；Stream durability → Redis Stream；
Execution durability → DBOS/Temporal（后续 M11 决策）。

---

# 4. 架构分层

```text
React / Vite
  ↓
FastAPI Product Runtime
  ├─ Auth / AuthZ
  ├─ Conversation / Message / RequestRun
  ├─ Idempotency / Rate / Quota / Concurrency
  ├─ Deadline / Explicit Cancellation
  └─ Usage / Billing / Audit
  ↓
AgentExecutor            ← app/modules/chat/executor.py（framework-neutral port）
  ↓
Pydantic AI              ← 下一 milestone
  ↓
LiteLLM
  ↓
Model Providers
```

## Framework Ownership

```text
FastAPI Product Runtime → Product semantics / AuthZ / Idempotency / Request lifecycle
AgentExecutor           → Agent 执行边界（唯一 port）
Pydantic AI             → Agent loop / model invocation / tools（下一阶段）
LiteLLM                 → LLM routing / retry / fallback / cost
PostgreSQL              → Business durable state
Redis                   → Business shared runtime state
OpenTelemetry           → Infrastructure observability
```

---

# 5. 强制不变量

```text
Product Runtime 只有一个；Agent Framework 不拥有 Product lifecycle / SOT。
Business Conversation != Agent Runtime Thread。
Product model 不出现 Agent Framework-specific identity（无 langgraph_thread_id，
也不允许 pydantic_thread_id / agent_thread_id）。
Conversation / Stream / Execution durability 分离。
Disconnect != Cancel；真正取消必须走 Product Cancel API。
Agent Framework 只能通过 AgentExecutor 接入。
浏览器不得绕过 FastAPI Product Lifecycle 直接访问 Agent Runtime。
```

---

# 6. 当前施工顺序（下一步）

1. 接 Pydantic AI Core（`feat(agent): introduce pydantic ai executor`）
   - 实现 `AgentExecutor`：ChatService → AgentExecutor → PydanticAIExecutor → Pydantic AI → LiteLLM
   - 恢复 M3 普通问答（/chat 从 503 恢复）
   - 不引入 Harness / Streaming / DBOS / Travel SubAgents
2. Pydantic AI Harness（Skills / Planning / SubAgents，按需）
3. M7 Business Usage Attribution
4. M8 PydanticAI + Vercel AI Streaming
5. M9 C-End Chat
6. M10 Observability / Security / Eval
7. M11 Production Durability / HA（DBOS 决策）

---

# 7. 禁止事项

禁止：

```text
一边删旧框架一边接 PydanticAI
删除 ChatService 后重写
删除 M4/M6 tests
修改 Product semantics 来迁就 Agent Framework
给 Conversation 加 pydantic thread id
把 Redis Stream 当 execution durability
把浏览器断线当 cancel
同时重构 RequestRun 状态机（cancelling/queued 以后单独设计）
重复造轮子：CustomCircuitBreaker / ProviderRouter / RetryBudgetManager /
CustomCheckpointSchema / ConversationSummarizer / EvalDashboard /
CustomAgentStreamingProtocol / CustomSSEDeltaParser
```

---

# 8. Codex 每轮执行规则

```text
1. 阅读 SOT
2. 检查真实代码
3. 确认当前 Milestone
4. 只做一个最小任务
5. 增加测试
6. 跑相关检查
7. 更新 docs/施工路线图.md
8. 未验证能力不得标记完成
9. 汇报下一步最小任务
```

禁止顺手提前做未来 Travel Tool、顺手重构无关模块。
