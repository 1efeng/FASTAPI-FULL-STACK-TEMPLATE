> ⚠️ 已归档（2026-09-11）：P1–P5 自研方案，早已被 Redis 协调层版取代，现再被 Aegra 版取代。保留供面试讲"自研打底"部分。

# Resumable Agent Application — 目标与实现方案

> 分支：`p0-resumable-agent`（基于 M0 基线 `d6e3b7d`）
> 状态：已确认的设计，开始实施

## 1. 项目定位

在 M0 基线上，把现有 Chat Agent 收敛为一个**支持多 worker 的 Resumable Agent Application**：
浏览器刷新能恢复、部署/崩溃后前端自动触发恢复。用 LangGraph 官方能力 + 两张业务表 + 最小租约实现，
不引入任何编排平台。

## 2. 功能目标（就两条）

### 2.1 刷新恢复（多 worker）

刷新页面 → 复用 `thread_id`（前端已有）→ `GET state` 从 LangGraph checkpoint 恢复消息（已有）→
重连 SSE 继续收事件。

多 worker 的关键：事件写入 `agent_events`（全局 seq），订阅端从 DB 回放 + 轮询，
任何 worker 都能服务任何订阅者，不依赖进程内存。

### 2.2 部署/崩溃后自动恢复

后端重启/部署、或某 worker 崩溃后：用户再次加载页面 → 前端检测到该 thread 有未完成 run →
**自动调用 resume** → 后端原子认领 + 从 checkpoint 继续执行 → 事件落库 → 前端 SSE 收到。

不需要用户点按钮，也不需要后端启动扫描或调度器。

## 3. 非目标（明确不做）

- 启动自动扫描 / 周期接管 / 后台调度器
- 工具幂等（后续阶段；本期只记录限制）
- Temporal / DBOS / AgentRun / Inngest（见 §12）
- 重写 transport、破坏 LangGraph 官方协议、引入第二套执行状态源
- worker pool / lease 框架 / fencing token 平台 / 自研 workflow engine

## 4. 硬约束

- LangGraph checkpoint 是执行状态**唯一来源**；`thread_id` 为恢复主键（`f"{user_id}:{thread_id}"`）
- 支持多 worker（Dockerfile `--workers 4` 场景正确）
- 进程内内存状态只做可选加速，正确性不依赖它
- 正确性由后端保证（原子认领 + 租约 + END 防护），前端可自由重试

## 5. 总体架构与数据流

```text
React (useStream)
  │  ① commands / ② SSE stream / ③ state / ④ resume / ⑤ cancel
  ▼
FastAPI (多 worker)
  │  astream_events(version="v3") → adapt_v3_event → INSERT agent_events
  │  graph.invoke(None) 恢复 / aget_state 状态
  ▼
LangGraph (AsyncPostgresSaver checkpoint)
  ▼
PostgreSQL
   ├─ agent_runs（应用状态：run 生命周期 + 租约）
   ├─ agent_events（SSE 落库：回放 + 跨 worker 实时）
   └─ LangGraph checkpoint 表（框架自管，不建模型）
```

### 5.1 发布路径（执行中）

```text
run.start / resume → 创建/认领 agent_runs(RUNNING)
  → astream_events → adapt_v3_event → INSERT agent_events（提交）
  → 期间每 15s renew 租约 + 检查 cancel_requested
  → 完成/失败 → agent_runs 终态 + 释放租约
```

### 5.2 订阅路径（SSE）

```text
POST /threads/{thread_id}/stream?last_event_id=N
  → 回放：SELECT agent_events WHERE thread_id=? AND seq > N ORDER BY seq
  → 实时：轮询新事件（~500ms），空闲发 keep-alive（: ping）
```

### 5.3 恢复路径（前端自动触发）

```text
页面加载（mount StreamProvider）
  → hydrate（GET state 恢复消息）+ root pump 打开订阅
  → 若 sessionStorage 有 activeRun → 直接 POST resume（resume 本身即幂等检查，无需先 GET 状态）
      → RUNNING 且租约未过期 → 幂等 no-op，返回原 run_id（前端只需重连 SSE）
      → cancel_requested=true 且无活 worker → 标 INTERRUPTED，不执行（取消不被恢复绕过）
      → WAITING_USER（本期无 interrupt，预留分支）无 value → no-op，等人工输入
      → 其余（PENDING / RUNNING 租约过期 / WAITING_USER 带 value）
          → 认领同一 run 行（原子租约与 run.start / 启动恢复竞争，恰一个 worker 推进）
          → astream_events(None 或 Command(resume=value), config) 继续执行
      → 无 active run（已完成/取消/失败）→ 404，前端清 activeRun
  → SSE 实时收事件（后端全量回放 + add-only 对账，顺序不强约束）
```

已完成的线程上 `astream_events(None)` 是安全 no-op（LangGraph 实测：next 为空
直接返回当前 state，不重跑节点），因此"run 已跑完但终态未写"的恢复会自动落
COMPLETED，无需显式 END 防护前置检查。

## 6. 数据模型

应用数据走 SQLAlchemy AsyncSession + Alembic；LangGraph checkpoint 表由框架自管。

### agent_runs

一次用户输入（一次 LangGraph run）= 一行。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | run_id，返回给前端 |
| user_id | UUID FK→user | 多用户隔离 |
| thread_id | str | 客户端 thread_id |
| command_id | int | SDK 命令去重 |
| status | str enum | PENDING / RUNNING / WAITING_USER / INTERRUPTED / COMPLETED / FAILED |
| lease_owner | str? | 当前执行 worker 实例 id |
| lease_expires_at | timestamptz? | 租约过期时间 |
| lease_version | int | 认领时 +1；renew 校验所有权 |
| cancel_requested | bool | 停止按钮标志 |
| created_at / updated_at | timestamptz | |

约束/索引：

- `UNIQUE(user_id, thread_id, command_id)` — 命令去重落库
- `INDEX(user_id, thread_id)`、`INDEX(status, lease_expires_at)`（备用查询）

### agent_events

SSE 落库，回放 + 跨 worker 实时通道。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | |
| user_id | UUID FK→user | |
| thread_id | str | |
| run_id | UUID FK→agent_runs | start / resume 两条路径都必须先建行或认领行再写事件；FK 不允许悬空 |
| seq | bigint | 全局递增序列；SSE 的 `id:` 字段 |
| event_type | str | 事件类型（过滤用） |
| payload | JSONB | **适配后**的 wire 事件（`adapt_v3_event` 输出，保留协议自带 `seq`），回放无需再适配 |
| created_at | timestamptz | |

约束/索引：

- `UNIQUE(thread_id, seq)`；seq 用 PostgreSQL 全局 sequence（避免 `MAX(seq)+1` 并发竞争）
- `INDEX(user_id, thread_id, seq)` — 回放查询

### tool_invocations（后续阶段，本期不建）

保留设计：`(thread_id, idempotency_key)` 唯一，key 用 LangGraph `tool_call_id`，用于工具结果幂等 + 对账。

## 7. 关键机制

### 7.1 最小租约（resume 防双跑）

- 认领（原子）：`UPDATE agent_runs SET status='RUNNING', lease_owner=?, lease_expires_at=now()+60s,
  lease_version=lease_version+1 WHERE id=? AND (status IN ('PENDING','INTERRUPTED')
  OR (status='RUNNING' AND lease_expires_at < now())) RETURNING id`
  实际实现：`status IN ('PENDING','RUNNING','WAITING_USER','INTERRUPTED') AND
  (lease_owner IS NULL OR lease_expires_at < now())`
- 续约：`UPDATE ... SET lease_expires_at=now()+60s WHERE id=? AND lease_owner=? AND lease_version=?
  AND status='RUNNING' RETURNING id`；返回 0 行 = 已失去租约，停止执行
- 释放：终态时清空租约
- 常量：租约 60s、续约 15s；**renew 必须是与 astream 并行的独立 asyncio 任务**。
  租约只用于检测 worker 死亡：并行续约下，即使单次模型/工具调用超过 60s 也不会丢失租约，
  "租约 > 最长工具执行时间"是错误约束（只有 renew 与执行串行时才成立）。

### 7.2 END 防护

LangGraph 对已完成线程（`next` 为空）的 `astream_events(None)` 是安全 no-op：
实测只返回当前 state、不重跑节点。因此恢复路径不需要显式前置检查——"run 已跑完
但终态未写"时，恢复 invoke 直接返回，`execute_run` 随后落 COMPLETED，不会重复执行。

### 7.3 停止（cancel）

`POST cancel` → `UPDATE agent_runs SET cancel_requested=true` → 执行中 worker 在续约循环里发现 → 停任务、
标 INTERRUPTED（checkpoint 保留，可再恢复）。修复了原 `run_registry` 在多 worker 下 404 的回归。
若执行 worker 已死（标志无人消费），run 会停在 RUNNING(过期)；**resume 认领时必须先检查
cancel_requested=true → 直接标 INTERRUPTED，不恢复执行**，否则取消会被恢复动作绕过。

### 7.4 同 thread 并发 start 防护

租约只保护"同一 run 行的认领"。两个 tab 各提交新命令（不同 command_id）会建两行 RUNNING，
对着同一 checkpoint thread 双写。`run.start` 时若该 thread 已有活跃 run（RUNNING 或未过期租约）
→ 返回 409；这是线程级互斥，不是 run 行认领。

## 8. 前端设计

### 8.1 现状（M0）

- `ChatPage.tsx`：threadId 存 sessionStorage；`StreamProvider` + `HttpAgentServerAdapter`（自定义 paths）；`onCreated`/`onCompleted` 维护 activeRun
- 刷新已能复用 threadId，hydrate（`GET state`）恢复消息
- 缺口：无自动恢复、无连接状态提示、SDK 重连不带 `since`

### 8.2 SDK 关键事实（v1.10.2 源码核对）

- 自定义 adapter 下，重连由 transport 内部处理：指数退避、默认上限次；重连成功**不携带 `since`**（仅首次打开未 ready 时可能带）
- SDK 丢弃 SSE 的 `id:` 字段，只消费 `event.data`；协议 payload 自带 `seq`
- 控制器对消息做 **add-only 对账**（按消息 id 去重），重连全量回放安全
- 自定义 adapter 下 `onReconnect` 不被注入 → 想显示"重连中"只能自包装；本期不做（§8.3）

### 8.3 最小改动（不做包装器/状态机）

改动集中在 `ChatPage.tsx`：

1. **自动恢复**：加载时若 sessionStorage 有 `activeRun` → 直接 `POST resume`
   （后端幂等：live 租约 no-op / stalled 原子认领 / 终态 404；resume 本身就是"检查"）
2. **重试**：复用现有错误横幅，文案改为"连接中断，点击重试" → 点击后重新 mount
   `StreamProvider`（key=epoch）→ 重新 hydrate + subscribe + auto-resume

不引入：`ResumableTransport` 包装器、三态连接状态机、`ConnectionBanner`、独立 `runClient.ts`。
理由：SDK 自带约 17s 指数退避重连 + 现有错误横幅已覆盖"不可用"；区分"思考中/重连中"是纯 UI
打磨，不满足任何验收项；包装 SDK 内部是维护隐患，违反"不加自研层"原则。

### 8.4 行为预期（诚实）

- 部署窗口 ≤ ~17s（SDK 退避预算）：页面保持"正在思考…"，SDK 重连成功后从 DB 回放补齐，自动恢复
- 部署窗口 > ~17s：错误横幅"连接中断，点击重试" → 重试（re-mount）→ auto-resume + 订阅
- 手动刷新是最强的重试：任何时候刷新都重走 hydrate + auto-resume

代价：部署那十几秒内 UI 显示"思考中"而非"正在重连"。纯视觉取舍，可接受。

范围声明：threadId / activeRun 存 sessionStorage（per-tab）。跨 tab、新开会话或换设备的恢复
需要 run 列表查询或持久化 threadId，本期不做；本期只承诺"同 tab 刷新 / 重试"。

### 8.5 补事件语义（验收 3）

依赖 SDK 内置：断线重连 → transport 重新 POST 订阅 → 后端从 DB 回放（无 cursor 全量）→ add-only 对账。
`agent_events` 的价值 = 跨 worker 实时 + 重启不丢事件；客户端显式 `last_event_id` 仅为带宽优化，本期不做。

### 8.6 停止按钮

沿用现有交互：调 cancel 路由（P3 改为写 `cancel_requested`）+ 断开 stream。

## 9. 实施阶段与提交

每阶段一个 commit，提交说明含：修改文件、为什么修改、验证结果。每步测试通过后再进下一步。

| 阶段 | 内容 | 验证 |
| --- | --- | --- |
| P0 | 本开发文档 | 设计评审 |
| P1 | 两张表 + 迁移 + models + run_store + 单测 | pytest 通过（含 tests/conftest 对 agent_runs/agent_events 的级联清理） |
| P2 | SSE 落库 + 回放 + 轮询（替换 AgentStreamSession） | 协议测试 + 集成测试 |
| P3 | run 生命周期（start 建行、租约、renew、cancel、终态）+ resume 路由 + 启动恢复 | pytest + 恢复测试 |
| P4 | tool_invocations 幂等 + resume 语义（同一 run 行认领）+ 前端自动恢复/错误重试 | pytest 54 passed + biome/tsc/vite build |
| P5 | 验收测试矩阵 + 文档收尾 | 全部验收场景 |

## 10. 验收场景

验收矩阵（手测场景 + 自动化覆盖）：

| # | 场景 | 操作 | 预期 | 自动化覆盖 |
| --- | --- | --- | --- | --- |
| 1 | 普通执行 | 提交问题，等完成 | run → COMPLETED，消息完整 | test_api.py（FakeAgent 全链路） |
| 2 | 执行中刷新 | 提交后立即刷新页面 | 同 thread 恢复展示，run 继续，事件补齐 | 手测（SDK hydrate + DB 回放） |
| 3 | SSE 断线重连 | 断开网络/杀 SSE，等 SDK 重连 | SDK 指数退避重连，DB 全量回放 + add-only 对账，无事件丢失 | test_api.py stream 回放测试 |
| 4 | 后端重启恢复 | 执行中 kill backend → restart → 前端重试/刷新 | 启动恢复认领 stalled run；resume 幂等不双跑；从 checkpoint 继续到 COMPLETED | test_lease.py（恢复扫描/认领）+ test_api.py（stalled resume） |
| 5 | tool 重复执行保护 | 工具成功后退进程，恢复同一 run | tool_invocations 命中缓存结果，不重复副作用 | test_tool_idempotency.py |
| 6 | 停止按钮 | 执行中点击停止 | cancel_requested → INTERRUPTED，线程可开新 run | test_api.py cancel 测试 |
| 7 | 已完成但状态未写 | 构造 run 已完成、终态未写，恢复 | astream_events(None) 安全 no-op → 自动落 COMPLETED | 实测验证（§7.2） |
| 8 | 多 worker 并发 | 双 tab / 双进程同时 resume 同一 run | 原子认领恰一个生效，另一个 no-op | test_lease.py（认领互斥/续约/END 防护） |

## 11. 稳定性与已知限制

- 假死 + 租约过期：双跑窗口存在但极小（LangGraph checkpoint 不接受 fencing token，框架边界）
- 工具执行成功但进程在结果落库前死亡：恢复重跑被 tool_invocations 缓存拦截（P4）；失败记录不缓存，允许重试
- 崩溃点在模型调用超步内：恢复会重烧一次 token
- SSE 轮询延迟约 0.5s
- 单个 SSE 连接随 worker 死亡必然断一次，靠前端重连 + DB 补事件（无跨进程长连接）

## 12. 平台评估（均暂不采用）

决策规则：从零项目 + 目标即生产级 durable agent + 接受重写通信层，三者同时满足才值得引入。
本项目三条都不满足。

| 候选 | 结论 | 原因 |
| --- | --- | --- |
| Temporal | 不采用 | 需跑 server；与 LangGraph 抢执行状态；面试叙事从"自己写恢复"变"接平台" |
| Temporal LangGraph 插件 | 不采用 | 针对绿场最优；会重写 useStream 通信层；浏览器事件通道（agent_events）仍要自己建 |
| DBOS | 不采用 | 集成是 Pydantic AI 专属；我们是 LangGraph；两套执行状态源 |
| AgentRun | 不采用 | 托管平台层，不提供恢复/幂等语义；只省弹性/网关/沙箱，非本项目目标 |
| Inngest | 不采用 | 同类 durable execution；无 LangGraph 图运行插件；浏览器那一半仍要自己写 |

## 13. 与 Agent101 第 3 章的关系

| 课程概念 | 本项目处理 |
| --- | --- |
| `agent_tasks` / `task_events` | 采纳（`agent_runs` / `agent_events` 同构） |
| 租约 + 恢复认领 | 采纳（原子认领） |
| 取消 / 恢复入口 | 采纳（cancel_requested + 前端自动 resume） |
| 全局 seq（不靠 MAX+1） | 采纳（PostgreSQL sequence） |
| fencing token | 不采纳（LangGraph checkpoint 不接受，框架边界） |
| `tool_invocations` 幂等 | 采纳（P4：按 tool_call_id 缓存成功结果，恢复命中直接返回） |
| 状态机 version / 预算 / 重规划 / Sandbox | 不采纳（Codebase Agent 量级，聊天 demo 不需要） |

课程铁律"没有证据副作用未发生就不能自动重发"——P4 起以 tool_invocations 为准：
只有证据不足（FAILED/未知）的工具调用才允许重试，成功结果一律缓存。
