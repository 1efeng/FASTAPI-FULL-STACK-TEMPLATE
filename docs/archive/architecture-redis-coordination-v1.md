> ⚠️ 已归档（2026-09-11）：被 `docs/architecture.md`（Aegra 版定稿）取代。保留供历史参考与面试"自研 → 收敛"叙事。

# 架构设计：Resumable Agent Application（Redis 协调层版）

> 状态：目标设计（实施前定稿）。本文是项目收敛后的唯一架构依据，与 `docs/messages.md`、`AGENTS.md` 共同构成开发文档。

## 1. 背景与决策

项目曾实现 P1–P5 的"Agent Runtime 层"（`agent_runs`/`agent_events`/`tool_invocations`、租约、启动恢复、DB 事件回放、前端 auto-resume 状态机）。该层带来了两套恢复语义（应用层 vs LangGraph checkpoint），复杂度和面试收益不成比例，且与"LangGraph 是唯一 Agent Runtime"的原则冲突。

因此收敛为最简生产形态，并引入 **Redis 作为协调层**（与 AgentScope / Mastra 验证过的同一分工）：

- **PostgreSQL = 数据层**：LangGraph checkpoint（执行事实源）+ `chat_messages`（UI 读模型）。
- **Redis = 协调层**：事件流（广播 + 有界回放）+ 线程分布式锁；后续限流、缓存、会话复用同一实例。
- 执行状态**只由 LangGraph checkpoint 管理**，应用层不再维护第二套 run/step/event 状态机。
- 多实例滚动部署采用**30s 排水兜底 + 前端断流自动 resume 一次**，依赖 checkpoint，用户基本无感。
- 验收口径为**文字内容完整 + 事件进度展示完整**；不把逐 token 动画当承诺（后端回放会顺带包含，但不依赖）。

## 2. 目标与非目标

### 目标

1. 浏览器刷新后 agent 继续执行，页面重新打开后内容完整恢复。
2. SSE 断线后重连，内容与进度完整（任意实例可回放 + 实时续流）。
3. 多实例滚动部署：旧实例 30s 内优雅退出，前端自动 resume，新实例从 checkpoint 继续。
4. 多 worker 并发推进同一线程由 Redis 分布式锁互斥（TTL 租约，进程死亡自动过期）。
5. 执行状态唯一事实源 = LangGraph checkpoint；`chat_messages` 只是 UI 展示读模型。

### 非目标（明确不做）

- 进程被杀后的自动接管、完整 lease/fencing、调度器。
- 工具幂等台账（`tool_invocations`）。
- Temporal / DBOS / Inngest / ARQ / k8s 编排。
- 自研 workflow engine 或第二套 runtime。
- 会话列表、标题、搜索（只预留读模型，不做产品功能）。
- Redis 高可用（哨兵/集群）——本期单实例 Redis，属平台化范畴。

异常（进程崩溃、超过排水上限被取消）不自动恢复：用户同 thread 重发或前端自动 resume 一次，从 checkpoint 续跑。

## 3. 分层架构

```text
Browser (React + assistant-ui)
  └─ useStream (@langchain/langgraph-sdk/react)
       ├─ POST /threads/{id}/commands   run.start / run.resume
       ├─ POST /threads/{id}/stream     SSE ← Redis Stream（回放 + 实时）
       ├─ GET  /threads/{id}/state      checkpoint hydrate
       └─ GET  /threads/{id}/messages   读模型（长期内容，任意实例可读）
                  │
           FastAPI（多 worker，进程内 RunRegistry / drain）
                  │
           LangGraph create_agent   ←  唯一 Agent Runtime
                  │
        ┌─────────┴───────────┐
   AsyncPostgresSaver      Redis（协调层）
        │                    ├─ agent:stream:*  事件流（回放 + 实时）
     PostgreSQL             └─ agent:lock:*    分布式锁（SET NX PX，TTL 租约）
        ├─ checkpoint 表（执行事实源）
        └─ chat_messages（UI 展示读模型）
```

### 职责划分

| 组件 | 职责 | 边界 |
| --- | --- | --- |
| LangGraph checkpoint（PG） | 执行状态、消息、中断的唯一事实源；恢复/续跑都从它读 | 不直接作为 UI 展示源 |
| `chat_messages`（PG） | UI 展示读模型（投影），按 `message_id` 幂等写入，长期内容 | 不参与执行判断 |
| Redis Stream | 协议事件广播 + 有界回放，SSE 由任意实例服务 | 有界非权威，丢流不影响内容 |
| Redis 锁 | `agent:lock:{owner}:{thread}` SET NX PX，token + Lua 释放，TTL 即租约 | 最小互斥，不做自动接管 |
| RunRegistry（进程内） | 跟踪 asyncio 任务、drain/取消在途 run | 进程内语义，不是分布式锁 |
| `useStream` | 前端唯一 Agent Runtime 连接层 | 不引入自研 SSE parser |

## 4. 核心流程

### 4.1 正常对话

用户提交 → `run.start` → FastAPI 创建 asyncio 任务（先抢 Redis 锁）→ LangGraph `astream_events(v3)` → 每个协议事件 `XADD` 到 `agent:stream:{owner}:{thread}` → SSE 端点 `XREAD` 推送 → `useStream` 渲染。流结束后，后端从 checkpoint `aget_state` 快照 human/ai 最终消息，按 `message_id` 幂等 upsert 到 `chat_messages`。

### 4.2 刷新恢复

- run 是后端任务，不依赖浏览器连接：刷新不会取消执行（同一进程内）。
- 刷新后 `useStream` 重新挂载：先 `GET state`（checkpoint hydrate）恢复完整内容；再订阅 SSE——事件源在 Redis Stream，**任意 worker 都能回放 + 实时续流**，"静默 SSE"问题消失。

### 4.3 SSE 断线重连

- 带游标（`since`/`last_event_id`）：先 `XREAD` 回放漏掉的事件，再 `XREAD BLOCK` 进入实时；跨实例一致。
- 无游标（fresh mount）：只进实时，内容由 checkpoint hydrate 保证，避免与回放重复。
- 断流/部署（`stream.error`）：前端检测 run 在途 → 自动调用一次 `run.resume`（空参）→ 新实例抢 Redis 锁（旧实例未释放则 409，前端退避重试）→ 从 checkpoint 继续 → 事件写入 Redis Stream。再次失败才显示手动重试横幅。

### 4.4 滚动部署

1. SIGTERM → uvicorn 停止接新连接；lifespan 置 `draining` 标志（`/threads/*/commands` 返回 503）。
2. `RunRegistry.drain(AGENT_DRAIN_TIMEOUT=30s)`：等待在途 run 收尾，超时取消剩余任务。
3. SSE 订阅随连接关闭；进程快速退出（Redis Stream 不回丢，新实例可回放）。
4. 前端断流 → 自动 resume 一次 → 负载均衡路由到新实例 → 抢 Redis 锁 → 从 checkpoint 继续。
5. 短任务在排水期内正常完成；超时任务被取消后同样由 resume 续跑。用户基本无感。

## 5. 数据模型

### `chat_messages`（PG，UI 展示读模型 / 长期内容）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID PK | |
| `user_id` | FK `user.id` ON DELETE CASCADE | 数据隔离 |
| `thread_id` | str(128) | 用户可见线程 id |
| `seq` | int | 线程内单调递增，断线游标 |
| `message_id` | str | LangGraph 消息 id，幂等键 |
| `role` | str(16) | `human` / `ai` |
| `payload` | JSONB | 与 `protocol.serialize_message` 同构；AI 消息含 `tool_calls` |
| `created_at` | timestamptz | |

约束：`UNIQUE(user_id, thread_id, message_id)`；索引 `(user_id, thread_id, seq)`。

写入：run 流结束后从 checkpoint 快照 human/ai 最终消息，按 `message_id` 幂等 upsert（run 粒度，不追 token，避免半条消息污染）。

读取：`GET /threads/{thread_id}/messages?after_seq=`，按 `seq` 升序，owner 作用域。

### Redis 键布局（协调层，非权威数据）

| Key | 类型 | 说明 |
| --- | --- | --- |
| `agent:stream:{owner_id}:{thread_id}` | Stream | 适配后协议事件 `XADD`，`MAXLEN ~2000`（或 TTL）；条目 seq 与 SSE `id:` 对齐，供游标回放 |
| `agent:lock:{owner_id}:{thread_id}` | String | `SET NX PX`，值 = 随机 token + 实例标识；释放用 Lua 比对删除；TTL 默认 10min（可配） |

Redis Stream 是有界协调数据，**不是权威数据**：丢了不影响内容（checkpoint / `chat_messages` 兜底）。

## 6. 接口清单

| 方法 | 路径 | 语义 |
| --- | --- | --- |
| POST | `/threads/{thread_id}/commands` | `run.start`：新对话轮次，先抢锁再建任务；`run.resume`：空参 = 从 checkpoint 继续，有值 = interrupt resume（SDK 协议） |
| POST | `/threads/{thread_id}/stream` | SSE 订阅：有游标则 Redis Stream 回放 + 实时；无游标只实时 |
| GET | `/threads/{thread_id}/state` | checkpoint hydrate（SDK 挂载用） |
| GET | `/threads/{thread_id}/messages` | 读模型查询，`after_seq` 增量 |
| POST | `/threads/{thread_id}/runs/{run_id}/cancel` | 取消本进程在途 run（M0 保留） |

## 7. 部署与优雅退出

- `compose.yml` 新增 `redis` 服务，backend 依赖其健康；`REDIS_URL` 配置。
- `backend/Dockerfile` CMD：`uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --timeout-graceful-shutdown 45`。
  - `fastapi run` 不暴露 `--timeout-graceful-shutdown`；默认无超时会被 SSE 长连接拖死关停。
- `compose.yml` backend：`stop_grace_period: 60s`（> uvicorn 45s 兜底）。
- `AGENT_DRAIN_TIMEOUT`：默认 30s，环境变量可配；是"发布等待时长 vs 用户被打断概率"的取舍。
- `draining` 期间新命令返回 503，保证只出不进。

## 8. 边界与取舍（面试口径）

- **为什么 PG 存数据、Redis 管协调**：执行状态与内容要求持久、可查、事务（PG）；事件广播与锁要求低延迟 + 租约（Redis）。AgentScope / Mastra 都是同一分工。
- **为什么锁用 Redis 而不是 PG advisory lock**：协调统一到一个组件，不占用 PG 连接/池；`SET NX PX` + token 释放天然防进程死亡卡死（TTL 租约）。面试口径一句："PG 存数据、Redis 管协调"。
- **为什么不做完整租约/fencing/自动接管**：Redis 锁的 TTL 租约只保证互斥与自动释放；"进程被杀后主动捡活"仍需持久化触发器 + 启动恢复（平台化范畴），本期明确不做，异常由用户同 thread 重试或前端 resume 一次。
- **Redis 故障边界**：实时流退化（SSE 收不到事件）、锁失效退化为无互斥；内容恢复仍靠 PG checkpoint / `chat_messages`。Redis 是运行前提，compose 保证存活；高可用属平台化范畴。
- **双写一致性**：checkpoint 是可写事实源，`chat_messages` 是投影；run 结束后一次性幂等 upsert，允许短暂滞后，不参与执行判断。
- **resume ≠ 重发消息**：恢复语义是"继续执行"（`astream_events(None)`），绝不再发一条 human 消息，避免重复内容。

## 9. 验收场景

| Case | 场景 | 期望 |
| --- | --- | --- |
| 1 | 普通执行 | 对话完成，事件进 Redis Stream，消息写入 `chat_messages` |
| 2 | 执行中刷新 | 内容完整恢复；实时续上 |
| 3 | SSE 断线重连 | 任意实例按游标回放 + 实时 |
| 4 | 滚动部署 | SIGTERM → 30s 排水 → 前端自动 resume → 新实例续跑，用户无感 |
| 5 | 手动 stop | 不触发自动 resume |
| 6 | 完成线程 resume | no-op，不重复内容 |
| 7 | 跨 worker 刷新 | 实时续上（Redis 广播，无需静默检测） |
| 8 | 同线程并发 resume | Redis 锁 409 + 退避，最终只有一个进程推进该线程，无重复消息 |
| 9 | Redis 停止 | 实时流退化但内容可从 checkpoint / `chat_messages` 恢复 |

## 10. 实施顺序

1. 回退 P 系列到 M0 基线 `d6e3b7d`（删除 `chat/runs/`、`protocol/db_stream.py`、两个 P 迁移、`docs/resumable-agent/`、P 系列测试）。
2. `chat_messages` 读模型（表、迁移、写入 hook、`GET messages` 端点、测试）。
3. Redis 协调层：compose 加 Redis；Redis Stream 事件总线替换进程内 session（SSE 回放 + 实时）；Redis 锁替换 PG advisory lock（409 语义）；测试。
4. 排水 + 前端 resume：`RunRegistry.drain`、draining 503、`AgentStreamSession` 移除、前端仅保留"断流 resume 一次"（删静默检测）、Dockerfile/compose、测试。
5. 文档收尾（更新 `AGENTS.md`，校对本文与 `docs/messages.md`）。

每阶段一个 commit；保留 P 系列历史，不重写 git 历史。
