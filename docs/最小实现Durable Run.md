# Durable Agent Run 的最小实现：为什么刷新页面以后 Agent 还能继续执行

## 摘要

在很多 Agent 产品中，前端通常通过 SSE 接收模型输出、工具调用、执行步骤和最终结果。

这种方式实现简单，但如果直接在 SSE 请求协程中执行 Agent，就会产生一个很隐蔽的问题：

> 浏览器连接的生命周期，意外变成了 Agent 执行的生命周期。

用户刷新页面、网络短暂断开或者关闭浏览器时，SSE 连接会结束。如果 Agent 恰好运行在这个 SSE Request Task 中，那么请求取消可能继续向下传播，最终导致正在执行的 Agent 一起被取消。

对于普通聊天，这种行为可能还能接受；但对于需要几十秒甚至几分钟的 Research Agent、Travel Agent、Coding Agent 来说，它会直接破坏产品体验。

我们的解决方案并没有引入复杂的 MQ、Celery、Temporal、DBOS 或分布式 Worker，而是先解决最核心的问题：

> **将 Agent Execution Task 与 SSE Subscription Task 分离。**

最终形成：

```text
Agent Task → Event Hub → SSE Task → Browser
```

用户刷新页面时：

```text
SSE Task      ❌ 结束
Subscriber    ❌ 删除

Agent Task    ✅ 继续
RequestRun    ✅ 保留
```

页面重新加载以后，再通过持久化的 `run_id` 找回正在执行的任务，并建立新的 SSE 连接。

这是一种非常轻量，但非常有效的 Durable Agent Run 实现。

---

# 一、问题到底出在哪里

最常见的 Agent Streaming 实现类似这样：

```python
@app.get("/chat/stream")
async def stream():
    async for event in agent.astream(...):
        yield event
```

从代码上看很自然：

```text
Browser
   │
   │ SSE
   ▼
HTTP Handler
   │
   ▼
agent.astream()
   │
   ├── LLM
   ├── Search
   └── Tools
```

但这里存在一个关键问题：

```text
SSE Request Task
      │
      └── Agent Execution
```

Agent 并不是独立运行的。

它实际上属于当前 HTTP Streaming Request 的执行链。

于是用户按下 F5 时，可能发生：

```text
Browser Refresh
      ↓
旧 SSE Connection 断开
      ↓
Streaming Request 结束
      ↓
Request Task 被取消
      ↓
CancelledError 向下传播
      ↓
agent.astream() 被中断
      ↓
Agent 停止
```

真正的问题并不是 SSE。

而是：

> **我们把 Execution Lifetime 和 Transport Lifetime 绑定在了一起。**

---

# 二、重新定义 Agent 的生命周期

要解决这个问题，首先需要明确系统中实际上存在三个完全不同的生命周期。

### Browser Lifetime

浏览器可能随时：

```text
F5
关闭页面
网络切换
电脑休眠
移动端切后台
```

这是最不可靠的一层。

---

### SSE Lifetime

SSE 本质上是一条实时数据传输连接。

它负责：

```text
token delta
tool event
progress
status
final event
```

但它不应该决定 Agent 是否存在。

因此：

```text
SSE = Transport
```

而不是：

```text
SSE = Execution
```

---

### Agent Lifetime

Agent 才是真正需要稳定存在的任务：

```text
规划
搜索
调用工具
调用模型
整理结果
生成最终回答
```

所以正确关系应该是：

```text
Browser Lifetime
        ≠
SSE Lifetime
        ≠
Agent Lifetime
```

在我们当前实现中：

```text
Agent Lifetime
=
Python Process Lifetime
```

也就是说：

```text
浏览器刷新         ✅ Agent继续
关闭浏览器         ✅ Agent继续
SSE断开            ✅ Agent继续
网络断开           ✅ Agent继续

Python进程Crash     ❌ 当前Run终止
服务器重启          ❌ 当前Run终止
机器掉电            ❌ 当前Run终止
```

这是一个非常明确的可靠性边界。

---

# 三、核心实现：把 Agent 放进独立 Task

Python `asyncio` 提供了一个非常适合这个场景的基础能力：

```python
asyncio.create_task()
```

它不是 MQ。

它也不是持久化任务系统。

它只是：

> 把一个 coroutine 调度成当前 Python Event Loop 中独立运行的 Task。

例如：

```python
task = asyncio.create_task(
    execute_agent(run_id)
)
```

此时结构从原来的：

```text
SSE Task
   └── Agent
```

变成：

```text
Python Process

├── Agent Task
│      └── Deep Agent
│
└── SSE Task
       └── Subscriber
```

这是整个方案最关键的一步。

---

# 四、为什么 create_task 可以解决 F5

创建 Agent Run 时：

```python
active_runs: dict[str, asyncio.Task] = {}
```

然后：

```python
async def start_run(run_id: str):
    if run_id in active_runs:
        return

    task = asyncio.create_task(
        execute_agent(run_id),
        name=f"agent:{run_id}",
    )

    active_runs[run_id] = task

    task.add_done_callback(
        lambda _: active_runs.pop(run_id, None)
    )
```

HTTP API 只负责启动任务：

```text
POST /api/runs
      │
      ▼
create RequestRun
      │
      ▼
asyncio.create_task()
      │
      ├────────────→ Agent继续执行
      │
      ▼
立即返回 run_id
```

例如：

```json
{
  "run_id": "run_123",
  "status": "running"
}
```

这里最重要的变化是：

> HTTP 请求已经完成，但 Agent 仍然存在。

因此之后浏览器刷新：

```text
Browser
   X

Agent Task
   │
   └────────────────继续
```

F5 根本不会触碰这个 Task。

---

# 五、为什么还需要一个 Run

如果只是 `create_task()`，任务虽然能继续跑，但刷新以后前端不知道：

```text
刚才运行的是哪个任务？
任务还活着吗？
执行到哪一步了？
已经结束了吗？
失败了吗？
最终消息是什么？
```

因此必须引入一个稳定的顶层对象：

```text
RequestRun
```

或者对外直接叫：

```text
AgentRun
```

它代表：

> 一次用户发起的 Agent 执行。

最小字段可以设计为：

```text
request_runs

id
conversation_id

status
stage
progress_message

input
result

error_message

started_at
completed_at
cancelled_at

created_at
updated_at
```

生命周期：

```text
pending
   ↓
running
   ↓
┌────────────┬────────────┐
▼            ▼            ▼
completed   failed     cancelled
```

这样即使 SSE 完全不存在：

```text
RequestRun
```

依然能够告诉系统：

```text
run_123 还在执行
```

---

# 六、SSE 不再执行 Agent

这是第二个核心变化。

以前：

```text
SSE
 ↓
Agent
```

现在：

```text
Agent
 ↓
Event Hub
 ↓
SSE
```

也就是说，SSE 变成一个纯消费者。

Agent 产生：

```text
status
message_delta
tool_start
tool_result
progress
final
```

Event Hub 负责转发。

---

# 七、最简单的 Event Hub

在单 Python Process 阶段，我们甚至不需要 Redis。

可以直接使用：

```python
subscribers: dict[
    str,
    set[asyncio.Queue]
] = {}
```

每个 SSE Connection 创建自己的 Queue：

```python
async def subscribe(run_id: str):
    queue = asyncio.Queue()

    subscribers.setdefault(
        run_id,
        set(),
    ).add(queue)

    try:
        while True:
            event = await queue.get()
            yield event
    finally:
        subscribers[run_id].discard(queue)
```

Agent 发布事件：

```python
async def publish(run_id: str, event: dict):
    for queue in subscribers.get(run_id, set()):
        queue.put_nowait(event)
```

于是整体关系变成：

```text
                   ┌── Queue A → Browser A
                   │
Agent → Event Hub ─┼── Queue B → Browser B
                   │
                   └── Queue C → Browser C
```

---

# 八、F5 到底杀掉了什么

假设 Browser A 按下 F5：

```text
Browser A
    X

SSE Task A
    X

Queue A
    X
```

Event Hub 删除 Queue A。

但：

```text
Agent Task          ✅
Queue B             ✅
Queue C             ✅
RequestRun          ✅
```

全部继续存在。

所以准确来说：

> SSE 断开以后确实会“结束一个东西”。

结束的是：

```text
这个浏览器连接对应的 SSE Subscription Task
```

而不是：

```text
Agent Task
```

---

# 九、没有 Subscriber 时 Agent 怎么办

这是实现中一个非常重要的细节。

假设用户关闭页面以后：

```text
subscribers["run_123"] = []
```

Agent 又生成一个事件：

```python
await publish(
    "run_123",
    {
        "type": "status",
        "stage": "researching"
    }
)
```

这时候：

```python
for queue in []:
    ...
```

什么都不会发生。

然后 Agent 继续：

```text
LLM
↓
Search
↓
Tool
↓
Reasoning
↓
Final
```

这也是为什么 Event Hub 必须设计成：

> **best effort live delivery**

而不能成为 Agent 的执行依赖。

特别要避免这种设计：

```text
Agent
 ↓
await queue.put()
 ↓
Queue没人消费
 ↓
Queue满
 ↓
Agent被卡住
```

实时事件应该可以丢。

关键状态不能丢。

---

# 十、Snapshot 才是真相，Stream 只是实时体验

我们的系统因此形成了一个非常重要的原则：

> **Snapshot is Truth, Stream is Projection.**

实时 Token：

```text
message_delta
```

可以错过。

某些临时步骤：

```text
tool_start
progress update
```

也可以错过。

但这些必须持久化：

```text
Run status
当前重要阶段
最终 Assistant Message
错误信息
Token Usage
开始结束时间
```

因此用户刷新以后，不需要 replay 原来的所有 Token。

只需要：

```text
GET /runs/run_123
```

例如得到：

```json
{
  "id": "run_123",
  "status": "running",
  "stage": "researching",
  "progress_message": "正在整理北京景点资料"
}
```

然后重新建立：

```text
GET /runs/run_123/stream
```

即可。

---

# 十一、刷新以后不是“恢复 Agent”

这一点尤其重要。

很多人在设计 F5 恢复时，会自然想到：

```text
checkpoint
resume
workflow recovery
```

但对于我们这个场景，这些实际上都不是必须的。

因为 Agent 根本没有停止。

刷新以后发生的是：

```text
恢复观察
```

而不是：

```text
恢复执行
```

完整过程：

```text
T0

POST /runs
   ↓
run_123
   ↓
Agent Task running
```

用户看到：

```text
正在规划...
```

---

随后 F5：

```text
T1

Browser SSE
     X

Agent Task
     │
     └──继续搜索
```

---

页面重新加载：

```text
T2

GET /runs/run_123
     ↓
status = running
stage = researching
```

然后：

```text
重新连接 SSE
```

整个过程中：

```text
Agent从未恢复
```

因为：

```text
Agent从未停止
```

这是这个设计最简洁的地方。

---

# 十二、用户点击“停止”怎么处理

刷新和停止必须是两个完全不同的语义。

刷新：

```text
disconnect SSE
```

停止：

```text
cancel Agent Task
```

API：

```text
DELETE /api/runs/{run_id}
```

Runtime：

```python
async def cancel_run(run_id: str):
    task = active_runs.get(run_id)

    if task:
        task.cancel()
```

Python 会向对应 Task 注入：

```python
asyncio.CancelledError
```

Agent 执行函数捕获：

```python
async def execute_agent(run_id: str):
    try:
        await run_deep_agent(run_id)

    except asyncio.CancelledError:
        await mark_cancelled(run_id)
        raise
```

于是：

```text
用户点击停止
      ↓
DELETE /runs/run_123
      ↓
task.cancel()
      ↓
CancelledError
      ↓
Agent退出
      ↓
RequestRun = cancelled
```

---

# 十三、为什么要有 cancelling 状态

实际系统中：

```text
用户点击停止
```

和：

```text
Agent完全停止
```

之间可能有一个非常短的时间差。

因此推荐：

```text
running
   ↓
cancelling
   ↓
cancelled
```

前端可以展示：

```text
正在停止...
```

真正收到 `CancelledError` 后：

```text
已停止
```

这样状态更加准确。

---

# 十四、F5 和 Stop 的区别

整个系统最重要的两个方向：

### F5

```text
Browser
   X

SSE Subscriber
   X

Agent Task
   ✅
```

### Stop

```text
Browser
   │
DELETE /run
   │
   ▼
Agent Task
   X

SSE
   ↓
run.cancelled
   ↓
结束
```

所以可以总结成一句：

> **F5 操作的是 Subscriber；Stop 操作的是 Agent Task。**

---

# 十五、最终运行结构

整个 Runtime 可以非常薄：

```text
AgentRuntime

├── start(run_id)
├── cancel(run_id)
├── active_runs
├── publish(run_id, event)
├── subscribe(run_id)
└── graceful_shutdown()
```

核心数据：

```python
active_runs: dict[str, asyncio.Task]
```

核心启动：

```python
task = asyncio.create_task(
    execute_agent(run_id)
)
```

核心取消：

```python
task.cancel()
```

核心实时传输：

```text
Agent
 ↓
Subscriber Queue
 ↓
SSE
```

核心持久化：

```text
RequestRun
+
Message
```

---

# 十六、为什么当前阶段不需要 MQ

很多人看到“后台任务”，第一反应可能是：

```text
Celery
Redis Queue
RabbitMQ
Kafka
DBOS
Temporal
```

这些方案当然都能解决更高级的可靠性问题。

但我们当前的需求只是：

> 浏览器刷新不能停止 Agent。

`asyncio.create_task()` 已经足以把：

```text
HTTP生命周期
```

和：

```text
Agent生命周期
```

分开。

对比：

| 能力              | create_task | Durable MQ / Workflow |
| --------------- | ----------: | --------------------: |
| F5 后继续          |           ✅ |                     ✅ |
| SSE 断开继续        |           ✅ |                     ✅ |
| 显式取消            |           ✅ |                     ✅ |
| 单进程异步并发         |           ✅ |                     ✅ |
| 任务持久化           |           ❌ |                     ✅ |
| Worker crash 恢复 |           ❌ |                     ✅ |
| 跨机器接管           |           ❌ |                     ✅ |
| 自动 Retry        |           ❌ |                     ✅ |
| Workflow Replay |           ❌ |                     ✅ |
| 实现复杂度           |          很低 |                    较高 |

因此：

> 在需求没有要求 Worker Crash Recovery 之前，没有必要过早引入 Durable Workflow Runtime。

---

# 十七、当前方案明确不解决什么

这个方案必须诚实地定义 Failure Boundary。

当前 Agent Task 存在于：

```text
Python Process
```

所以：

```text
Browser F5                ✅
Browser close             ✅
SSE disconnect            ✅
短暂网络故障               ✅
HTTP Request结束           ✅
```

不会影响 Agent。

但是：

```text
Python Crash              ❌
Docker Container Restart  ❌
OOM Kill                  ❌
服务器重启                 ❌
机器宕机                   ❌
```

都会导致当前内存中的 Task 消失。

因此当前关系是：

```text
Browser Lifetime
        ≠
Agent Lifetime

Agent Lifetime
        =
Python Process Lifetime
```

这不是 Bug。

这是当前阶段主动选择的可靠性边界。

---

# 十八、正常部署如何避免中断

正常发布和异常 Crash 是两件事。

Agent Runtime 可以支持：

```text
Graceful Shutdown
+
Draining
```

例如：

```text
Runtime V1

Run A
Run B
Run C
```

准备发布：

```text
V1 → draining
```

不再接新任务。

启动：

```text
Runtime V2
```

新任务进入 V2。

旧：

```text
A
B
C
```

继续执行直到完成。

然后：

```text
V1 shutdown
```

所以正常 Rolling Restart 并不一定需要 Durable Workflow。

真正只有异常：

```text
kill -9
OOM
机器掉电
```

才会丢失正在执行的 Run。

---

# 十九、未来什么时候才需要 DBOS 或 MQ

升级触发条件应该非常明确。

如果未来产品提出：

> 一个 Agent 已经 Research 了 5 分钟，即使 Worker Crash，也不能重新开始，必须从之前的位置继续。

那么我们的可靠性目标就从：

```text
Browser Durability
```

升级成：

```text
Execution Durability
```

这时候才应该考虑：

```text
DBOS
Temporal
Celery + durable queue
其他 durable execution runtime
```

也就是说：

```text
F5 Recovery
        ↓
create_task 就够


Worker Crash Recovery
        ↓
需要 Durable Runtime
```

不要混为一谈。

---

# 二十、最终架构

我们当前采用的整体架构可以概括为：

```text
                         Browser
                            │
                     HTTP / SSE
                            │
                            ▼
                     Product API
                            │
                            ▼
                       RequestRun
                            │
                            ▼
                      PostgreSQL

                            │
                            │ start
                            ▼
                  Python Agent Runtime
                            │
                     create_task()
                            │
                            ▼
                       Deep Agent
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
           Search          Maps          Weather
             │
             └──────────────┬──────────────┘
                            │
                            ▼
                          LLM
```

实时链路：

```text
Deep Agent
    │
    ▼
Event Hub
    │
    ▼
Subscriber Queue
    │
    ▼
SSE
    │
    ▼
Browser
```

控制链路：

```text
POST /runs
    ↓
start Agent Task


DELETE /runs/:id
    ↓
cancel Agent Task
```

恢复链路：

```text
Browser F5
    ↓
GET /runs/:id
    ↓
读取 Snapshot
    ↓
重新 Subscribe SSE
```

---

# 二十一、最核心的设计原则

整个实现最后可以浓缩成五句话。

### 1.

```text
Agent Task ≠ SSE Task
```

### 2.

```text
SSE Disconnect ≠ Agent Cancel
```

### 3.

```text
RequestRun = Product Truth
```

### 4.

```text
Snapshot = Truth
Stream = Projection
```

### 5.

```text
Refresh = Reconnect
不是 Resume Execution
```

这五条原则一旦成立，浏览器 F5 后 Agent 继续执行的问题就已经解决了。

---

# 结语

Agent 产品真正进入生产阶段以后，很多问题已经不再只是 Prompt、模型和 Tool 的问题。

更重要的是：

```text
谁拥有一次 Agent Run？
谁决定它什么时候结束？
浏览器断开是否意味着任务结束？
实时流是不是系统的最终真相？
用户点击停止到底停止了什么？
```

如果这些运行时边界没有定义清楚，再强大的 Agent Framework 最后也可能只是：

> 一条必须让浏览器一直保持连接才能正常工作的长 HTTP 请求。

我们的实现没有一开始就引入复杂的 Durable Workflow Runtime。

而是从最基本的生命周期问题出发：

```text
Agent Execution
与
SSE Transport
解耦
```

通过：

```text
RequestRun
+
asyncio.create_task()
+
active Task Registry
+
Event Hub
+
SSE Subscriber
+
Persistent Snapshot
```

就实现了：

> **页面可以刷新，网络可以断开，SSE 可以重新连接，但 Agent 仍然继续完成自己的任务。**

对于当前阶段的 Agent 产品，这是一种足够简单、边界清晰，同时又具备良好演进空间的实现方式。
