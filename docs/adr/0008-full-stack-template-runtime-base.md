# ADR-0008: Full-Stack Template 作为 Application Runtime Base

## Status

Accepted

## Context

v6 已验证 AI Cognitive Core，但正式 C-End 产品仍需要 FastAPI、Auth、DB、Alembic、Docker、测试、Frontend 等通用 Application Runtime。

从空仓库重新 Vibe Coding 这些通用能力，会把大量精力浪费在成熟基础设施上。

## Decision

Travel Agent v7 使用：

```text
https://github.com/1efeng/FASTAPI-FULL-STACK-TEMPLATE
```

作为 Application Runtime Base。

模板不是 Travel Agent 架构 Source of Truth。

## Consequences

保留并适配成熟通用能力。

保留 `item` 作为标准业务 Module / 全栈参考实现，供后续 `conversation`、`request_run`、`usage` 等模块复用一致的分层、测试和客户端生成模式；`item` 不属于 Travel Agent 核心业务或旅行领域模型。

按 Roadmap 增量加入：

```text
Redis
LiteLLM
Travel Cognitive Core
OpenTelemetry
Conversation / Request Lifecycle
Agent Streaming Adapter
Travel Chat
```

历史说明：早期 roadmap 中的 `LangGraph PostgreSQL Persistence`、`LangSmith` 已被 v8.2 SUPERSEDED（分别由 StreamResumeStore / OpenTelemetry + M10 决策取代）。

当前项目 Python 基线已经是 3.14。
具体框架 API 仍必须以 `uv.lock` 中实际版本为准。
