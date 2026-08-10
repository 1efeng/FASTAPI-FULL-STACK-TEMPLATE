# ADR-0005: 10,000 DAU 基线采用模块化单体 + 多实例

## Status

Accepted

## Context

10,000 DAU 需要生产可靠性和横向扩展，但不自动意味着微服务。

## Decision

第一阶段保持一个 Travel Agent 业务单体，多实例部署，关键状态外置到 PostgreSQL / Redis / LiteLLM 等共享基础设施。

## Consequences

- 应用无状态；
- 可以单机多容器起步，也能平滑迁多机；
- 不上 Kubernetes-first；
- 只有真实热点、独立 SLA、团队边界、数据瓶颈出现时再拆服务。
