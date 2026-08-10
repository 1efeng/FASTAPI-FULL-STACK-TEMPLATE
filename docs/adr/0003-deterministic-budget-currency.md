# ADR-0003: Budget 与 Currency 使用确定性 Tool

## Status

Accepted

## Context

预算总和和汇率换算属于确定性问题，把它们拆成 LLM Agent 会增加成本和错误。

## Decision

- Budget 使用 deterministic calculator；
- Currency 使用确定性 external-data converter；
- 最终使用哪些价格仍由 Main 决定。

## Consequences

- 不创建 Budget Agent / Currency Agent；
- 数学结果可单元测试；
- FX 不可用时保留当地货币，不由模型猜汇率。
