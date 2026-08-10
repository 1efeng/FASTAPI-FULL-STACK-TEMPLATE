# ADR-0004: Central LLM Gateway 采用 LiteLLM Proxy

## Status

Accepted

## Context

生产需要统一 Provider abstraction、retry/fallback、routing、health、limits、cost 和 Gateway HA。自研这些能力会重复成熟基础设施并增加长期维护成本。

## Decision

生产 Central LLM Gateway 采用 **LiteLLM Proxy**。

LiteLLM 是 provider retry/fallback/routing/cost 的主 Owner。

Travel Agent 保留 End-to-End Request Deadline 和 Business Quota。

## Rejected

- Application 直接分别接 DeepSeek/OpenAI 并自己 failover；
- 自研 ProviderRouter；
- 自研 CLOSED/OPEN/HALF_OPEN Circuit Breaker；
- Portkey 作为当前首选。

## Consequences

- Application 使用 OpenAI-compatible Gateway client；
- Provider keys 移到 LiteLLM；
- LiteLLM 自己需要生产版本、Redis/Postgres、HA 和 migration 管理；
- Usage Ledger 瘦身成 Business Attribution；
- 文档使用 LiteLLM cooldown/health/fallback 语义，不再写自研 breaker。
