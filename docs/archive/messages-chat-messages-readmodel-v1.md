> ⚠️ 已归档（2026-09-11）：`chat_messages` 规格在 Aegra 架构下**延后**（Aegra values 快照可渲染消息），是否建表待定。

# chat_messages：UI 展示读模型规格

## 1. 目的

`chat_messages` 是面向 UI 的展示读模型（投影），与 LangGraph checkpoint 分离：

- **checkpoint**：执行状态的事实源，保存全部消息与图状态，供恢复/续跑使用。
- **chat_messages**：最终 human/ai 消息的稳定副本，任意实例可读，供刷新/重连/未来产品功能（会话列表、标题、搜索）使用。

它不是第二套执行状态：写入只发生在 run 结束后，幂等 upsert，不参与执行判断。

## 2. 表结构

```sql
CREATE TABLE chat_messages (
    id          UUID PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES "user" (id) ON DELETE CASCADE,
    thread_id   VARCHAR(128) NOT NULL,
    seq         INTEGER NOT NULL,
    message_id  VARCHAR(255) NOT NULL,
    role        VARCHAR(16) NOT NULL,          -- 'human' | 'ai'
    payload     JSONB NOT NULL,                -- serialize_message 同构
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, thread_id, message_id)
);

CREATE INDEX ix_chat_messages_thread_seq
    ON chat_messages (user_id, thread_id, seq);
```

### 字段说明

- `thread_id`：用户可见线程 id（不拼接 owner 前缀；owner 用 `user_id` 表达）。
- `seq`：线程内单调递增游标，断线恢复时用 `after_seq` 增量拉取；由写入逻辑在事务内取 `MAX(seq)+1` 计算，避免并发写冲突。
- `message_id`：LangGraph 消息 id，幂等键；同一消息重复写入只更新不新增。
- `payload`：与 `backend/app/chat/protocol/adapter.py` 的 `serialize_message` 输出一致：
  - `{"type": "human"|"ai", "content": ..., "id": ..., "name": ...}`
  - AI 消息带 `tool_calls`（序列化后），保留工具调用元信息。

## 3. 写入路径

- 时机：`_run_agent` / `_resume_agent` 的流结束后，从 checkpoint `aget_state` 读取该线程最终消息列表。
- 过滤：只保留 `type in ("human", "ai")` 的消息；工具中间消息、system prompt 不落表。
- 幂等：按 `message_id` upsert；同线程同消息重复写入只更新 payload，不产生重复行。
- 事务边界：每次 run 结束后一次性写入（run 粒度），不追 token；中断的 run 其部分消息在成功续跑并结束后才补全。
- 并发：`MAX(seq)+1` 在同一事务内计算并插入；`UNIQUE(user_id, thread_id, message_id)` 兜底幂等。

## 4. 读取路径

`GET /threads/{thread_id}/messages?after_seq=<int>`（owner 作用域）

- 返回 `{"messages": [{"seq": ..., "role": ..., "payload": ...}]}`，按 `seq` 升序。
- `after_seq` 省略时返回全部；`after_seq` 提供时只返回大于该值的增量。
- 任意实例可读（PostgreSQL 共享），是跨实例内容级恢复的依据。

## 5. 边界与语义

- **resume ≠ 重发消息**：断流恢复调用 `run.resume`（空参）从 checkpoint 继续，绝不追加一条 human 消息。
- **完成线程 resume 为 no-op**：LangGraph 对已到 END 的线程继续执行时直接返回最终状态，不会重复内容。
- **允许滞后**：run 进行中 `chat_messages` 可能缺当前轮次消息（run 粒度写入）；刷新/重连时的即时展示以 checkpoint hydrate 为主，读模型用于跨实例内容兜底与产品数据。
- **不做事件级回放**：token 增量、工具进度事件不落库；跨实例不承诺逐 token 动画。
- **清理语义**：`user` 删除时级联删除（ON DELETE CASCADE）。

### 与 Redis Stream 的分工

`chat_messages` 与 Redis 事件流职责不同，二者互补、不重复：

- **`chat_messages`（PG）**：长期、权威的展示内容（可查、可做产品功能），run 粒度幂等写入，永不过期。
- **Redis Stream（协调层）**：最近事件的广播 + 有界回放（`MAXLEN`/TTL），服务 SSE 重连；不是权威数据，丢失不影响内容。
- 面试口径：**Redis 管"最近的事件流"，PostgreSQL 管"长期的内容"**。

## 6. 测试要点

- 幂等：同一 `message_id` 重复写入不产生重复行，payload 更新。
- `seq` 单调：同一线程连续写入 `seq` 严格递增；`after_seq` 查询只返回增量。
- 过滤：只落 human/ai，工具消息与 system 不落表。
- 恢复：断流后 resume 续跑，最终消息完整写入读模型。
- 并发：两轮 run 同时结束写入同一线程，`seq` 无冲突、无重复。
