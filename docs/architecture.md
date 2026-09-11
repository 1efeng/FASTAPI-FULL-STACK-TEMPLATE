# 架构设计：Aegra 版 Resumable Agent Application（定稿）

> 状态：**定稿**（2026-09-11）。本文是项目唯一架构依据。
> 旧设计（自研 Redis 协调层 / P1–P5 / chat_messages 规格）已归档到 `docs/archive/`。
> 实测证据见 `docs/aegra-evaluation.md`；协议澄清（v2 传输协议 vs v3 runtime 事件）见该文档 §2。

## 1. 背景与决策

项目曾两度自研"Resumable Agent 协调层"（P1–P5 的 `agent_runs/agent_events/db_stream`，以及"自研 Redis Stream 事件总线 + 分布式锁"版），核心痛点是：**应用层在重复实现运行时能力，且自研版能力更弱**（没有跨实例 SSE、没有 lease/reaper、没有 drain 交接）。

经实测评估后定稿：**Runtime 交给 Aegra（自托管开源 server，Apache 2.0，实测 0.10.4），应用只补治理**。

- Aegra 单进程内置：Redis job queue + worker、PG lease + heartbeat + reaper、Redis Pub/Sub SSE 广播 + 有界回放、SIGTERM drain 交接、跨实例 cancel、Redis 不可用时 PG 轮询降级。
- 协议兼容：Aegra 原生提供 LangGraph Agent Protocol **v2**（`/commands` + `/threads/{id}/stream/events`），前端 `@langchain/react` `HttpAgentServerAdapter` 直连即可，spike 已端到端实测。
- 执行状态唯一事实源仍是 **LangGraph checkpoint（AsyncPostgresSaver）**，Aegra 在同一 PG 上初始化；不新增第二套执行状态。

### 为什么是 Aegra 而不是自研/Temporal/LangGraph Platform

| 方案 | 结论 |
| --- | --- |
| 自研协调层 | 重复实现成熟运行时；无 lease/reaper/drain/跨实例，稳定性不可比 |
| Temporal / Inngest / DBOS | 引入独立编排平台与运维成本，超出"Resumable Agent"范围（AGENTS.md 明确不引入） |
| LangGraph Platform（云） | 托管平台，成本与数据主权问题；Aegra 是其自托管开源替代 |
| **Aegra（自托管）** | ✅ 1.2k star / Apache 2.0；与现有 LangGraph + 前端 SDK 协议原生兼容；开箱即得上述运行时能力 |

## 2. 目标与非目标

### 目标

1. 浏览器刷新后 agent 继续执行，重新打开后内容与进度完整恢复。
2. SSE 断线后重连，内容与进度完整（任意实例可回放 + 实时续流）。
3. 多实例部署 / 滚动发布：旧实例优雅 drain，未完成 run 自动 requeue，新实例从 checkpoint 续跑。
4. 进程崩溃后自动恢复：lease 过期 → reaper 重新入队 → 其他实例接管。
5. 工具调用基础幂等（应用层，Aegra 不提供）。
6. 验收口径：文字内容完整 + 事件进度展示完整；不要求逐 token 动画。

### 非目标（明确不做）

- 自研 job 队列 / worker / lease / reaper / drain（Aegra 已提供）。
- 自研事件总线 / SSE 回放（Aegra Redis broker 已提供）。
- Temporal / DBOS / Inngest / ARQ / k8s 编排 / 自研 durable runtime。
- 完整多租户权限、审计平台、RBAC（应用只保留最小 owner 隔离）。
- `chat_messages` 表（**延后**：Aegra `values` 快照可渲染完整消息；是否建表待真实产品需求，见 §6.3）。

## 3. 分层架构

```text
Browser（React，当前手写 Chat 组件，无 assistant-ui）
  └─ @langchain/react useStream + HttpAgentServerAdapter（v2 协议）
       ├─ POST /threads/{id}/commands          run.start / input.respond / run.resume
       ├─ POST /threads/{id}/stream/events      SSE（seq 游标 / event_id 去重）
       └─ GET  /threads/{id}/state              checkpoint hydrate
                  │
        Nginx / SLB（多实例，无状态）
                  │
   ┌──────────────┴──────────────┐
   Aegra Instance A         Aegra Instance B
   （aegra serve，API + SSE broker + worker + reaper）
                  │
        ┌─────────┴───────────┐
     PostgreSQL            Redis
        ├─ Aegra 表（threads/runs/…）
        ├─ LangGraph checkpoint（AsyncPostgresSaver，执行事实源）
        └─ 业务表（user、tool_invocations 等）
                           ├─ job queue（BLPOP）
                           ├─ SSE Pub/Sub 广播
                           ├─ SSE replay 缓冲（1h）
                           └─ cancel 命令通道
```

### 职责划分

| 组件 | 职责 | 边界 |
| --- | --- | --- |
| LangGraph checkpoint（PG） | 执行状态、消息、中断的唯一事实源；恢复/续跑从它读 | 不直接作为 UI 展示源（values 快照渲染） |
| Aegra run 表（PG） | run 生命周期（pending/running/success/error…）、执行参数、lease 字段 | 由 Aegra 迁移管理，应用不建 SQLAlchemy model |
| Aegra worker + lease + reaper | 后台执行、独占租约、崩溃回收 | 框架能力，不应用重实现 |
| Redis | job 队列 + SSE 广播/回放 + cancel 通道 +（reaper 兜底） | 有界非权威，丢流不影响内容（checkpoint 兜底） |
| 应用层（保留） | 认证/owner 隔离、工具幂等、业务风险策略、v2 custom 信封适配 | 只补 Aegra 不解决的治理 |
| `useStream` / `HttpAgentServerAdapter` | 前端唯一 Agent Runtime 连接层 | 不引入自研 SSE parser |

## 4. 核心流程

### 4.1 普通对话（后台 run）

1. 前端 `useStream.submit()` → `POST /threads/{id}/commands`（`run.start`）。
2. Aegra API 校验并持久化 run（status=pending），`RPUSH aegra:jobs`。
3. 任意实例的 worker `BLPOP` 拾起 → PG 原子获取 lease → 执行 graph → 每事件 `PUBLISH` + `RPUSH` replay。
4. 前端经 `POST /threads/{id}/stream/events` 收 SSE，`values`/`custom` 渲染内容与进度。
5. 完成后 worker 原子 finalize（status=success，释放 lease，置 done key）。

### 4.2 SSE 断线重连

- v1：`GET /threads/{tid}/runs/{rid}/stream` + `Last-Event-ID`，服务端从 replay 缓冲补漏。
- v2（前端同款）：`POST /threads/{id}/stream/events` 携带 `since`（= 最后 seq）；SDK 侧重连走全量回放 + `event_id` 去重，内容由 `values`/checkpoint 兜底。
- 实测：断在 event_45，带 `Last-Event-ID` 重连补 event_47…547，23 + 251 = 274 全部事件，无重复无遗漏（`docs/aegra-evaluation.md` Test A/B3）。

### 4.3 刷新恢复

- run 是后台任务，不依赖浏览器连接：刷新不取消执行。
- 刷新后 `useStream` 重新挂载：先 `GET state`（checkpoint hydrate）恢复完整内容，再订阅 SSE 实时续流；事件源在 Redis，任意实例可服务。

### 4.4 滚动部署 / 优雅退出

1. SLB 摘流旧实例 → 发 SIGTERM。
2. Aegra executor 进入 drain：等待在途 run 至多 `WORKER_DRAIN_TIMEOUT`（默认 30s，建议 30s）。
3. 窗口内没跑完的 run：**不 finalize**，reset 为 pending、清 lease、重新入队（不消费重试预算）。
4. 新实例 worker 拾起 → 从 checkpoint 续跑 → 事件继续广播。
5. SSE 代理若随旧实例关闭，客户端按 §4.2 重连补事件。
6. 实测：B 执行中 SIGINT → drain → requeue → A 接管续跑 120.4s success（`docs/aegra-evaluation.md` Test B3）。

### 4.5 崩溃恢复

- worker 崩溃 → heartbeat 停止 → lease（30s）过期。
- reaper（15s 扫描）把过期 run reset 为 pending、清 owner、重新入队，递增 `_retry_count`；新 worker 从 checkpoint 续跑；超过 `BG_JOB_MAX_RETRIES`（默认 3）标记 error。
- Redis 不可用时：worker 降级为 PG 轮询 pending（`POSTGRES_POLL_INTERVAL_SECONDS`）。

### 4.6 取消

- 跨实例 cancel：API 先做所有权安全 DB 更新（无 owner 或 lease 过期则直接中断并清租约）；有存活 owner 则经 Redis Pub/Sub 通知该 worker `task.cancel()` 并 finalize。用户主动 cancel 最终态为 `interrupted`，**drain 不会复活已取消 run**。

## 5. 关键参数（Aegra 环境变量，可配）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `REDIS_BROKER_ENABLED` | false | 生产多实例必须 true |
| `WORKER_COUNT` / `N_JOBS_PER_WORKER` | 2 / 4（1w DAU 基线） | 单实例并发容量 = 乘积；压测后再扩容 |
| `LEASE_DURATION_SECONDS` | 30 | 租约 TTL |
| `HEARTBEAT_INTERVAL_SECONDS` | 10 | 续租频率 |
| `REAPER_INTERVAL_SECONDS` | 15 | 过期 lease 扫描 |
| `WORKER_DRAIN_TIMEOUT` | 30.0 | SIGTERM 排水等待，超时未完成 run requeue |
| `BG_JOB_MAX_RETRIES` | 3 | 崩溃重试上限 |
| `STUCK_PENDING_THRESHOLD_SECONDS` | 120 | 卡 pending 重新入队阈值 |
| `BG_JOB_TIMEOUT_SECS` | 3600 | 单 run 最大执行时长 |
| `FF_V2_EVENT_STREAMING` | true | v2 协议开关（回滚用） |

## 6. 数据与状态

### 6.1 LangGraph checkpoint（唯一执行事实源）

- `AsyncPostgresSaver` 管理 checkpoint 表（`checkpoint_*`），由 Aegra 初始化。
- 恢复 = 基于 `thread_id` 从 checkpoint 继续执行（`run.start` 对已存在线程即 resume），绝不重发用户消息。

### 6.2 Aegra 表

- `threads` / `runs`（含 `execution_params`、`claimed_by`、`lease_expires_at`、`_retry_count`）、事件回放等，由 Aegra 迁移管理。
- 应用**不建 SQLAlchemy model、不通过 Alembic 重复管理**这些表。

### 6.3 消息读模型（`chat_messages` 延后）

- Aegra 的 `values` 快照 + replay 已能渲染完整消息；刷新/重连不依赖专门读模型。
- 会话列表/标题/搜索等真实产品需求出现前**不建表**。规格保留在 `docs/archive/messages-chat-messages-readmodel-v1.md`。

### 6.4 工具幂等（应用层，Aegra 不提供）

- 保留应用级 `tool_invocations` 台账：执行 tool 前按 `idempotency_key` 查询已有成功结果，命中直接返回，避免恢复/重试重复副作用。
- 只做基础幂等，不做完整 Tool Runtime。

## 7. 接口清单

| 方法 | 路径 | 语义 |
| --- | --- | --- |
| POST | `/threads/{id}/commands` | v2 命令：`run.start` / `input.respond` / `run.resume` |
| POST | `/threads/{id}/stream/events` | v2 SSE：channels 过滤 + `since` 续流 |
| GET | `/threads/{id}/state` | checkpoint hydrate（SDK 挂载用） |
| POST | `/threads/{tid}/runs` | 创建后台 run（返回 run_id） |
| GET | `/threads/{tid}/runs/{rid}/stream` | v1 流，`Last-Event-ID` 重连 |
| GET | `/threads/{tid}/runs/{rid}` | run 状态查询 |
| POST | `/threads/{tid}/runs/{rid}/cancel` | 跨实例取消 |
| GET | `/health` `/ready` `/live` | 健康检查 |

## 8. 部署与优雅退出

### 8.1 1w DAU 单机基线

默认生产入口是仓库根目录的 `compose.production.yml`：FastAPI、Aegra、
PostgreSQL、Redis 由同一套 Compose 管理，Aegra 先运行单实例
（`WORKER_COUNT=2`、`N_JOBS_PER_WORKER=4`）。Aegra migration 由一次性
`aegra-migrate` 服务执行，应用和 Aegra 共用同一个 PostgreSQL。

```bash
docker compose -f compose.yml -f compose.production.yml up -d --build
```

React 构建时通过 `VITE_AEGRA_URL` 指向 HTTPS 的 `AGENT_DOMAIN`；Agent
Protocol/SSE 不经过 FastAPI 中转。

### 8.2 扩容形态

```text
Nginx / SLB
  ├── Aegra Instance A（aegra serve --port 2026，容器内 RUN_MIGRATIONS_ON_STARTUP 可选）
  └── Aegra Instance B（aegra serve --port 2026）
        │ shared
  PostgreSQL（Aegra 表 + LangGraph checkpoint + 业务表）
  Redis（job queue + SSE broker + replay + cancel + reaper 兜底）
```

- 滚动发布：SLB 摘流 → SIGTERM → drain（`WORKER_DRAIN_TIMEOUT`=30s，编排器 `terminationGracePeriodSeconds` 略大于 30s）→ requeue → 新实例续跑。
- 多 Pod 迁移：建议 `RUN_MIGRATIONS_ON_STARTUP=false`，发布前由 CI/init 容器执行一次 `aegra db upgrade`（避免 Alembic 锁竞争）。
- 本地演示：docker-compose（PG + Redis + 多实例 app）即可。

## 9. 验收场景

| Case | 场景 | 期望 |
| --- | --- | --- |
| 1 | 普通执行 | 对话完成，内容 + 事件进度完整展示 |
| 2 | 执行中刷新 | 内容完整恢复，实时续上 |
| 3 | SSE 断线重连 | 带游标补漏，无重复无遗漏 |
| 4 | 滚动部署 / 后端重启 | drain → 自动 requeue → 其他实例从 checkpoint 续跑 → success |
| 5 | worker 崩溃 | lease 过期 → reaper 重新入队 → 接管续跑 |
| 6 | 工具重复执行保护 | 幂等命中，恢复后不重复副作用 |

## 10. 实施顺序

1. ✅ **迁移 graph**：`travel-planning` graph 已迁到 `agent-runtime/` 并在 `aegra.json` 注册（`assistant_id="travel_planning"`）。
2. ✅ **删自研层**：`backend/app/chat/`、`backend/app/agent/` 已移除；auth 保留在 FastAPI，工具幂等台账保留在 `agent-runtime/src/travel_runtime/db.py`。
3. ✅ **前端接线**：`HttpAgentServerAdapter` 直连 Aegra v2；刷新复用同 thread；auto-resume 状态机未引入（Aegra 后台 run + SDK 重连已替代）。
4. ✅ **部署**：补 `compose.production.yml`（共享 PG/Redis、单实例 Aegra、一次性 migration、Traefik HTTPS 路由）；`agent-runtime/docker-compose.yml` 保留为多实例验证栈。
5. 🟡 **验收**：Case 1（普通执行）/ Case 2（执行中刷新恢复）已用真实 LLM 浏览器端到端验证（`AEGRA_E2E=1 bunx playwright test chat-recovery.verify`，登录→发送→流式完成→刷新→同 thread 恢复，2 passed）；Case 3–6（SSE 断线重连、滚动部署 drain、worker 崩溃 reaper、工具幂等回归）待真实部署验收。

## 11. 面试口径

**不要讲"纯自研版"，也不要说"就接了个开源"**，讲三幕收敛链路：

1. 自研打底：P1–P5 实现过 `agent_runs/agent_events/租约/db_stream`，踩了"应用层 state 与 checkpoint 双源"的坑，理解了 run 生命周期与断线补事件的难点。
2. build vs buy：拿自研版与自托管 Aegra 对比（lease/heartbeat/reaper/drain/SSE replay 开箱即得；不解决工具幂等与认证），结论是"Runtime 复用成熟实现，应用只补治理"——生产标准做法。
3. 落地与验证：graph 迁移、v2 custom 信封适配、工具幂等、多实例部署，并实测五类验收（含 drain 交接 23+251 事件无重复无遗漏）。

**Aegra 机制要能空手讲透**：BLPOP 队列 → PG 原子 lease → 10s heartbeat → 15s reaper → drain 时不 finalize 只 requeue → SSE 回放（Last-Event-ID / since + event_id 去重）→ 跨实例 cancel。详见 `docs/aegra-evaluation.md` §4。
