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
│   ├── chat/          # Chat HTTP / LangGraph stream 协议
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
- LangGraph stream protocol / SSE boundary
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
- `schema.py`: LangGraph SDK transport request boundary
- `agent/agent.py`: LangChain ChatModel + create_agent + server-owned system instructions
- `agent/middleware.py`: Skill catalog and read-only skill file middleware
- `protocol/messages.py`: LangGraph SDK `UIMessage[]` → LangChain messages
- `protocol/stream.py`: LangChain/LangGraph output → LangGraph stream protocol SSE
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

前端使用 assistant-ui 作为 Chat UI 组件层，`@langchain/langgraph-sdk/react` 的 `useStream` 作为 Agent Runtime 连接层。

请求保持 LangGraph SDK 原生形状（`messages`、`thread_id`、`stream_mode`），后端在 `protocol/messages.py` 转为 LangChain messages。

`/chat/stream` 返回 **LangGraph stream protocol** SSE，而不是应用自定义 event names，也不是 AI SDK UI Message Stream。

响应遵循 LangGraph stream 的 SSE 格式，`useStream` 直接消费 `messages` / `updates` / `custom` 等 stream mode 事件。

LangChain/LangGraph 原始 chunk 不直接透传给浏览器。边界必须是：

```text
LangChain / LangGraph stream
  ↓
chat/protocol/
  ↓
LangGraph stream protocol SSE
  ↓
useStream / assistant-ui
```

Chapter 1 只实现完整文本 Chat subset。Tool、Approval、Reasoning、Sources 等在对应章节出现时，再在同一个 `protocol/` 目录扩展 LangGraph stream 已定义的事件类型；产品特有 progress/activity 使用 `custom` stream mode event 或 `ui_message` generative UI，不再维护平行协议。

AI SDK（`@ai-sdk/react`、`ai`）仅是历史遗留的普通 REST 表单和 OpenAPI client 类型来源，不参与 Agent Chat 协议。

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
