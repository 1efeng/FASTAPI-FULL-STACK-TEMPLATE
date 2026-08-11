# FastAPI + Redis Stream + SSE：实现 Agent 页面 F5 不丢任务、断线可重连

## 1. 要解决的问题

在普通 Agent Chat 实现中，经常会直接把 Agent 执行绑定到 HTTP/SSE 请求：

```text
Browser
   │
   │ SSE
   ▼
FastAPI
   │
   ▼
Agent
```

这种结构的问题是：

```text
用户 F5
   ↓
SSE 连接断开
   ↓
HTTP Request 结束
   ↓
Agent 可能一起被取消
```

我们真正想要的是：

```text
用户 F5
   ↓
SSE 连接断开

但：

Agent                  ✅ 继续执行
Redis 中已经产生的事件 ✅ 保留
新产生的事件           ✅ 继续写入

页面重新打开
   ↓
恢复之前内容
   ↓
继续接收新内容
```

本文采用一个非常小的架构：

```text
FastAPI
+
asyncio 后台任务
+
Redis Stream
+
SSE
```

不引入：

```text
DBOS
Temporal
Celery
Kafka
Redis Pub/Sub
Consumer Group
```

本文也明确不解决：

```text
FastAPI 进程崩溃后的 Agent 恢复
服务器重启后的 Agent 恢复
Worker A → Worker B 自动接管
```

只解决：

> **浏览器 F5 / 网络断开不能影响 Agent，并且重新连接后可以恢复流。**

---

# 2. 最终架构

```text
                       Browser
                          │
                   POST /api/runs
                          │
                          ▼
                  ┌──────────────┐
                  │  FastAPI A   │
                  └──────┬───────┘
                         │
                  asyncio.create_task
                         │
                         ▼
                       Agent
                         │
                         │ XADD
                         ▼
              ┌────────────────────┐
              │    Redis Stream    │
              │                    │
              │ run:123:events     │
              │                    │
              │ 1-0 run.started    │
              │ 2-0 text.delta     │
              │ 3-0 text.delta     │
              │ 4-0 tool.started   │
              │ 5-0 text.delta     │
              │ ...                │
              └─────────┬──────────┘
                        │
                     XREAD
                        │
                        ▼
                  ┌──────────────┐
                  │  FastAPI A   │
                  └──────┬───────┘
                         │ SSE
                         ▼
                      Browser
```

用户 F5 后，第二次请求甚至可以进入另一个 FastAPI：

```text
                       Browser
                          │
                         F5
                          │
                          ▼
                   Load Balancer
                          │
                          ▼
                  ┌──────────────┐
                  │  FastAPI B   │
                  └──────┬───────┘
                         │
                       XREAD
                         │
                         ▼
                    Redis Stream
                         ▲
                         │
                       XADD
                         │
                    FastAPI A
                         │
                       Agent
```

FastAPI B 不需要知道 Agent 在 FastAPI A。

它只需要知道：

```text
run_id
+
Redis Stream cursor
```

即可。

---

# 3. 为什么 Redis Stream 特别适合这个场景

Redis Stream 中每条消息都有自己的 ID，例如：

```text
1740000000000-0
1740000000100-0
1740000000200-0
```

我们可以把它直接作为：

```text
SSE event id
```

Redis 官方推荐的 `XREAD` 使用方式就是：保存最后收到的 Stream ID，下一次继续从这个 ID 往后读取；`BLOCK` 可以在没有新事件时等待未来事件。

因此：

```text
客户端最后收到：

1740000000200-0
```

断线以后：

```text
XREAD run:123:events 1740000000200-0
```

Redis 返回：

```text
> 1740000000200-0
```

也就是：

```text
1740000000300-0
1740000000400-0
1740000000500-0
...
```

天然就是：

```text
历史补发
+
实时等待
```

而且不用在：

```text
history mode
live mode
```

之间切换。

---

# 4. Event 设计

不要直接把 Agent 的 Python 对象扔给前端。

定义一个稳定的事件协议。

例如：

```json
{
  "type": "text.delta",
  "data": {
    "delta": "北京"
  }
}
```

建议第一版只保留几个事件：

```text
run.started

text.delta

tool.started

tool.finished

run.completed

run.failed
```

一个旅行 Agent 的 Redis Stream 最终可能长这样：

```text
1-0
run.started

2-0
text.delta
{"delta":"我"}

3-0
text.delta
{"delta":"推荐"}

4-0
tool.started
{"tool":"search_route"}

5-0
tool.finished
{"tool":"search_route"}

6-0
text.delta
{"delta":"北京到承德"}

7-0
run.completed
```

Redis `XADD` 会为 Stream entry 自动生成 ID；同时 Redis 也支持通过 `MAXLEN` 等方式裁剪旧数据。

---

# 5. 后端依赖

Python：

```bash
pip install fastapi uvicorn redis
```

假设 Redis：

```text
redis://localhost:6379/0
```

项目结构：

```text
app/
├── main.py
├── redis_client.py
├── run_manager.py
└── agent.py
```

为了文章完整，下面也可以先全部写在一个文件里。

---

# 6. Redis 初始化

```python
from redis.asyncio import Redis

redis = Redis.from_url(
    "redis://localhost:6379/0",
    decode_responses=True,
)
```

定义 key：

```python
def run_stream_key(run_id: str) -> str:
    return f"agent:run:{run_id}:events"


def run_meta_key(run_id: str) -> str:
    return f"agent:run:{run_id}:meta"
```

其中：

```text
agent:run:{run_id}:events
```

保存事件。

```text
agent:run:{run_id}:meta
```

保存：

```text
status
user_id
```

---

# 7. 写入 Agent Event

封装一个统一函数：

```python
import json
from datetime import datetime, timezone


async def append_event(
    run_id: str,
    event_type: str,
    data: dict,
) -> str:
    stream_key = run_stream_key(run_id)

    event_id = await redis.xadd(
        stream_key,
        {
            "type": event_type,
            "data": json.dumps(
                data,
                ensure_ascii=False,
            ),
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        },
    )

    return event_id
```

例如：

```python
await append_event(
    run_id,
    "text.delta",
    {
        "delta": "北京",
    },
)
```

Redis：

```text
agent:run:abc123:events

1740000000010-0
type = text.delta
data = {"delta":"北京"}
```

---

# 8. 最关键一步：Agent 和 SSE 解耦

错误做法：

```python
@app.post("/chat")
async def chat(request):
    async for chunk in agent_stream():
        yield chunk
```

这里：

```text
HTTP Request
=
Agent 生命周期
```

我们要改成：

```text
HTTP 创建 Run
↓
后台 asyncio Task
↓
Agent 独立执行
```

---

# 9. 后台 Task Registry

`asyncio.create_task()` 最好保存引用。

```python
import asyncio
from collections.abc import Coroutine
from typing import Any


background_tasks: set[asyncio.Task[Any]] = set()


def spawn_background_task(
    coroutine: Coroutine[Any, Any, Any],
):
    task = asyncio.create_task(coroutine)

    background_tasks.add(task)

    task.add_done_callback(
        background_tasks.discard
    )

    return task
```

之后：

```python
spawn_background_task(
    execute_agent(...)
)
```

浏览器 HTTP 请求结束，不影响这个 Task。

---

# 10. Agent 执行逻辑

```python
async def execute_agent(
    run_id: str,
    user_id: str,
    prompt: str,
):
    try:
        await redis.hset(
            run_meta_key(run_id),
            mapping={
                "status": "running",
                "user_id": user_id,
            },
        )

        await append_event(
            run_id,
            "run.started",
            {},
        )

        async for delta in stream_agent(prompt):
            await append_event(
                run_id,
                "text.delta",
                {
                    "delta": delta,
                },
            )

        await append_event(
            run_id,
            "run.completed",
            {},
        )

        await redis.hset(
            run_meta_key(run_id),
            mapping={
                "status": "completed",
            },
        )

    except Exception as exc:
        await append_event(
            run_id,
            "run.failed",
            {
                "message": str(exc),
            },
        )

        await redis.hset(
            run_meta_key(run_id),
            mapping={
                "status": "failed",
            },
        )

    finally:
        # Run 完成后保留 24 小时，
        # 方便 F5 / 网络重连。
        await redis.expire(
            run_stream_key(run_id),
            86400,
        )

        await redis.expire(
            run_meta_key(run_id),
            86400,
        )
```

---

# 11. 接入真实 Agent

`stream_agent()` 是 Agent Framework 和我们的 Runtime 之间唯一需要适配的地方。

例如：

```python
async def stream_agent(prompt: str):
    async for chunk in your_agent_stream(prompt):
        yield chunk
```

如果使用 LangGraph / Deep Agents，可以类似：

```python
async def stream_agent(prompt: str):
    async for event in agent.astream_events(
        {
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ]
        },
        version="v2",
    ):
        if event["event"] != "on_chat_model_stream":
            continue

        chunk = event["data"]["chunk"]

        content = getattr(
            chunk,
            "content",
            "",
        )

        if isinstance(content, str) and content:
            yield content
```

以后要增加 Tool Event，也只改这一层：

```python
if event["event"] == "on_tool_start":
    await append_event(
        run_id,
        "tool.started",
        {
            "tool": event["name"],
        },
    )
```

Agent Framework 本身不需要知道 SSE 存在。

---

# 12. 创建 Run API

```python
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI()


class CreateRunRequest(BaseModel):
    message: str


class CreateRunResponse(BaseModel):
    run_id: str


@app.post(
    "/api/runs",
    response_model=CreateRunResponse,
)
async def create_run(
    body: CreateRunRequest,
):
    # 正式项目这里应该来自 JWT / Session。
    user_id = "current-user"

    run_id = uuid4().hex

    await redis.hset(
        run_meta_key(run_id),
        mapping={
            "user_id": user_id,
            "status": "pending",
        },
    )

    spawn_background_task(
        execute_agent(
            run_id=run_id,
            user_id=user_id,
            prompt=body.message,
        )
    )

    return {
        "run_id": run_id,
    }
```

请求：

```http
POST /api/runs
Content-Type: application/json

{
  "message": "帮我规划北京到承德三天自驾游"
}
```

立即返回：

```json
{
  "run_id": "7d58dc1ed748..."
}
```

注意：

> 这里不要等待 Agent 完成。

HTTP 请求到此结束。

Agent 已经独立运行。

---

# 13. SSE 接口

FastAPI 官方 `StreamingResponse` 可以接受 async generator，然后持续向客户端发送响应体。

实现：

```python
import asyncio
import json

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse


TERMINAL_EVENTS = {
    "run.completed",
    "run.failed",
}


def encode_sse(
    event_id: str,
    event_type: str,
    data: str,
) -> str:
    return (
        f"id: {event_id}\n"
        f"event: {event_type}\n"
        f"data: {data}\n\n"
    )


@app.get(
    "/api/runs/{run_id}/stream"
)
async def stream_run(
    run_id: str,
    request: Request,
    cursor: str = "0-0",
):
    meta_key = run_meta_key(run_id)
    stream_key = run_stream_key(run_id)

    exists = await redis.exists(meta_key)

    if not exists:
        raise HTTPException(
            status_code=404,
            detail="Run not found",
        )

    # 正式项目这里必须验证：
    #
    # run.user_id == current_user.id

    async def event_generator():
        last_id = cursor

        while True:
            if await request.is_disconnected():
                break

            streams = await redis.xread(
                {
                    stream_key: last_id,
                },
                count=100,
                block=15_000,
            )

            if not streams:
                status = await redis.hget(
                    meta_key,
                    "status",
                )

                if status in {
                    "completed",
                    "failed",
                }:
                    break

                # SSE heartbeat
                yield ": ping\n\n"
                continue

            for _, entries in streams:
                for event_id, fields in entries:
                    event_type = fields["type"]
                    data = fields["data"]

                    yield encode_sse(
                        event_id=event_id,
                        event_type=event_type,
                        data=data,
                    )

                    last_id = event_id

                    if event_type in TERMINAL_EVENTS:
                        return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

核心就在：

```python
streams = await redis.xread(
    {
        stream_key: last_id,
    },
    block=15_000,
)
```

假设：

```text
last_id = 100-0
```

Redis 会读取：

```text
> 100-0
```

的事件。

所以不会重新返回已经确认处理的 `100-0`。

---

# 14. 为什么不需要 XRANGE + Pub/Sub

有些实现会设计成：

```text
XRANGE
↓
历史重放

然后：

Pub/Sub
↓
实时消息
```

问题是：

```text
历史结束
→
实时订阅开始
```

中间天然存在切换窗口。

我们的方案不存在两个阶段。

永远只有：

```text
XREAD cursor
```

流程：

```text
有历史
↓
立即返回历史

历史读完
↓
继续 XREAD

没有新数据
↓
BLOCK

Agent XADD
↓
XREAD 立即返回
```

天然完成：

```text
Replay → Live
```

切换。

---

# 15. 前端为什么推荐 fetch，而不是原生 EventSource

浏览器原生：

```javascript
new EventSource(...)
```

当然可以使用。

SSE 标准里的：

```text
id:
```

字段会更新 EventSource 内部的 last event ID；连接丢失后浏览器也支持自动重连。

但是很多业务系统需要：

```http
Authorization: Bearer xxx
```

原生 `EventSource` 不方便自定义 Authorization Header。

因此这里直接使用：

```text
fetch
+
ReadableStream
```

读取 `text/event-stream`。

这样：

```text
Bearer Token
AbortController
自定义 cursor
F5 snapshot
```

都很好处理。

---

# 16. 前端 SSE Parser

```javascript
async function connectRunStream({
  runId,
  cursor,
  token,
  signal,
  onEvent,
}) {
  const response = await fetch(
    `/api/runs/${runId}/stream?cursor=${encodeURIComponent(cursor)}`,
    {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${token}`,
      },
      signal,
    },
  );

  if (!response.ok) {
    throw new Error(
      `stream failed: ${response.status}`,
    );
  }

  if (!response.body) {
    throw new Error('response body is empty');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  let buffer = '';

  while (true) {
    const {
      done,
      value,
    } = await reader.read();

    if (done) {
      return;
    }

    buffer += decoder.decode(
      value,
      {
        stream: true,
      },
    );

    // 统一换行符
    buffer = buffer.replace(
      /\r\n/g,
      '\n',
    );

    while (true) {
      const index = buffer.indexOf(
        '\n\n',
      );

      if (index === -1) {
        break;
      }

      const rawEvent = buffer.slice(
        0,
        index,
      );

      buffer = buffer.slice(
        index + 2,
      );

      // heartbeat
      if (
        rawEvent.startsWith(':')
      ) {
        continue;
      }

      let id = '';
      let type = 'message';
      const dataLines = [];

      for (
        const line of rawEvent.split('\n')
      ) {
        if (line.startsWith('id:')) {
          id = line.slice(3).trim();
        }

        if (
          line.startsWith('event:')
        ) {
          type = line
            .slice(6)
            .trim();
        }

        if (
          line.startsWith('data:')
        ) {
          dataLines.push(
            line.slice(5).trimStart(),
          );
        }
      }

      const dataText =
        dataLines.join('\n');

      onEvent({
        id,
        type,
        data: dataText
          ? JSON.parse(dataText)
          : {},
      });
    }
  }
}
```

---

# 17. `last_event_id` 到底是什么

这里特别容易搞混。

例如前端已经处理：

```text
100-0  "我"
101-0  "推荐"
102-0  "北京"
```

那么：

```text
last_event_id = 102-0
```

它表示：

> 我已经成功处理到 `102-0`。

它**不是页面内容**。

也就是说：

```text
last_event_id
```

只能告诉服务器：

```text
从哪里继续
```

不能告诉浏览器：

```text
之前页面显示了什么
```

所以 F5 后恢复页面有两种方案。

---

# 18. 方案 A：F5 后从 0-0 全量 Replay

这是最简单、最可靠的第一版。

页面刷新：

```text
React state
全部丢失
```

但是：

```text
run_id
```

保存在：

```text
sessionStorage
```

页面重新打开：

```text
cursor = 0-0
```

于是：

```text
XREAD stream 0-0
```

Redis：

```text
1
2
3
4
...
100
101
102
```

全部重新发送。

React reducer：

```text
run.started
text.delta
text.delta
tool.started
...
```

重新执行一次。

页面自然恢复。

然后：

```text
cursor = 102-0
```

继续：

```text
XREAD BLOCK 102-0
```

等待 103。

这是一套非常漂亮的：

```text
Event Replay
```

模型。

---

# 19. 方案 B：缓存 UI Snapshot + last_event_id

如果希望：

> F5 后页面瞬间恢复，不等待 Redis replay。

可以把：

```text
当前 UI
+
last_event_id
```

一起放进 `sessionStorage`。

关键点：

> 不要分别保存。

应该保存一个整体 snapshot。

例如：

```json
{
  "cursor": "102-0",
  "text": "我推荐北京...",
  "status": "running"
}
```

这样 cursor 与页面状态始终绑定。

---

# 20. React Snapshot 实现

```javascript
function snapshotKey(runId) {
  return `agent:run:${runId}:snapshot`;
}


function loadSnapshot(runId) {
  const raw = sessionStorage.getItem(
    snapshotKey(runId),
  );

  if (!raw) {
    return {
      cursor: '0-0',
      text: '',
      status: 'running',
    };
  }

  try {
    return JSON.parse(raw);
  } catch {
    return {
      cursor: '0-0',
      text: '',
      status: 'running',
    };
  }
}


function saveSnapshot(
  runId,
  snapshot,
) {
  sessionStorage.setItem(
    snapshotKey(runId),
    JSON.stringify(snapshot),
  );
}
```

事件处理：

```javascript
function reduceAgentEvent(
  snapshot,
  event,
) {
  const next = {
    ...snapshot,
    cursor: event.id,
  };

  switch (event.type) {
    case 'text.delta':
      next.text +=
        event.data.delta ?? '';
      break;

    case 'run.started':
      next.status = 'running';
      break;

    case 'run.completed':
      next.status = 'completed';
      break;

    case 'run.failed':
      next.status = 'failed';
      break;
  }

  return next;
}
```

这样一次事件：

```text
text.delta
+
event id
```

会一次性变成：

```json
{
  "cursor": "103-0",
  "text": "我推荐北京到承德...",
  "status": "running"
}
```

---

# 21. React Hook 完整实现

```javascript
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';


const CURRENT_RUN_KEY =
  'agent:current-run';


export function useAgentRun(token) {
  const [runId, setRunId] =
    useState(() =>
      sessionStorage.getItem(
        CURRENT_RUN_KEY,
      ),
    );

  const initialSnapshot =
    runId
      ? loadSnapshot(runId)
      : {
          cursor: '0-0',
          text: '',
          status: 'idle',
        };

  const [
    snapshot,
    setSnapshot,
  ] = useState(initialSnapshot);

  const controllerRef =
    useRef(null);


  const applyEvent = useCallback(
    (event) => {
      setSnapshot((current) => {
        const next =
          reduceAgentEvent(
            current,
            event,
          );

        if (runId) {
          saveSnapshot(
            runId,
            next,
          );
        }

        return next;
      });
    },
    [runId],
  );


  useEffect(() => {
    if (!runId) {
      return;
    }

    const controller =
      new AbortController();

    controllerRef.current =
      controller;

    let retryDelay = 1000;


    async function follow() {
      while (
        !controller.signal.aborted
      ) {
        const current =
          loadSnapshot(runId);

        if (
          current.status ===
            'completed' ||
          current.status ===
            'failed'
        ) {
          return;
        }

        try {
          await connectRunStream({
            runId,
            cursor:
              current.cursor ??
              '0-0',
            token,
            signal:
              controller.signal,
            onEvent: applyEvent,
          });

          const latest =
            loadSnapshot(runId);

          if (
            latest.status ===
              'completed' ||
            latest.status ===
              'failed'
          ) {
            return;
          }

        } catch (error) {
          if (
            controller.signal
              .aborted
          ) {
            return;
          }

          console.warn(
            'SSE disconnected',
            error,
          );
        }

        await new Promise(
          (resolve) =>
            setTimeout(
              resolve,
              retryDelay,
            ),
        );

        retryDelay = Math.min(
          retryDelay * 1.5,
          10_000,
        );
      }
    }

    follow();

    return () => {
      controller.abort();
    };
  }, [
    runId,
    token,
    applyEvent,
  ]);


  async function startRun(
    message,
  ) {
    controllerRef.current?.abort();

    const response = await fetch(
      '/api/runs',
      {
        method: 'POST',
        headers: {
          'Content-Type':
            'application/json',

          Authorization:
            `Bearer ${token}`,
        },

        body: JSON.stringify({
          message,
        }),
      },
    );

    if (!response.ok) {
      throw new Error(
        'create run failed',
      );
    }

    const data =
      await response.json();

    const newRunId =
      data.run_id;

    const initial = {
      cursor: '0-0',
      text: '',
      status: 'running',
    };

    sessionStorage.setItem(
      CURRENT_RUN_KEY,
      newRunId,
    );

    saveSnapshot(
      newRunId,
      initial,
    );

    setSnapshot(initial);
    setRunId(newRunId);
  }


  return {
    runId,

    text: snapshot.text,

    status: snapshot.status,

    startRun,
  };
}
```

---

# 22. 页面使用

```jsx
import {
  useState,
} from 'react';

import {
  useAgentRun,
} from './useAgentRun';


export default function AgentPage() {
  const token = 'YOUR_TOKEN';

  const [
    message,
    setMessage,
  ] = useState('');

  const {
    text,
    status,
    startRun,
  } = useAgentRun(token);


  return (
    <div>
      <textarea
        value={message}
        onChange={(event) =>
          setMessage(
            event.target.value,
          )
        }
      />

      <button
        onClick={() =>
          startRun(message)
        }
      >
        开始
      </button>

      <div>
        状态：{status}
      </div>

      <pre>
        {text}
      </pre>
    </div>
  );
}
```

---

# 23. F5 的完整过程

现在假设 Agent 已经生成：

```text
1-0  我
2-0  推荐
3-0  北京
4-0  到
5-0  承德
```

浏览器 snapshot：

```json
{
  "cursor": "5-0",
  "text": "我推荐北京到承德",
  "status": "running"
}
```

用户：

```text
F5
```

旧 SSE：

```text
❌
```

但后台：

```text
asyncio Agent Task ✅
```

继续：

```text
6-0 自
7-0 驾
8-0 三
9-0 天
```

Redis：

```text
1
2
3
4
5
6
7
8
9
```

页面加载。

React：

```javascript
loadSnapshot(runId)
```

立即得到：

```text
我推荐北京到承德
```

所以旧内容立刻显示。

然后：

```text
cursor = 5-0
```

请求：

```http
GET /api/runs/123/stream?cursor=5-0
```

FastAPI：

```python
XREAD run:123 5-0
```

Redis 返回：

```text
6
7
8
9
```

页面变成：

```text
我推荐北京到承德自驾三天
```

之后：

```text
XREAD BLOCK 9-0
```

等待下一条。

整个过程：

```text
F5
↓
恢复 snapshot
↓
拿 last_event_id
↓
XREAD > last_event_id
↓
补漏掉的消息
↓
继续实时
```

---

# 24. 如果 sessionStorage 丢了怎么办

也没关系。

默认：

```javascript
{
  cursor: '0-0',
  text: ''
}
```

重新从：

```text
0-0
```

开始。

Redis Stream 会重新发送：

```text
1
2
3
...
```

整个 UI 重新构建。

因此：

```text
sessionStorage
```

只是：

> F5 加速缓存。

真正的恢复源还是：

```text
Redis Stream
```

---

# 25. 多 FastAPI 实例为什么也成立

假设：

```text
Nginx
   │
   ├── FastAPI A
   ├── FastAPI B
   └── FastAPI C
```

第一次：

```text
POST /runs
↓
FastAPI A
↓
Agent Task 在 A
```

Agent：

```text
FastAPI A
↓
XADD
↓
Redis
```

第一次 SSE：

```text
Browser
↓
FastAPI B
↓
XREAD Redis
```

完全可以。

F5：

```text
Browser
↓
FastAPI C
↓
XREAD Redis
```

也完全可以。

因为：

```text
SSE Consumer
```

并不需要找到：

```text
Agent Task Owner
```

共享状态在：

```text
Redis Stream
```

而 Redis 普通 `XREAD` 本来就允许客户端独立按自己的 Stream ID 读取；它和用于 Worker 分配任务的 `XREADGROUP` 是不同模型。

因此：

```text
Sticky Session
```

不是必须的。

---

# 26. 为什么 SSE 不应该使用 Consumer Group

不要：

```text
XREADGROUP
```

因为 Consumer Group 的目标是：

```text
一个消息
↓
多个 Worker
↓
只交给其中一个处理
```

而我们的目标是：

```text
同一个 Stream
↓
浏览器 A 自己读
浏览器 B 自己读
重新连接也自己读
```

所以 SSE 应该使用：

```text
XREAD
```

每个连接维护自己的：

```text
cursor
```

---

# 27. Nginx 配置

SSE 前面如果有 Nginx，建议：

```nginx
location /api/runs/ {
    proxy_pass http://backend;

    proxy_http_version 1.1;

    proxy_buffering off;

    proxy_cache off;

    proxy_read_timeout 3600s;
}
```

Nginx 默认会进行 proxy response buffering；关闭 `proxy_buffering` 后，上游内容会更直接地传给客户端。官方文档也说明 `proxy_read_timeout` 默认是 60 秒，而且它衡量的是两次上游读取之间的时间。

我们的 SSE 又每 15 秒发送：

```text
: ping
```

因此连接不会长期完全没有数据。

---

# 28. Stream 保存多久

不要把 Redis Stream 当永久聊天数据库。

本文建议：

```text
运行中：
保留全部 Run Events

Run 完成：
保留 24 小时

最终 Assistant Message：
保存 PostgreSQL
```

也就是：

```text
Redis
=
实时执行日志 / Replay Buffer

PostgreSQL
=
最终业务数据
```

如果一次 Agent Run 产生很多 token，Redis Stream 可以使用：

```text
MAXLEN
```

进行裁剪；Redis 官方 `XADD` 原生支持 capped streams。

但如果要支持：

```text
F5 后从 0-0 完整 replay
```

就必须保证当前 Run 所需的事件还没有被裁掉。

因此第一版甚至可以：

> Run 运行期间不裁剪，完成后设置 TTL。

最简单。

---

# 29. 不建议每个字符写一次 Redis

不要：

```text
我
推
荐
北
京
...
```

每个字符：

```text
XADD
```

应该按照模型本身返回的 chunk：

```text
"我推荐"
"北京到"
"承德"
```

写 Redis。

如果模型 chunk 太碎，再增加：

```text
20~50ms buffer
```

批量合并即可。

这是性能优化。

第一版不用急着做。

---

# 30. 这个方案真正保证什么

它保证：

```text
浏览器 F5                ✅

SSE 网络断开             ✅

重新连接                 ✅

旧内容重新展示           ✅

遗漏消息补发             ✅

继续接收实时消息         ✅

FastAPI SSE 多实例       ✅

不需要 Sticky Session    ✅
```

但它不保证：

```text
Agent 所在 Python
进程崩溃                 ❌

服务器重启               ❌

Agent Task 自动
迁移到其他实例           ❌
```

这里一定要把两个问题分开：

```text
SSE 多实例
≠
Agent Execution 多实例 HA
```

当前需求只解决前者。

---

# 31. 最终核心代码其实只有四个概念

整个方案可以浓缩为：

```text
1. run_id

2. asyncio.create_task()

3. Redis Stream

4. cursor / last_event_id
```

创建：

```text
POST /runs
↓
run_id
↓
create_task(agent)
```

Agent：

```text
Agent Event
↓
XADD run:{run_id}:events
```

SSE：

```text
XREAD run:{run_id}:events cursor
↓
SSE
```

浏览器：

```text
event
↓
更新 UI
↓
保存 snapshot
↓
保存 cursor
```

F5：

```text
恢复 snapshot
↓
读取 cursor
↓
重新 XREAD
```

这就形成了一个完整闭环：

```text
              Agent
                │
                │
              XADD
                │
                ▼
          Redis Stream
          ▲           │
          │           │
       cursor       events
          │           │
          │           ▼
        FastAPI SSE
                │
                ▼
              React
                │
         ┌──────┴──────┐
         │             │
      UI State       cursor
         │             │
         └──────┬──────┘
                ▼
          sessionStorage
                │
               F5
                │
                ▼
             Restore
```

对于“只解决页面刷新导致 Agent 流丢失”这个需求，这套方案已经足够，而且复杂度明显低于引入完整 Durable Runtime。
