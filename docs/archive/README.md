# docs/archive

被新设计取代的旧文档归档区。**只读参考**，不再作为开发依据。

| 文件 | 原职责 | 取代者 |
| --- | --- | --- |
| `architecture-redis-coordination-v1.md` | 自研 Redis 协调层架构（Redis Stream 事件总线 + 分布式锁 + 30s 排水） | `docs/architecture.md`（Aegra 版定稿） |
| `messages-chat-messages-readmodel-v1.md` | `chat_messages` UI 展示读模型规格 | 延后；Aegra values 快照可渲染消息，是否建表待定 |
| `development-resumable-p1p5-v1.md` | P1–P5 自研 Runtime 方案（agent_runs/agent_events/租约/db_stream） | 同上 |

用途：保留决策历史；面试时可展示"自研打底 → build vs buy 评估 → 收敛到 Aegra"的完整链路。
