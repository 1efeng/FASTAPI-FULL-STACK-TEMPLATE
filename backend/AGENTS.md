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
│   ├── chat/          # Agent 主业务
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
- SSE boundary
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

优先保持 feature-local：

```text
app/chat/
├── api.py
├── schema.py
├── agent.py
└── skills/
```

文件只在真实需求出现时新增：

- `events.py`: 有稳定 SSE event protocol 时
- `tools.py`: 有 Tool 时
- `middleware.py`: 有 Tool/Agent 横切治理时
- `graph.py`: 开始低层 StateGraph orchestration 时
- `state.py`: Graph state 独立后
- `runtime.py`: API 已被 checkpoint/thread/resume/stream lifecycle 明显撑大时

不要创建空目录或占位抽象预测未来复杂度。

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

- unit tests for policy/business boundaries
- streaming contract tests
- tool side-effect/idempotency tests
- interrupt/resume tests
- recovery tests

不要依赖真实付费模型才能跑完核心测试；为模型调用提供测试 fake/mock。