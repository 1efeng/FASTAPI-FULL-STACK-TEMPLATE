# Backend AGENTS.md

本文件补充根目录 `AGENTS.md`，仅约束 `backend/`。

## 定位

`backend/` 是 **FastAPI 应用服务**（认证、用户、普通 REST、静态前端托管），不再承载 Agent 执行。

Agent Runtime 与 LangGraph graph 已迁出到独立项目 `agent-runtime/`（Aegra 运行时包，`aegra serve` 启动）。根目录 `AGENTS.md` 的「前后端 Chat 协议」是跨项目协议约束；本文件只管 FastAPI 自身。

不要重新在 `backend/` 里引入：

- `app/chat/`、`app/agent/`、`protocol/`、`db_stream.py`
- Agent 执行状态、checkpoint、run 生命周期表
- 应用层 job 队列 / lease / reaper / drain

## 目录组织

采用 **业务模块优先 + 模块内轻分层**。

当前长期结构：

```text
backend/
├── app/
│   ├── core/          # config/security/deps/global response
│   ├── db/            # SQLAlchemy base/session/model registry
│   ├── auth/          # 认证业务（JWT 与 Aegra 共用 SECRET_KEY）
│   ├── user/          # 用户业务
│   ├── item/          # 模板示例业务
│   ├── demo/          # 模板示例业务
│   ├── system/        # health/ops endpoints
│   ├── integrations/  # 第三方集成
│   ├── frontend/      # 前端构建产物静态托管（构建时生成）
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

普通 REST 继续由 FastAPI 提供；Agent Chat 的流式边界由 Aegra v2（`/threads/{id}/commands` + `/stream/events` + `/state`）承担，`HttpAgentServerAdapter` 直连 Aegra，**不经过 FastAPI**。

不要在 `api.py` 内堆模型初始化、Agent node、业务数据访问等执行细节，但也不要为了“薄 API”创建只有一行转发的 Service/Facade。

## 与 Aegra 的认证边界

- 前端向 Aegra 透传 JWT（`Authorization: Bearer`），Aegra 侧 `agent-runtime/src/travel_runtime/auth.py` 用同一 `SECRET_KEY` 校验，`sub` 为 thread owner。
- FastAPI 是 JWT 的签发方（登录/注册）；`SECRET_KEY` 由根环境变量注入，两端保持一致。
- 不在 FastAPI 里复制 Aegra 的 token 校验逻辑；需要跨服务身份时复用同一 JWT，不引入第二套会话。

## SQLAlchemy

- 使用 SQLAlchemy 2 async 风格。
- Repository 只做数据访问和 `flush/refresh`，不自行 `commit`。
- transaction boundary 由业务 service / use case 决定。
- 复用现有 `AsyncSession` dependency。
- 新 application model 必须注册到当前 model registry，确保 mapper/Alembic 可见。
- 不为 LangGraph checkpoint table 建 ORM model（checkpoint 表由 Aegra/AsyncPostgresSaver 管理）。

## 业务数据与 Agent 数据的归属

- 业务数据（用户、会话元数据等真实产品数据出现时）→ FastAPI + SQLAlchemy。
- Agent 执行状态（messages / checkpoint / run 生命周期）→ Aegra + LangGraph AsyncPostgresSaver。
- 工具幂等台账 `tool_invocations` → `agent-runtime/src/travel_runtime/db.py`（Aegra 不提供，应用补治理），不在 backend 重复建表。

## Testing

改动后按影响范围执行：

```bash
uv sync
pytest
ruff check .
mypy app
```

若仓库当前命令不同，以现有 `pyproject.toml` / CI 为准。

Agent 能力（graph / tool / 恢复语义）的测试在 `agent-runtime/` 内维护，不依赖 backend 测试库。
