# ADR-0007: 成熟框架能力优先，禁止平行自研基础设施

## Status

SUPERSEDED（by v8.2：Deep Agents / LangGraph / LangChain 已从 v8 runtime 移除；LangSmith 不再作为当前 AI Trace/Eval 决策；"成熟框架优先、禁止平行自研"的原则本身保留）

## Context

Vibe Coding 很容易在每次新任务中重新生成 Circuit Breaker、Checkpoint、Context Summary、SSE、Trace、Eval 等“看起来合理”的基础设施，最终形成多个 Source of Truth。

## Decision

Framework Ownership：

```text
Deep Agents   → Agent Harness / Context
LangGraph     → Checkpoint
LiteLLM       → LLM Infrastructure
LangSmith     → AI Trace / Eval
OpenTelemetry → Infrastructure span standard / instrumentation
FastAPI       → HTTP / SSE
```

Travel Agent 只实现业务层缺失能力。

## Consequences

新增与框架重叠的通用组件前必须写 ADR 证明：

1. 官方能力确实不能满足；
2. adapter 无法解决；
3. 自研维护成本可接受；
4. 有测试、升级和迁移策略。
