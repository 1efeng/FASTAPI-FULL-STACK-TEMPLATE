# Agent Engineering Platform — 实现步骤

> 执行分支：`agent101-foundation`
>
> 这是一份全项目执行清单。Chapter 1 的细化步骤以 `docs/chapter-01-implementation.md` 为准。

## 0. 当前目标架构

```text
React + TypeScript
        ↓
@ai-sdk/react useChat
        ↓
DefaultChatTransport
        ↓ AI SDK UIMessage[] / SSE
FastAPI
        ↓
chat/protocol/
        ↓
LangChain
        ↓
LangGraph
        ↓
PostgreSQL
```

边界：

- AI SDK = 前端 Chat 状态与 wire protocol
- FastAPI = HTTP/Auth/SSE boundary
- `chat/protocol/` = AI SDK ↔ LangChain/LangGraph 适配
- LangChain = model/tool/high-level agent abstraction
- LangGraph = 唯一 Agent Runtime
- PostgreSQL = application data + 后续 LangGraph checkpointer

不要再维护自定义 `useChatStream`、自定义 SSE event names 或第二套 Agent Runtime。

---

# Stage 1 — Chapter 1：Model Engineering

当前已经落地：

```text
backend/app/
├── agent/
│   ├── agent.py
│   ├── middleware.py
│   └── skills/
└── chat/
    ├── api.py
    ├── schema.py
    └── protocol/
        ├── __init__.py
        ├── messages.py
        └── stream.py
```

已实现：

- AI SDK 原生 `UIMessage[]` 请求进入 FastAPI
- `UIMessage[] → LangChain messages`
- LangChain `ChatModel.astream()`
- `AIMessageChunk → AI SDK UI Message Stream`
- 基础 system prompt
- `create_agent` + feature-local Skills/Filesystem middleware
- Travel Skill 由主 Agent 按需读取
- JWT `CurrentUser` boundary
- fake model protocol tests

剩余顺序：

1. 本地 `uv sync / pytest / ruff / mypy`。
2. 前端 `bun install / build`。
3. 配置真实 OpenAI-compatible model 做 E2E。
4. Stop / HTTP disconnect cancellation。
5. Provider error mapping。
6. latency / usage logging。
7. structured output 小示例。

Chapter 1 完成后再进入 Tool。

---

# Stage 2 — Chapter 2：Tool Calling + Tool Governance

目标：

```text
FastAPI
  ↓
LangChain create_agent
  ↓
LangGraph-backed Agent Runtime
  ↓
Tools
```

执行顺序：

1. 新增一个 READ Tool，例如 `get_weather` / `search_attractions`。
2. 使用官方 `@tool` + type hints/Pydantic。
3. 普通 Agent 主线使用当前官方 `create_agent`。
4. 在 `chat/protocol/` 扩展完整 Tool 协议：

```text
tool-input-start
tool-input-delta
tool-input-available
tool-output-available
tool-output-error
```

5. 前端复用 AI SDK `UIMessage.parts` / Tool UI，不新造 tool event store。
6. 使用官方 middleware 做通用 retry / limit / HITL 能力。
7. 应用自己实现业务治理：

```text
trusted user context
resource authorization
READ / WRITE / HIGH risk
side-effect idempotency
unknown outcome
reconciliation
audit
```

禁止自研：

```text
ToolRegistry
ToolExecutor
ToolRuntime
RetryEngine
ApprovalRuntime
MCP transport
```

完成标准：

```text
user
→ model chooses tool
→ tool executes
→ UI shows tool state
→ result returns to model
→ final answer
```

并且写 Tool 的 timeout 不会被当成安全可重试。

---

# Stage 3 — Chapter 3：LangGraph Agent Runtime

目标：从高层 `create_agent` 进入可讲清底层执行流的 StateGraph。

先做最小手写 ReAct Graph：

```text
START
  ↓
model_node
  ↓
should_continue
  ├─ tools → ToolNode → model_node
  └─ END
```

自己实现：

- State
- Node
- conditional routing
- loop / termination
- budget / convergence
- replan

继续复用：

- official ToolNode
- LangChain Tool schema/runtime
- LangGraph streaming

不要手写 generic Tool executor。

随后增加：

```text
plan
→ execute
→ evaluate
→ replan
→ finish
```

完成标准：

面试时能解释：

- `create_agent` 为何方便
- StateGraph 底层如何循环
- ToolMessage 如何反馈
- 什么时候 END
- 如何防止无限循环

---

# Stage 4 — Persistence + HITL

目标：把执行状态交给 LangGraph 官方 persistence。

使用：

```text
AsyncPostgresSaver
→ same PostgreSQL
```

原则：

- checkpoint table 由 LangGraph 管
- 不建 SQLAlchemy checkpoint model
- 不复制一套完整 run state

然后实现：

```text
interrupt()
→ approval required
→ Command(resume=...)
```

协议层扩展 AI SDK approval/tool part；前端不直接理解 LangGraph internal interrupt payload。

完成标准：

- restart 后 thread state 可恢复
- approval 可暂停/继续
- 不存在第二套 resume source of truth

---

# Stage 5 — Durable Side-effect Governance

LangGraph checkpoint 解决的是执行状态恢复，不自动解决外部副作用安全。

对 WRITE Tool 增加：

```text
authorization
→ idempotency check
→ side effect
→ persist result
→ audit
```

如果 timeout 后无法确认副作用是否成功：

```text
UNKNOWN
→ reconciliation
```

不要盲目 retry。

只有出现多个写 Tool 重复逻辑后，才抽：

```text
chat/governance/
├── idempotency.py
├── reconciliation.py
└── audit.py
```

完成标准：

测试覆盖：

- duplicate command
- provider timeout after possible write
- reconcile success/failure
- audit failure 不反向破坏已成功业务操作

---

# Stage 6 — Thread 产品能力

只有出现真实需求后再增加应用层 Thread 数据：

```text
thread title
owner
created_at
updated_at
archive/search
```

这类产品 metadata 可以用 SQLAlchemy。

不要因为 LangGraph 已经有 checkpoint，就复制保存完整 message/state；也不要因为需要 sidebar，就把 checkpoint 当产品数据库直接暴露给 UI。

完成标准：

```text
ChatThread application data
≠
LangGraph execution checkpoint
```

职责清楚。

---

# Stage 7 — E2E / Recovery / Interview Packaging

最终必须自动化验证：

```text
登录
→ 发消息
→ 文本流
→ Tool
→ Tool result
→ final answer
→ Stop
→ retry/error
→ approval interrupt
→ resume
→ process restart recovery
```

再补：

- README architecture diagram
- 运行方式
- `.env.example`
- 演示截图/GIF（需要时）
- 面试项目讲法
- 核心 trade-off

不要用“学习了多少章节”定义项目完成度。

项目完成的可观测结果是：

- repository runnable
- tests green
- demo reproducible
- architecture explainable
- 简历能写清问题、设计、实现、结果

---

# 当前下一步

不要继续扩架构。

现在只做 Chapter 1 剩余项：

```text
1. 本地验证依赖/测试/build
2. 真实模型流式 E2E
3. cancellation
4. error mapping
5. latency / usage
6. structured output
```

完成这六项，再进入 Chapter 2 Tool Calling。
