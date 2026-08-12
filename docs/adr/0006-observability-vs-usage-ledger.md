# ADR-0006: OTel / LangSmith / LiteLLM / Business Attribution 分层

## Status

SUPERSEDED（by v8.2：LangSmith 不再作为当前 AI Trace/Eval 决策，Agent semantic trace 走 OpenTelemetry，AI trace 平台选型 M10 再决策；OTel / LiteLLM / Business Attribution 分层保留）

## Context

Agent Trace、distributed trace、Gateway cost、产品成本归因是不同问题。将所有东西塞进一个自研 Usage/Trace DB 会重复成熟平台。

## Decision

```text
OpenTelemetry → 基础设施 span 标准协议与 propagation（不建设独立平台）
LangSmith     → Agent semantic trace / Eval
LiteLLM       → provider/model usage & cost
Business DB   → product usage attribution
```

## Consequences

- `trace_id` 以 OTel 为准；
- 不自研完整 tracing platform；
- 不自研 LLM price engine；
- Business Usage 保存 request/user/agent_role 等产品维度；
- 四个观测面通过 IDs 关联。
