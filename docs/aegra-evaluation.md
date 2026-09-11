# Aegra 实测评估报告

> 状态：spike 完成，结论为"可替换当前自研协调层"。本文记录实测证据、v2/v3 协议澄清、对仓库的影响与风险。
>
> 日期：2026-09-11　分支：`p0-resumable-agent`

## 1. 结论摘要

**Aegra（Apache 2.0，约 1.2k star）可以在不改动 LangGraph 官方协议的前提下，直接接管我们当前手写的"Resumable Agent 协调层"，并且做得更完整、更稳。**

它在单进程内提供了我们 P1–P5 想实现但没实现完的东西：

| 能力 | 当前项目（自研） | Aegra（实测） |
| --- | --- | --- |
| 后台 run（请求与执行解耦） | P1 半成品 | Redis job queue + worker |
| SSE 断线续流 | db_stream 轮询过渡 | Redis 回放 + `Last-Event-ID` / `since` |
| 跨实例 SSE | 无 | Redis Pub/Sub 广播 |
| 跨实例 worker 执行 | 无 | 任意实例可执行任意 run |
| 崩溃恢复 | 启动扫描 RUNNING | lease + heartbeat + reaper |
| 滚动部署 drain 交接 | 30s 兜底 + 前端 resume | SIGTERM drain + 自动 requeue + checkpoint 续跑 |
| 工具幂等 | 需自建 tool_invocations | 仍是应用职责，Aegra 不提供 |

## 2. 版本矩阵与 v2/v3 澄清

### 实测版本

| 组件 | 版本 |
| --- | --- |
| aegra-cli / aegra-api | 0.10.4 |
| langgraph（Python） | 1.2.11 |
| langchain-core | 1.6.2 |
| langgraph-sdk（Python） | 0.4.4 |
| @langchain/react（前端） | 1.0.35 |
| @langchain/langgraph-sdk（JS，@langchain/react 内置） | 1.10.2 |

### v2 和 v3 不是同一层，不存在"选 v3"

- **v2 = 传输协议**（wire protocol）：`POST /threads/{id}/commands` + `POST /threads/{id}/stream/events`（SSE 信封 + content-block 消息模型 + `seq` 游标 + `event_id` 去重）。当前最新 SDK（JS 1.10.2 / Python 0.4.4）和 `useStream` / `HttpAgentServerAdapter` 讲的就是它。
- **v3 = LangGraph runtime 事件格式**（langgraph-core 的 native v3 events），是装进 v2 信封里的内容。Aegra 文档明确：v2 协议要求 runtime 能产生 native v3 events，否则返回 `503` 提示升级。
- 因此"用 v3"不是一个前端选项。当前栈（langgraph 1.2.11 / langchain-core 1.6.2 / langgraph-sdk JS 1.10.2）已经是 **v2 协议 + v3 事件** 的最新组合。
- Aegra 的 `FF_V2_EVENT_STREAMING` 是开关（默认开），可回滚。

## 3. 实测证据

全部在 `/tmp/aegra-spike` 独立环境完成（隔离 PG:15432 / Redis:16379，不触碰仓库与现有容器）。

### Test A：断线续流（v1，`Last-Event-ID`）

curl 两段读取 slow graph（custom + values 模式）：

- 首段收到 `metadata (event_1)` 后断开；
- 带 `Last-Event-ID: <run>_event_1` 重连，只收到 `event_3/5/7…`（后续全部事件），**无重复、无遗漏**。

### Test B1：跨实例 SSE

run 在实例 A（2026）创建，在实例 B（2027）订阅，收到完整事件流（Redis Pub/Sub 广播，SSE 连接与执行 worker 可不在同一实例）。

### Test B2：worker 分配

并发 4 个 slow run，3 个被 B 的 worker 接走、1 个被 A 接走，共享 `aegra:jobs` 队列，任意实例可执行任意 run。

### Test B3：drain 交接（滚动部署核心场景）

120s slow run，`WORKER_DRAIN_TIMEOUT=3`：

1. 仅实例 B 运行时创建 run，B 的 worker 拾起执行（`WIN-QCTB3IGT5LI-316653-worker-1`）；
2. 实例 A 启动（2026）；
3. 对 B 发 SIGINT，B 日志依次出现：
   - `Draining in-flight jobs count=1`
   - `Shutdown drain cancel, skipping finalize for requeue`
   - `Requeueing drained runs for another instance count=1 run_ids=['f64d4798-…']`
4. A 的 worker 在 requeue 后瞬间拾起（`08:26:52.696`），从 checkpoint 续跑 120.4s，`08:28:53` `status=success`；
5. SSE 断在 `event_45`（B 被杀时），带 `Last-Event-ID: …_event_45` 经 A 重连，补齐 `event_47…event_547` 共 251 个事件：**B 端 23 + 重连 251 = 274 = 全部事件，无重复无遗漏**。

### Test C：v2 协议端到端（前端同款）

用 stock `langgraph_sdk`（与前端 `HttpAgentServerAdapter` 同一条 v2 协议路径）：

```python
async with client.threads.stream(assistant_id="slow") as ts:
    await ts.run.start(input={})
    sub = ts.subscribe(["custom"])
    async for ev in sub:
        print(ev["seq"], ev["event_id"], ev["method"], ev["params"]["data"])
```

结果：`seq=4..8`、`event_id=<run>_event_N:0`、`method=custom`、data 为 `{"payload": {"progress": "a-N"}}`（v2 信封包一层 `payload`）。随后跨实例 cancel 成功（Redis Pub/Sub 通知执行 worker 终止并 finalize）。

结论：**现有前端 `HttpAgentServerAdapter` 指向 Aegra 即可工作**；自定义事件在 v2 信封里多一层 `payload`，前端解码需适配（这正是"适配器可以改"的落点）。

## 4. Aegra 提供的运行时能力（替代自研层）

| 机制 | Aegra 实现 | 说明 |
| --- | --- | --- |
| Job 队列 | Redis `BLPOP` + `aegra:jobs` | 瞬时投递，非轮询 |
| 执行租约 | PG 原子 `UPDATE … WHERE claimed_by IS NULL` + lease（默认 30s） | 只有一台 worker 赢 |
| Heartbeat | 10s 续租 | 崩溃后 30s 内可被回收 |
| Reaper | 15s 扫描过期 lease → reset pending + 重新入队 | 崩溃恢复，不消耗手动重试预算 |
| SSE 广播 | Redis Pub/Sub | 订阅端与执行端解耦 |
| SSE 回放 | Redis List 回放缓冲 + 计数器（保留 1h） | v1 `Last-Event-ID` / v2 `since` |
| Drain | SIGTERM 后等 `WORKER_DRAIN_TIMEOUT`，未完成 run reset + requeue | 滚动部署核心，不 finalize、不消费重试预算 |
| 取消 | 跨实例 cancel（DB 所有权判定 + Redis Pub/Sub） | 幂等，terminal 后 no-op |
| Redis 不可用 | 降级为 PG 轮询 pending | 可用性兜底 |
| Checkpoint | 同一 PG 上的 AsyncPostgresSaver（Aegra 初始化） | 执行状态唯一事实源不变 |

## 5. 对仓库的影响

### 可以直接删/停用的自研层

- `backend/app/chat/runs/`（agent_runs / agent_events / 租约 / tool_invocations 的 P1–P5 实现）
- `backend/app/chat/protocol/db_stream.py`（DB 回放 + 轮询过渡）
- 前端 auto-resume 状态机（`resumeActiveRun` / sessionStorage activeRun 跟踪）——Aegra 后台 run + SDK 自动重连取代

### 保留的应用职责（Aegra 不提供）

- 认证/授权（Aegra 有 auth 机制，生产需配置，不能 `AUTH_TYPE=noop`）
- 工具幂等台账（`tool_invocations` 仍是应用职责）
- 业务风险策略、审计
- 前端 v2 信封解码（custom 事件的 `payload` 包装）

### 部署形态

```text
Nginx / SLB
   │
   ├── Aegra Instance A（aegra serve，port 2026）
   └── Aegra Instance B（aegra serve，port 2026）
          │ shared
   PostgreSQL（Aegra 表 + LangGraph checkpoint）
   Redis（job queue + SSE broker + replay + lease reaper）
```

滚动发布：SLB 摘流 → 旧实例 SIGTERM → drain（`WORKER_DRAIN_TIMEOUT`，建议 30s，`terminationGracePeriodSeconds` 稍大）→ 未完成 run 自动 requeue → 新实例从 checkpoint 续跑 → 前端断线自动重连（v2 `since` / 全量回放 + `event_id` 去重）。

## 6. 风险与边界（如实记录）

1. **Aegra 是 0.x 年轻项目**（1.2k star）：API 变化快，`0.10.4` 是实测基线，升级需回归。
2. **v2 覆盖不完整**：Aegra 文档明确 WebSocket 传输、`agent.getTree` / `state.fork` / `subscription.*` 命令尚未实现；HTTP SSE + commands 路径（`useStream` 所需）已实测可用。
3. **custom 事件 v2 信封多一层 `payload`**：前端解码要适配（小改动）。
4. **工具幂等仍需应用层**：Aegra 不解决副作用幂等。
5. **认证**：spike 用 `AUTH_TYPE=noop`；生产需配置 auth 或由网关处理。
6. **消息读模型**：Aegra 的 `values` 快照可渲染完整消息，但"UI 展示与 checkpoint 分离的 `chat_messages`"仍需自行决定是否建表（与 `docs/messages.md` 的规划一致，未建表）。

## 7. 结论与下一步

Aegra 把"刷新恢复、断线补事件、多实例 worker、滚动部署 drain 交接、崩溃 lease 恢复"全部变成开箱即用，且协议与现有前端 SDK 兼容。**建议仓库按以下顺序收敛：**

1. 用 Aegra 替换 `backend/app/chat/runs/` + `db_stream.py` 自研层（保留 auth、工具幂等、业务治理）；
2. 前端 `HttpAgentServerAdapter` 指向 Aegra，适配 v2 custom 信封；
3. 迁移 `travel-planning` graph 到 Aegra 的 `aegra.json` 注册；
4. 部署形态改为多实例 `aegra serve` + Redis + PG（本地 docker-compose 即可演示）；
5. 验收 Case 1–5 用真实 LLM 重跑一遍。
