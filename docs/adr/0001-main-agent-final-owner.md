# ADR-0001: Main Agent 是唯一最终语义 Owner

## Status

Accepted

## Context

完整旅行规划包含 Research、预算、路线和用户偏好。如果每个子模块都生成最终答案，会产生多个互相竞争的语义 Owner。

## Decision

Main 是唯一用户入口、必要澄清 Owner、最终方案选择者和最终回答者。

Travel Researcher 只返回 Findings。

## Consequences

- Final 逻辑集中；
- 不新增 Writer / Planner / Validator Agent；
- Researcher 可以高噪声工作但不污染 Final Ownership；
- 任何未来 Agent 必须证明独立认知上下文价值。
