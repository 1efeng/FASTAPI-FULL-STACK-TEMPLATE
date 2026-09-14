# 面试记录：Resumable Agent 的无感部署与 FastAPI 生产部署

> 记录日期：2026-09-14
>
> 适用项目：`travel-agent`，Aegra 自托管 Runtime + LangGraph + FastAPI + assistant-ui

这份记录整理了几个相关面试问题：SSE 断开后 Agent 是否继续、浏览器刷新后如何恢复、多实例滚动发布如何不影响老任务，以及 FastAPI 的生产部署方式。

## 一、先把问题拆开

“用户无感部署新功能”不是一个单独问题，至少包含三种恢复：

1. **连接恢复**：SSE 连接断开后，浏览器能重新订阅并补齐漏掉的事件。
2. **执行恢复**：浏览器断开、API 进程重启甚至 Worker 崩溃后，Agent 任务仍能继续或被其他 Worker 接管。
3. **版本恢复**：上线新 graph、prompt、工具或 state 后，正在执行的老任务仍然能安全完成。

轮询或 SSE 重连只能解决第一种。它们不能让已经退出的进程继续执行 Agent，也不能自动解决新旧 graph 的兼容性。

## 二、本项目的最终选择：Aegra 承担 Runtime，应用补治理

项目最终采用 Aegra，而不是继续维护一套应用层 Durable Runtime。原因是多实例 Agent 需要同时处理任务队列、独占租约、心跳、失联回收、优雅排水、事件广播和断线回放。单独实现其中一个功能并不难，难的是这些功能之间的故障语义要一致。

```text
Browser
  └─ assistant-ui + @langchain/react useStream
       └─ Agent Protocol v2
            └─ Nginx / SLB
                 ├─ Aegra instance A
                 └─ Aegra instance B
                      ├─ LangGraph graph
                      ├─ PostgreSQL：Aegra 表 + LangGraph checkpoint
                      └─ Redis：job queue + SSE 广播/回放 + cancel
```

职责边界如下：

| 模块 | 负责内容 |
| --- | --- |
| LangGraph checkpoint | thread 的消息、状态、interrupt 和执行边界；是执行状态的唯一事实源 |
| Aegra | 后台 run、Worker、PG lease、heartbeat、reaper、drain、requeue、跨实例 cancel、SSE 广播与有限回放 |
| Redis | 队列和事件传输；不是权威状态，丢失事件后仍从 checkpoint 或事件回放恢复 |
| 应用层 | JWT/owner 校验、业务风险策略、工具副作用幂等、审计和版本兼容策略 |
| assistant-ui / `useStream` | Chat UI、SSE 订阅、断线重连和状态展示，不维护第二套 messages store |

## 三、Aegra 的关键运行原理

一次用户请求的执行路径是：

1. 前端提交 `run.start`，Aegra 将 run 写入 PostgreSQL，并把任务放入 Redis 队列。
2. 任意实例的 Worker 从队列取任务，通过 PostgreSQL 原子更新竞争 lease；只有一个 Worker 获得执行权。
3. Worker 执行 LangGraph。每个 graph super-step 会把 checkpoint 写入 PostgreSQL，并发布展示事件。
4. Worker 用 heartbeat 续租。租约过期后，reaper 将任务重新置为 pending 并入队，其他 Worker 从 checkpoint 继续。
5. Worker 正常完成时原子 finalize；取消、完成和失败都必须是幂等的终态更新。

SSE 只是观察通道。用户关闭页面不会取消后台 run；重新打开页面时，前端使用同一个 `thread_id`：

```text
GET state → hydrate checkpoint 中的 values/messages
POST stream/events(since=最后收到的 seq)
→ 回放缺失事件 → 继续接收实时事件 → event_id 去重
```

因此，刷新不重新发送用户消息，也不依赖原来的 API 实例。LangGraph 的生产 checkpointer 使用 PostgreSQL；官方文档将 checkpointer 用于 thread 级状态、会话连续性和故障恢复：[LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。

滚动发布时：

```text
SLB 摘除旧实例
  → SIGTERM
  → 旧 Worker drain（等待有限时间）
  → 未完成 run 不 finalize，清 lease 并 requeue
  → 新实例领取任务
  → 从 checkpoint 续跑
  → 前端重连并补事件
```

这里的关键是“drain 时 requeue，不把任务标记为成功或失败”。这样发布造成的进程退出不会消耗业务重试次数，也不会要求用户再次提交问题。

## 四、新功能上线时如何保护老任务

Aegra 提供任务恢复机制，但**不会自动解决 graph 版本兼容**。上线新功能前要选择一种策略。

### 策略 A：兼容迁移（默认推荐）

新版本保留旧 state key 和工具契约，新增字段提供默认值；旧 checkpoint 可以被新 graph 读取。发布后，旧任务在新实例接管时从 checkpoint 继续。

LangGraph 官方支持对 graph topology 和 state 做迁移，但中断中的线程不能随意重命名或删除节点，state key 的重命名也需要显式迁移：[Graph migrations](https://docs.langchain.com/oss/python/langgraph/graph-api#graph-migrations)。

### 策略 B：版本隔离（需要旧语义保持不变时）

给 run 保存不可变的 `execution_version`，让 v1 Worker 只领取 v1 任务，v2 Worker 只领取 v2 任务：

```text
发布前创建的 run → v1 graph / prompt / skill / tool
发布后创建的 run → v2 graph / prompt / skill / tool
```

发布期间保留 v1 Worker，直到 v1 的 pending/running 任务清空，再停止 v1。若还要求旧版本在固定时间内退出，则必须先证明 v2 能读取 v1 checkpoint，或者为旧任务保留独立的兼容 Worker。

不能只更新一个共享的 prompt 或 skill 文件，却声称老任务仍运行在旧版本；版本绑定必须落实到镜像、代码包或不可变配置。

## 五、不使用 Aegra 时的可行设计

技术上可以不用 Aegra，但需要自行维护以下模块：

```text
FastAPI API（无状态）
  ├─ agent_runs：任务状态、租约、版本
  ├─ agent_events：有序事件和回放
  ├─ PostgreSQL：业务表 + LangGraph checkpoint
  └─ 独立 Agent Worker：领取、心跳、回收、排水、重试
```

Worker 可以使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 领取 pending 任务；事件先落库再通过 SSE 发送，客户端带 `thread_id + event cursor` 重连。Redis 可以作为队列和 Pub/Sub，但 PostgreSQL/checkpoint 仍应是恢复依据。

这个方案能实现需求，但必须额外解决：租约失效后的旧 Worker 写入隔离、崩溃后重跑的工具幂等、快照与事件游标的一致性、版本路由和协议兼容。只把消息放进 Redis、让前端轮询 `pull_msgs`，只能恢复显示，不能保证 Agent 任务有人继续执行。

因此本项目选择 Aegra 的面试重点不是“用了一个框架”，而是：已经识别过自研层的边界，并把成熟的通用 Runtime 交给 Aegra，只保留应用必须负责的治理。

## 六、FastAPI 生产部署补充

FastAPI 是 ASGI 应用，常见部署组合包括：

- Uvicorn 单独运行并使用 `--workers`；
- Gunicorn 管理进程，使用 Uvicorn Worker 处理 ASGI；
- Hypercorn（支持 HTTP/2、asyncio 和 Trio）；
- Daphne；
- Granian。

Uvicorn 的 `uvicorn.workers` 模块已经弃用，新项目可使用独立的 `uvicorn-worker` 包：

```bash
gunicorn app.main:app \
  --worker-class uvicorn_worker.UvicornWorker \
  --workers 2 \
  --bind 0.0.0.0:8000
```

Gunicorn 的 `(2 × CPU 核心数) + 1` 只是起始经验值，不是 Agent 服务的固定公式。异步 Worker 在等待 LLM 或网络 I/O 时可以并发处理其他请求；增加进程会增加内存、数据库连接和模型客户端数量。应根据 P95 延迟、CPU、内存、数据库连接数、LLM 限流和实际并发压测调整。

异步代码使用 `async def` + `await`，例如异步 HTTP 客户端和 SQLAlchemy AsyncSession。同步路由可以直接使用普通 `def`，FastAPI 会将其放入线程池。若必须在 `async def` 中调用同步阻塞 SDK，应显式转移到线程：

```python
import asyncio

result = await asyncio.to_thread(blocking_sdk.fetch)
```

`run_in_executor` 也可以使用，但正确写法是 `loop.run_in_executor(...)`，不是 `asyncio.run_in_executor(...)`。大量 CPU 密集型计算则应考虑进程池或独立计算服务。FastAPI 官方说明允许混用 `def` 和 `async def`，并要求避免在异步函数中直接运行阻塞代码：[Concurrency and async/await](https://fastapi.tiangolo.com/async/)。

本项目中，FastAPI 普通 API 与 Aegra Agent Runtime 是两个部署单元。调高 FastAPI Web Worker 数量不会直接提高 Agent graph 的执行并发；Agent 并发由 Aegra Worker 配置、LLM 配额、工具预算和数据库容量共同决定。

## 七、生产级封装、观测与成本控制

如果面试题从“怎么运行”继续追问到“怎么长期运营”，可以按下面几个方面回答。

### FastAPI 接口与流式响应

请求体用 Pydantic 做类型、长度和枚举校验，认证后再检查 thread 的 owner。长时间运行的 Agent 应先创建后台 run 并返回 `thread_id/run_id`，不能把整个 Agent 生命周期绑定在 HTTP 请求或 SSE 生成器上。

如果由 FastAPI 直接提供 SSE，应使用异步生成器，并发送正确的 `text/event-stream` 响应；反向代理要关闭响应缓冲，并设置合理的读取超时。当前项目的 Agent SSE 由 Aegra Agent Protocol v2 提供，FastAPI 主要承担普通 API 和认证桥接，因此不要在 FastAPI 里再实现一套平行的 SSE 协议。

健康检查应分为两类：

- **liveness**：进程事件循环仍能响应，失败时重启实例；
- **readiness**：实例已完成启动并能访问所需的 PostgreSQL/Redis，失败时从负载均衡摘除。

readiness 失败不应删除正在执行的 checkpoint 或 run。收到 SIGTERM 后先停止接收新请求，再按 `WORKER_DRAIN_TIMEOUT` 排水；Agent Worker 的 drain 和 requeue 由 Aegra 负责。

### 可观测性

日志、指标和追踪要围绕一次 Agent run 关联，而不是只记录 HTTP 请求：

| 类型 | 建议字段或指标 |
| --- | --- |
| 结构化日志 | `trace_id`、`thread_id`、`run_id`、`model`、`tool`、`provider`、`status`、`error_code`、耗时；不记录完整 prompt、token 内容或敏感信息 |
| Agent 指标 | run 成功率、失败率、恢复次数、排队时间、执行时长、SSE 重连数、事件回放量、租约过期数 |
| LLM 指标 | 输入/输出 token、延迟、限流次数、重试次数、估算费用、fallback 次数 |
| 基础设施指标 | CPU、内存、事件循环延迟、数据库连接池、Redis 队列长度、Worker 并发和 checkpoint 写入延迟 |

项目当前已有 `model_call`、`tool_call` 和 `state_migrated` 级别的结构化日志；Prometheus、分布式 tracing 和告警规则属于部署环境需要补齐的运维能力，不能把“打了几行日志”说成完整可观测性。

### 成本控制

成本控制不是简单地把所有请求换成小模型，而是按任务阶段和风险做路由：

1. 意图分类、字段提取、结果去重等低风险步骤使用小模型或程序逻辑。
2. 复杂规划、冲突修复和最终回答使用更强模型。
3. 为每个 run 设置模型调用次数、token、工具搜索次数和最长执行时间上限。
4. 复用 checkpoint、工具结果和确定性搜索结果；缓存必须带 provider、参数和版本，避免旧数据污染新功能。
5. 对 LLM 和外部工具设置超时、指数退避和有限重试，区分可重试错误与业务错误。
6. 记录每次调用的 token、延迟和费用，按用户、thread、模型和功能统计预算。

在本项目里，旅行搜索预算和工具幂等已经属于应用治理；模型路由、精确费用计量和跨用户成本报表仍应在实际成本压力出现后加入，避免为了“看起来生产化”提前引入复杂网关。

### 安全与发布流水线

生产部署还应包括：

- JWT/owner 隔离、接口限流、请求体大小限制和密钥由 Secret 管理；
- 工具按读/写/高风险分类，外部链接解析要防 SSRF，工具参数不能直接信任模型输出；
- 日志脱敏，禁止把完整用户 prompt、Authorization header 或第三方密钥写入日志；
- CI 中运行类型检查、单元测试、graph/checkpoint 兼容性测试、镜像扫描和迁移检查；
- 数据库迁移使用 expand → 兼容运行 → contract，先保证旧 Worker 能读取新 schema；
- 新镜像使用不可变 tag 或 digest，先健康检查和冒烟，再灰度/蓝绿切流；发现错误时回切流量，同时保留能读取当前 checkpoint 的兼容代码。

这些措施共同保证“新功能部署不影响老任务”：流量切换只决定新请求去哪里，checkpoint/lease/drain 决定在途任务如何继续，版本兼容决定新旧代码能否安全接管。

## 八、面试中的完整回答

可以这样回答：

> 我们把无感发布拆成连接恢复、执行恢复和版本兼容。SSE 只是观察通道，浏览器断开不会取消后台 Agent run；状态保存在 LangGraph PostgreSQL checkpoint，事件按 seq/event_id 回放，刷新后使用同一个 thread_id hydrate 状态并从游标继续订阅。多实例中由 Aegra Worker 通过 PostgreSQL lease 互斥执行，heartbeat 维持租约，reaper 回收失联任务；滚动发布先摘流并 drain，超时任务不 finalize，而是 requeue 后由新实例从 checkpoint 续跑。新功能发布要保证 state/graph 兼容，或者按不可变 execution_version 保留旧 Worker 处理老任务。工具副作用由应用幂等台账保护，因为 Runtime 不会自动提供业务幂等。

如果面试官追问“为什么不用自己写”，可以补充：

> 我们确实可以用 `agent_runs + agent_events + Redis + PostgreSQL` 自研，但还要正确处理 lease、heartbeat、reaper、drain、跨实例回放、旧 Worker 写入隔离和工具不确定结果。项目把这部分通用 Runtime 交给 Aegra，应用只实现认证、业务治理、版本兼容和副作用幂等，并用故障注入验证刷新、断线重连、drain 和接管行为。

## 九、必须主动说明的边界

- 事件回放不等于执行恢复；Redis 中有消息不代表 Worker 还活着。
- checkpoint 恢复通常从最近的持久化执行边界继续，未完成的 LLM/tool 调用可能重跑，不是从中断的 token 原地继续。
- 租约和心跳不等于外部副作用天然 exactly-once，仍需要 `tool_invocations` 幂等台账和必要的对账。
- Aegra 不替应用解决 state、tool schema、prompt、skill 和数据库迁移的兼容性。
- “无感”通常允许短暂的输出停顿和自动重连，验收重点是任务不丢、内容不重复、事件可补齐，而不是逐 token 完全连续。

项目的正式架构、部署参数和已完成/待完成验收以 [architecture.md](architecture.md)、[aegra-evaluation.md](aegra-evaluation.md) 和 [implementation-status.md](implementation-status.md) 为准。
