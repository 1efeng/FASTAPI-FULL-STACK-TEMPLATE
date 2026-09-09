# Backend AGENTS.md

本文件补充根目录 `AGENTS.md`，仅约束 `backend/`。

## 目录组织

采用 **业务模块优先 + 模块内轻分层**。

当前长期结构：

```text
backend/
├── app/
│   ├── core/          # config/security/deps/global response
│   ├── db/            # SQLAlchemy base/session/model registry
│   ├── common/        # 真正共享且稳定的少量代码
│   ├── auth/          # 认证业务
│   ├── user/          # 用户业务
│   ├── agent/         # Agent 执行能力
│   ├── chat/          # Chat HTTP / AI SDK 协议
│   ├── system/        # health/ops endpoints
│   ├── integrations/  # 第三方集成
│   └── main.py
├── alembic/
├── scripts/
└── tests/
```

不要重新引入全局：

- `modules/`
- `application/`
- `domain/`
- `runtime/`
- `services/`
- `repositories/`
- `agents/`

业务模块内部有真实需要时，再出现 `service.py` / `repository.py` / `model.py`。

## FastAPI

`api.py` 负责：

- request validation
- auth dependency
- HTTP status / response
- AI SDK UI Message Stream / SSE boundary
- client disconnect / cancellation

不要在 `api.py` 内堆模型初始化、LangGraph node、业务数据访问等执行细节。

但也不要为了“薄 API”创建只有一行转发的 Service/Facade。

## SQLAlchemy

- 使用 SQLAlchemy 2 async 风格。
- Repository 只做数据访问和 `flush/refresh`，不自行 `commit`。
- transaction boundary 由业务 service / use case 决定。
- 复用现有 `AsyncSession` dependency。
- 新 application model 必须注册到当前 model registry，确保 mapper/Alembic 可见。
- 不为 LangGraph checkpoint table 建 ORM model。

## Chat / Agent

Chapter 1 当前结构为：

```text
app/agent/
├── __init__.py
├── agent.py
├── middleware.py
└── skills/
app/chat/
├── api.py
├── schema.py
├── protocol/
│   ├── __init__.py
│   ├── messages.py
│   └── stream.py
```

职责：

- `api.py`: FastAPI/auth/StreamingResponse
- `schema.py`: AI SDK transport request boundary
- `agent/agent.py`: LangChain ChatModel + create_agent + server-owned system instructions
- `agent/middleware.py`: Skill catalog and read-only skill file middleware
- `protocol/messages.py`: AI SDK `UIMessage[]` → LangChain messages
- `protocol/stream.py`: LangChain/LangGraph output → AI SDK UI Message Stream
- `agent/skills/`: 产品运行时 Skill

后续文件只在真实需求出现时新增：

- `agent/tools.py`: 有 Tool 时
- `agent/middleware.py`: 有 Tool/Agent 横切治理时
- `agent/graph.py`: 开始低层 StateGraph orchestration 时
- `agent/state.py`: Graph state 独立后
- `agent/runtime.py`: Agent lifecycle 已被 checkpoint/thread/resume/stream 明显撑大时

`protocol/` 是协议适配，不是第二套 Runtime。不要另建 `events.py` 再维护平行事件协议。

不要创建空目录或占位抽象预测未来复杂度。

## Chat Streaming Protocol

前端使用 Vercel AI SDK `useChat + DefaultChatTransport`。请求保持 AI SDK 原生 `UIMessage[]`，后端在 `protocol/messages.py` 转为 LangChain messages。

`/chat/stream` 返回 **AI SDK UI Message Stream**，而不是应用自定义 SSE event names。

响应至少遵循当前 AI SDK wire contract：

```text
Content-Type: text/event-stream
x-vercel-ai-ui-message-stream: v1
```

文本 SSE frame：

```text
data: {"type":"start"}

data: {"type":"start-step"}

data: {"type":"text-start","id":"..."}

data: {"type":"text-delta","id":"...","delta":"..."}

data: {"type":"text-end","id":"..."}

data: {"type":"finish-step"}

data: {"type":"finish"}

data: [DONE]

```

同一个文本 part 必须先 `text-start`，再零个或多个 `text-delta`，最后 `text-end`，并保持相同 part id。

LangChain/LangGraph 原始 chunk 不直接透传给浏览器。边界必须是：

```text
LangChain / LangGraph stream
  ↓
chat/protocol/
  ↓
AI SDK UIMessageChunk
  ↓
SSE
```

Chapter 1 只实现完整文本 Chat subset。Tool、Approval、Reasoning、Sources 等在对应章节出现时，再在同一个 `protocol/` 目录扩展 AI SDK 已定义的 part；产品特有 progress/activity 使用 typed `data-*` part，不再维护平行 `run.started/message.delta/tool.started` 协议。

AI SDK 仅是前后端 Chat UI 协议，不参与后端 Agent Runtime。

## Tool Governance

Tool 的注册、参数 schema、ToolMessage、通用执行优先交给 LangChain/LangGraph。

应用必须在业务边界处理：

- trusted user context
- final resource authorization
- risk classification
- side-effect idempotency
- unknown outcome
- reconciliation
- audit

写 Tool 不能因为 timeout 就默认安全重试。

`user_id` 等可信身份必须来自 FastAPI `CurrentUser` / Agent runtime context，不能由 LLM 或请求 payload 自由指定。

## LangGraph Persistence

需要持久化后，优先使用官方 Postgres checkpointer。

同一个执行状态只保留一个 source of truth。

除非出现明确产品需求，不复制保存完整 LangGraph messages/state 到额外 application tables。

## Testing

改动后按影响范围执行：

```bash
uv sync
pytest
ruff check .
mypy app
```

若仓库当前命令不同，以现有 `pyproject.toml` / CI 为准。

新增 Agent 能力时优先补：

- protocol contract tests
- unit tests for policy/business boundaries
- tool side-effect/idempotency tests
- interrupt/resume tests
- recovery tests

不要依赖真实付费模型才能跑完核心测试；模型调用使用 fake/mock。
