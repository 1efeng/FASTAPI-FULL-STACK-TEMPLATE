# Stream Durability / Resume 说明 — SUPERSEDED

> 更新时间：2026-08-13  
> 状态：**SUPERSEDED AS IMPLEMENTATION SOT**  
> 原文曾采用 `asyncio + Redis Streams(XADD/XREAD) + SSE` 作为 F5/reconnect 默认实现。  
> v8.2 已完成架构收敛，后续 M8 不再按原方案施工。

---

# 1. 为什么被替代

旧方案把：

```text
每个 UI chunk
→ Redis XADD
→ browser cursor = Redis Stream ID
→ XREAD replay/live
```

固定成 Product Streaming 架构。

v8.2 现在采用：

```text
Vercel AI SDK UI protocol
→ PydanticAI VercelAIAdapter
→ opaque encoded chunks
→ project-owned StreamResumeStore
→ RedisStreamResumeStore
```

Current implementation：

```text
Redis KV transport state
+
Redis Pub/Sub
+
producer-memory replay backlog
```

不再默认把每个 token/event 持久化到 Redis Streams。

---

# 2. Reset 后状态

本文本身已经是历史说明，不再定义 TARGET Architecture。

当前设计入口：

```text
docs/产品文档.md
docs/架构.md
AGENTS.md
```

如果需要理解 CURRENT stream 实现，可直接查看：

```text
backend/app/infra/stream_resume/README.md
backend/app/infra/stream_resume/protocol.py
backend/app/infra/stream_resume/redis_store.py
```

`docs/接口契约.md` 在 2026-08-19 reset 后属于 PROVISIONAL / NEEDS AUDIT，不能反向定义新架构。

---

# 3. 当前 Stream Resume Contract

```text
StreamResumeStore
├ start(stream_id, producer)
├ resume(stream_id)
├ start_or_resume(stream_id, producer)
├ status(stream_id)
└ close()
```

identity：

```text
stream_id = str(request_id)
```

transport state：

```text
MISSING
ACTIVE
DONE
FAILED
INTERRUPTED
```

这些不是 Product RequestRun state。

---

# 4. Ownership

`StreamResumeStore` 只拥有：

```text
one active producer claim
cross-replica producer discovery
producer-memory replay
active HTTP/UI reconnect
opaque string chunks
```

不拥有：

```text
RequestRun
Conversation / Message
Auth
Idempotency
Quota
Product Cancel
Pydantic cancellation
Vercel protocol encoding
Execution Durability
```

---

# 5. 当前能解决

```text
Browser F5
network disconnect
new subscriber
reconnect 落另一 FastAPI replica
active producer backlog replay
live continuation
```

前提：

```text
producer process 仍然活着
```

---

# 6. 当前不能解决

```text
producer process hard crash
server restart
worker handoff
rolling deploy 自动迁移 execution
```

这些属于：

```text
Execution Durability
→ future DBOS / Temporal
```

---

# 7. Product Terminal Rule

非终态 UI chunks 可以实时发送。

success terminal 必须：

```text
Agent final
→ Product Success TX
→ assistant final INSERT
→ RequestRun completed CAS
→ COMMIT
→ emit success terminal
```

禁止先发 finish 再落库。

---

# 8. Product Stop

```text
POST /requests/{request_id}/cancel
→ Product CAS
→ Pydantic first-party cancellation
```

不是：

```text
SSE disconnect
AI SDK browser abort
StreamResumeStore.close
```

---

# 9. Redis Streams 未来是否永远禁止？

不是。

如果未来 benchmark/failure requirement 证明：

```text
per-chunk durable log
producer crash 后仍需 partial replay
audit/replay requirement
```

确有价值，可以实现新的：

```text
RedisStreamsStreamResumeStore
```

但必须仍然位于：

```text
StreamResumeStore port
```

后面。

不得改变：

```text
Product RequestRun
Browser protocol
stream identity
Product lifecycle
```

因此 Redis Streams 是**可替换 backend 候选**，不是 v8.2 默认架构。

---

# 10. 迁移映射

```text
旧 run:123:events Redis Stream
→ 删除为默认架构假设

旧 Redis Stream event ID cursor
→ 不进入 Product API

旧 XADD/XREAD endpoint implementation
→ 不再施工

旧“Stream durability = Redis Streams”
→ 改为 Active Stream Resume = StreamResumeStore

旧“Redis Stream 可以恢复 execution”
→ 错误；Execution durability 独立由 future DBOS/Temporal 解决
```

本文件仅用于说明为什么旧方案被替代，不得再作为 Codex M8 implementation guide。
