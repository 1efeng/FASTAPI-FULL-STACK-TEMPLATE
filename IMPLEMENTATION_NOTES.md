# Implementation Notes — Travel Agent v7

> 更新时间：2026-08-11。这里只记录当前工作树中由代码或检查结果证实的实现，不把目标架构写成已完成状态。

## 当前真实基线

- 分支：`travel_agent_v7`，当前 HEAD 为 `3694126`；工作树包含本轮 Owner 更新和 M4 schema foundation 修改。
- Application Runtime：`1efeng/FASTAPI-FULL-STACK-TEMPLATE`。
- Python：`3.14.6`（`.python-version`、backend 约束与 Docker 镜像一致），不需要重建或降级。
- Backend：FastAPI `0.139+`、async SQLAlchemy 2、PostgreSQL、Alembic、JWT Auth、User/Item 模块。
- Frontend：React 19、Vite 8、TanStack Router、生成式 OpenAPI client；登录、账号、Admin 和 Items 示例页面仍存在。
- Runtime：Docker Compose 中 backend、PostgreSQL、Redis 与 LiteLLM 正在运行且 healthy；Traefik、Mailcatcher、Adminer、Playwright 等模板服务仍保留。
- 数据库：Alembic 当前 head 为 `c4f4d8a12b7e`，运行数据库已在该 head。

## 2026-08-10 Baseline Checks（历史快照）

- `uv lock --check`：通过，125 packages。
- `uv run ruff check backend/app backend/tests`：通过。
- `uv run mypy backend/app`：通过，52 source files。
- `uv run ty check backend/app`：通过。
- `uv run --project backend pytest -q backend`：78 passed，7 skipped，1 条第三方 Python 3.17 弃用预告。`pytest-asyncio` 已由 0.26.0 升级到 1.4.0，以适配 Python 3.14 并消除旧 event-loop policy 弃用调用。
- `docker compose build backend`：通过；其中 frontend `bun run build` 和 backend frozen dependency sync 均成功。
- `docker compose ps`：backend、PostgreSQL healthy。
- `GET /api/v1/utils/health/live`：`true`。
- `GET /api/v1/utils/health/ready`：`true`。
- `uv run alembic heads/current`：均为 `b7198f0d2c4a`。

## Milestone 1 Item 定位

`item` 保留为标准业务 Module 模板 / 参考实现，不属于 Travel Agent 核心业务。它用于给后续 `conversation`、`request_run`、`usage` 等模块提供统一实现范式：

- Backend：`backend/app/modules/item/` 的 API、model、repository、schema、service，并在应用路由与模型 metadata 中注册。
- Database：现有 Alembic 历史及 Item 表保留，用作 SQLAlchemy/Alembic 模式参考。
- Tests：`backend/tests/api/routes/test_items.py`、`backend/tests/utils/item.py` 及相关 fixture/引用保留，用作 Module 测试参考。
- Frontend：`frontend/src/routes/_layout/items.tsx`、`frontend/src/components/Items/`、Sidebar navigation、generated client/types 保留，用作全栈联调参考。

新增 Travel Agent 模块可以参考 Item 的目录分层和测试组织，但不得复制其简单 CRUD 语义来替代 conversation ownership、request lifecycle、idempotency 或 usage attribution 等业务契约。


## M0 逐项审计结果（历史快照，2026-08-10）

- M0-01～M0-07：已确认分支、工作树、根目录、backend/app、frontend、Compose 文件和 Alembic 状态。
- M0-08～M0-12：Python 3.14.6；backend `pyproject.toml` 与 `uv.lock` 已核对；`uv lock --check`、`uv sync --locked --all-groups` 通过，82 packages 可安装。
- M0-13～M0-20：Ruff、Mypy、ty 通过；backend pytest `66 passed`；PostgreSQL healthy；Alembic upgrade/current 为 `b7198f0d2c4a` head；FastAPI live/ready 为 `true`；`/docs` 返回 HTTP 200。
- M0-21～M0-26：本机没有 Bun，使用 Docker 固定 Bun/Playwright 环境完成依赖安装与构建；前端 Playwright smoke `62 passed`，覆盖登录、注册、用户设置、Item、Admin。
- M0-27～M0-33：Item 标准业务 Module 参考实现存在；Redis、LiteLLM、LangGraph PostgresSaver、LangSmith、OpenTelemetry 和 v6 代码均未接入当前 v7，v6 来源为 `/home/feng/vibecode/backend_v4`。
- M0-34～M0-35：本文件和 `docs/施工路线图.md` 已同步。

前端注册 smoke 曾断言旧错误文案；已将 `frontend/tests/sign-up.spec.ts` 对齐当前 backend 的 `User with this email already exists`，完整 62 项回归通过。
## 尚未实现或尚未迁入

- v6 Travel Agent Cognitive Core 仅迁入 RuntimeClock 语义并建立最小 Main Agent 组合入口；Travel Planning Skill、travel-researcher、Travel tools、CLI 仍未迁入。
- Redis、LiteLLM、Deep Agents 与 LangGraph AsyncPostgresSaver 已进入运行时；LangSmith 已有配置与模型 metadata 但尚未完成平台验证，OpenTelemetry infrastructure instrumentation 尚未接入。
- Conversation、Message、RequestRun、durable Chat lifecycle 与 request status API 已实现；business usage attribution 尚未实现。
- 同步 Travel Chat API 已实现 durable final；Native SSE、幂等重放、业务 quota/concurrency 与显式取消 API 尚未实现。
- AI Eval、生产多实例与 Travel C 端体验均未建立。

## 当前 Blockers

- 当前没有静态检查 blocker；LiteLLM failure-injection harness 的 Docker 路径仍需修正，本轮按用户确认勾选路线图三项，独立通过证据留待后续补充。
- v6 Cognitive Core 来源已确认：`/home/feng/vibecode/backend_v4`，分支 `travel_agent_v6`；迁移时只读提取既定语义，不整文件复制旧 composition/config/provider runtime。
- 前端本机没有 `bun`，但 Docker 构建阶段已使用固定 Bun 镜像成功完成 frontend build。

## 约束

- Framework Ownership 以 `AGENTS.md` 与 `docs/架构v7.md` 为准，不在实现快照中重新设计。
- 未经代码或测试证据，不把规划项标记为完成。

## Infrastructure Integration Foundation（2026-08-10）

已完成基础设施配置与运行时接入；当前已经进入最小同步 Chat 请求链路，但尚未完成 Phase A 的 Business Persistence / Request Lifecycle / Streaming：

- Redis：backend 依赖 `redis[hiredis]`；Settings 有 `REDIS_URL` / namespace；Compose 有 Redis 8 服务和持久化 volume；容器 smoke 返回 `PONG`。
- LiteLLM：Compose 增加独立 Proxy 服务、固定镜像配置入口和 `infra/litellm/config.yaml`；应用 Settings 有 `LITELLM_BASE_URL`、service key、logical model；Provider key 只留给 LiteLLM。
- LangGraph：backend 锁定 `langgraph` 与 `langgraph-checkpoint-postgres`；Settings 有 `LANGGRAPH_DATABASE_URL` / schema；尚未创建业务 graph 或运行 `AsyncPostgresSaver` setup。
- LangSmith：backend 锁定 `langsmith`；Settings 和 `.env.example` 已加入 tracing/project/endpoint，模型 metadata 已接入；LangSmith SaaS 平台 tracing 尚未完成验证。
- LiteLLM 数据库通过 `LITELLM_DATABASE_URL` 独立配置，默认指向 `litellm` 数据库；该数据库由 LiteLLM Proxy 自己执行其 migration，已在本地启动验证。

当前没有加入 OTel Collector；按架构决策，后续只按需增加基础设施 instrumentation，并将 LangSmith 作为主要 Trace 查看入口。

LiteLLM 本地健康检查：GET http://localhost:4000/health/liveliness 返回 I'm alive!；Redis 返回 PONG。
## M2-01 配置校验 + readiness smoke（2026-08-10）

- 已读取并核对当前 `.env`，未输出任何密钥值。
- Docker 环境变量已修正为服务名连接：`REDIS_URL=redis://redis:6379/0`、`LITELLM_BASE_URL=http://litellm:4000`。
- 新增 `GET /api/v1/utils/health/infrastructure`，同时检查 PostgreSQL、Redis、LiteLLM。
- Docker 实测返回：`{"postgres":"ok","redis":"ok","litellm":"ok"}`。
- `uv lock --check`、Ruff、Mypy、ty、backend pytest `66 passed` 均通过。
## M2-02 Redis 应用 lifespan + namespace + integration test（2026-08-10）

- `backend/app/infra/redis.py` 维护每个进程一个异步 Redis client/pool。
- FastAPI lifespan 在启动时初始化并执行 `PING`，关闭时释放连接。
- `namespaced_key()` 统一应用 Redis key 前缀，避免环境和业务键冲突。
- 已增加 namespace 单元测试与真实 Redis 生命周期集成测试；真实测试由 `RUN_REDIS_INTEGRATION=1` 显式启用。

## M3 配置系统字段清单（2026-08-10）

- Application：`APP_ENV` 运行环境、`APP_DEBUG` 调试开关、`REQUEST_DEADLINE_SECONDS` 请求截止时间。
- Database：`DATABASE_URL` 应用数据库连接；`LANGGRAPH_DATABASE_URL` LangGraph checkpoint 独立配置，当前允许连接同一 PostgreSQL 实例。
- Redis：`REDIS_URL` Redis 连接地址。
- LiteLLM：`LITELLM_BASE_URL` Proxy 地址、`LITELLM_SERVICE_KEY` 服务凭证、`LLM_LOGICAL_MODEL` 逻辑模型名。
- Agent Guard：递归、模型调用、工具调用上限，用于防止 Agent 失控。
- Observability：LangSmith 负责 AI Trace；`OTEL_SERVICE_NAME` / `OTLP_ENDPOINT` 仅用于按需补充基础设施 span。
- Travel Tools：Tavily、AMap、Weather Provider 配置保留占位；FX 不做，因此没有 FX Provider 配置。
- 生产环境缺少 LiteLLM service key 或 LangGraph 数据库连接时 fail-fast；Provider API key 归 LiteLLM 管理，不进入 FastAPI 模型路由。

## LiteLLM Gateway 实现记录（2026-08-10）

- LiteLLM 精确版本为 `1.96.0`，Compose 使用 OCI digest 固定镜像。
- 容器 healthcheck 使用镜像已有的 Python 标准库，不依赖镜像内未安装的 wget。
- 逻辑模型 `travel-agent-llm` 配置 DeepSeek primary、豆包 fallback、有限重试、call/stream timeout、cooldown、RPM、TPM 和最大并发。
- LiteLLM 使用独立 PostgreSQL 配置入口和 Redis shared state。
- 已生成并持久化 FastAPI 专用 Service Virtual Key；Application 只使用该 Key 和逻辑模型，不拥有 Provider Routing。
- LiteLLM readiness、Service Key 模型可见性、primary、fallback、token usage、Call ID 和 cost metadata 已完成真实验证。
- DeepSeek V4 Flash 自定义价格仅维护在 `infra/litellm/config.yaml` 的 deployment `model_info` 中，FastAPI 不维护价格。

## FastAPI → LiteLLM 模型边界记录（2026-08-10）

- `backend/app/infra/llm.py` 提供进程级 OpenAI-compatible client 和请求级 `build_model()`。
- builder 固定使用 `travel-agent-llm`、LiteLLM Service Virtual Key、Gateway `/v1` 地址、应用 deadline 与 `max_retries=0`。
- `X-Client-Request-Id` 传递 request_id；LiteLLM request metadata 与 LangSmith Runnable metadata 同步携带 request_id、trace_id、agent_role、logical_model 和业务 metadata。
- 强制 Chat Completions API（`use_responses_api=False`），避免 Gateway compatibility 边界被 SDK 自动切换。
- 真实 `ChatOpenAI → LiteLLM → DeepSeek` completion 已通过并返回 token usage。

## RuntimeClock 迁移（2026-08-10）

- 来源：`/home/feng/vibecode/backend_v4/middleware/runtime_clock.py`。
- 当前位置：`backend/app/agents/travel/middleware/runtime_clock.py`，归属 Travel Agent Cognitive Core 的 middleware 边界。
- 同步/异步 model-call middleware 会在每次模型调用前动态注入日期、星期、时间、时区和年份。
- 使用 `APP_TIMEZONE=Asia/Shanghai` 作为默认时区；拒绝 naive datetime，避免隐式时区推断。
- UTC→Asia/Shanghai 跨日、America/Los_Angeles 跨年及 naive datetime 测试通过。

## Deep Agents 最小集成记录（2026-08-10）

- 精确锁定 `deepagents==0.7.5`；`uv.lock` 当前解析 125 个包。
- `backend/app/agents/travel/agent.py` 是 Main Agent 唯一组合入口，调用官方 `create_deep_agent()`。
- Main Agent 显式注入 M6 `build_model()` 返回的 `ChatOpenAI`，不会使用 Deep Agents 默认 Provider；实际链路为 `Deep Agents → travel-agent-llm → LiteLLM → DeepSeek/fallback`。
- 主提示词位于 `backend/app/agents/travel/prompts/main.md`；RuntimeClock 通过 middleware 显式挂载。
- 本轮没有创建空的 Skills、Tools 或 Subagents 目录，也没有迁移 v6 业务能力。
- 单元 contract 测试验证逻辑模型、Gateway URL、禁用 SDK retry、request/trace metadata 和 middleware；真实 Deep Agent completion 经 LiteLLM 返回成功。
- 该集成记录时 backend baseline：Ruff、Mypy、ty 通过；pytest `78 passed, 7 skipped`。唯一 warning 来自 Deep Agents 间接依赖 `google-genai` 对 Python 3.17 的弃用预告，不是 Python 3.14 运行错误。

## FastAPI → Agent Chat 接口（2026-08-10）

- 初始切片新增受 Bearer Auth 保护的 `POST /api/v1/chat`，当时请求只接收非空 `message`，服务端生成 `request_id`。
- 调用链为 `FastAPI → ChatService → Deep Agents → LiteLLM → Provider`，响应返回 `request_id` 与最终 `content`。
- 已应用 `REQUEST_DEADLINE_SECONDS` 与 `AGENT_RECURSION_LIMIT`；模型超时、限流、不可用、Agent 递归上限及未知错误不会向客户端泄漏 Provider 异常。
- 直接调用运行中 Docker FastAPI 验证：登录 200、Chat 200，真实模型返回“API打通成功”。
- 该接口记录时 Mypy、ty 通过；pytest `78 passed, 7 skipped`，仍只有同一条第三方 Python 3.17 弃用预告；当前 Ruff 状态以本轮审计章节为准。
- 该初始切片当时不持久化 conversation/message/request_run；当前接口状态以本文后续 M4 章节为准。

## 本轮文档对齐审计（2026-08-11）

- uv lock --check：通过。
- Mypy：通过，56 source files。
- ty：通过。
- Backend pytest：81 passed, 7 skipped, 1 warning；failure-injection tests 本轮未完成独立执行，按用户确认将施工路线图中的 timeout/429/all-unavailable 三项标记为完成，独立 Docker 通过证据留待后续补充。
- Ruff：通过。
- 该节为实现 M4 前的审计快照；当前状态以本文后续 M4 章节为准。

## M4 Business Persistence Schema Foundation（2026-08-11）

- 已完整读取 `docs/数据库契约.md`，Business physical tables 使用 singular naming：`conversation`、`request_run`、`message`。
- 新增 SQLAlchemy 模型并集中注册到 `app.db.models`；Business Conversation ID 与独立 `langgraph_thread_id` 保持分离。
- `request_run` 已包含 user/conversation ownership 字段、用户作用域幂等唯一约束、四态 CHECK、终态时间 CHECK、单会话单 running partial unique index 和 running deadline index。
- `message` 已包含全局 identity `seq`、`request_id + role` 唯一约束、user/assistant role CHECK 和 conversation stable-order index。
- Alembic revision `c4f4d8a12b7e` 已应用到当前 PostgreSQL；三张表、FK cascade、约束和索引均已通过真实数据库测试。
- 定向 persistence schema tests：`6 passed`；完整 backend：`87 passed, 7 skipped, 1 warning`；Ruff、Mypy（61 source files）和 ty 均通过。
- `alembic check` 未发现新三表 drift，但仍报告既有 `user` column comment metadata drift；本轮不修改 Owner 已变更的旧 migration。
- 该 schema foundation 切片当时没有实现 Conversation CRUD、Chat durable transaction、RequestRun conditional transition 或 status API。

## M4 Conversation CRUD 与 Ownership（2026-08-11）

- 新增 `conversation` 模块的 schema、repository、service、API 分层，并在 FastAPI 注册 `/api/v1/conversations` 路由。
- 已实现创建、分页列表、详情、标题 PATCH 与软删除；列表按 `last_message_at DESC NULLS LAST, created_at DESC` 排序，详情按内部 `message.seq` 返回业务消息。
- 所有读写均强制 `current_user.id` 与 `deleted_at IS NULL`；普通用户和超级用户都不能绕过 ownership，越权与不存在统一返回 404，避免 IDOR 探测。
- Product API 不暴露 `user_id`、`langgraph_thread_id`、`deleted_at`、`message.seq` 或 `request_id`。
- 7 个 Conversation API 集成测试与 6 个 schema 测试定向执行：`13 passed`；完整 backend：`94 passed, 7 skipped, 1 warning`。
- Ruff check、Mypy（86 source files）与本切片 ty 检查通过；`ty check app tests` 另发现 4 个既有 integration test `pytest.skip` 调用签名诊断，不由本切片引入。
- 该 CRUD 切片当时没有改造同步 `POST /api/v1/chat`，也没有实现 durable user/assistant message transaction、RequestRun 状态转换或 status API。

## M4 Durable Request Start Transaction（2026-08-11）

- `POST /api/v1/chat` 现在要求 owned active `conversation_id` 与非空 `Idempotency-Key`，服务端生成的 `request_id` 直接作为 `request_run.id`。
- Agent 前置事务依次校验 `conversation.id + current_user.id + deleted_at IS NULL`，写入 `request_run(running)`、user message，并更新 `conversation.last_message_at`。
- 三项业务写入共用一个 AsyncSession transaction；只有 `COMMIT` 成功后才构建并调用 Agent，事务异常会显式 rollback。
- `started_at` 与绝对 `deadline_at` 已持久化；Business Conversation ID 作为 metadata 传给 Agent，但 `langgraph_thread_id` 仍保持独立且未进入 runtime wiring。
- Chat tests 共 `10 passed`，其中独立连接在 Agent invoke 内验证前置数据已提交，并通过强制 commit failure 验证零残留写入与 Agent 未调用；M4 定向测试共 `23 passed`。
- 完整 backend：`98 passed, 7 skipped, 1 warning`；Ruff、Mypy（87 source files）与本切片 ty 检查通过，`uv lock --check` 通过。
- 本切片只完成 start transaction；幂等重放语义、assistant final、completed/failed/cancelled conditional transition 与 request status API 尚未实现。



## M4 Durable Final / Terminal Lifecycle（2026-08-11）

- Agent 成功后在同一事务中插入 assistant message、条件更新 `request_run running → completed` 并更新 `conversation.last_message_at`；只有 COMMIT 成功才返回 Product success。
- Provider/Agent/Product 异常条件更新为 `failed` 并只保存 Product error code；任务取消使用 shield 持久化 `cancelled`。
- terminal transition 使用 `WHERE status = running`，取消与 final 竞争失败时回滚 assistant message，不能产生伪成功。
- 新增 `GET /api/v1/chat/requests/{request_id}`，按 `request_run.user_id` 鉴权，越权与不存在统一返回 404。

## M5 LangGraph Production Persistence（2026-08-11）

- 新增进程级 `LangGraphCheckpointRuntime`，使用官方 `AsyncPostgresSaver`、psycopg async pool 和独立 `LANGGRAPH_DATABASE_SCHEMA`；FastAPI lifespan 负责 setup/start/close。
- setup 使用 PostgreSQL advisory lock 防止多实例并发 migration；连接统一设置 schema search path，不自建 checkpoint ORM 或 migration。
- Main Agent 显式接入 checkpointer；Chat 仅将服务端保存的 `conversation.langgraph_thread_id` 作为 `configurable.thread_id`，Business Conversation ID 仍只用于产品资源与 metadata。
- 真实 PostgreSQL 测试验证 bootstrap、restart/resume、两个 runtime 实例共享状态、thread 隔离及官方 `adelete_thread` 删除。
- 本轮完整 backend：`106 passed, 7 skipped, 1 warning`；Ruff、Mypy、M4/M5 范围 ty 与 `uv lock --check` 通过。Alembic head/current 均为 `c4f4d8a12b7e`；`alembic check` 仍只报告既有 `user` comment drift。

## 当前 Phase A 状态（2026-08-11）

- M0/M1：模板、Python 3.14、Auth/User、Item Reference、Docker/Compose、Alembic 基线已由代码和测试验证。
- Infrastructure：Redis runtime、LiteLLM Gateway、Deep Agents 最小 Main、RuntimeClock 和同步 `POST /api/v1/chat` 已由代码和真实调用验证。
- M3 普通 Chat：当前为部分完成；已有认证、request_id、deadline 基础、recursion limit、基础错误映射和 Chat contract regression（包含 provider details leakage、timeout、rate-limit、unavailable）；ModelCallLimitMiddleware 仍未完成。
- M4：Business persistence、Conversation CRUD/ownership、durable start/final/failed/cancelled lifecycle、Request Status API 与 persistence tests 已完成。
- M5：AsyncPostgresSaver setup/lifespan、conversation ↔ thread mapping、restart/resume、多实例共享、隔离与删除策略测试已完成；M6 及之后仍未完成。
- Phase B：Travel Skill、Researcher、Search、Maps、Weather、Travel UI 均保持 Gate 前暂缓；当前代码没有这些能力。
- Frontend：`frontend/package.json` 尚未引入 `@langchain/react`、assistant-ui 或 `@assistant-ui/react-langchain`；未开始 M8 Streaming Spike。

## 当前下一步

根据施工路线图，下一个最小可执行任务是补齐 M3 ModelCallLimitMiddleware 与普通 Chat 无 Travel Tool 依赖回归，然后进入 M6 Product Request Lifecycle（AuthZ / Idempotency）。
