# ADR-0009: Main Candidate Plan First + Iterative Research Agent

## Status

Accepted — supersedes ADR-0002 for the current Travel Research architecture.

## Context

旅行规划既需要 Main 保持完整的用户目标、路线取舍和最终回答上下文，也需要对价格、预约、开放、交通政策、天气等动态事实进行可靠核验。

此前 dedicated researcher / 多分支 Research 编排把“复杂研究”与“并行 worker 数量”绑定，导致 Research routing、usage、evidence 和 workflow orchestration 之间耦合过重。大量普通完整旅行规划实际上只需要少量现实事实核验，不应自动进入复杂 Research。

## Decision

Travel Research 固定采用：

```text
Main
→ Candidate Plan
→ Reality Gaps
→ Main Tools OR research_agent
→ ResearchFindings / facts
→ Main revise
→ Final Plan
```

具体决策：

1. Main 是唯一旅行规划负责人、最终决策者和最终回答者。
2. 完整旅行规划默认先形成 Candidate Plan，再识别会实质影响方案成立的现实信息缺口。
3. 少量、直接、边界清晰的现实事实由 Main 自己使用 Native Web Search、`web_fetch`、Maps、Weather 核验。
4. 只有复杂、多步骤、多来源、需要根据中间结果继续调查的独立研究任务才委托 `research_agent`。
5. `research_agent` 使用 PydanticAI 自身 Agent iterative tool-use loop；不新增 Python Research workflow engine。
6. Main 只传最小 ResearchRequest：objective、相关 Candidate Plan context、用户关键 constraints。
7. `research_agent` 只返回结构化 ResearchFindings，不生成最终 itinerary，不拥有 Budget / FX，不递归调用 Agent。
8. Research Agent 直接 await 于 Main 当前 tool call 中，不创建 detached task；父执行取消可沿 await 链传播。
9. Main 与 Research Agent 使用独立 role-local usage limits；Product AgentUsage 聚合完整 Main + child usage。
10. Host evidence attestation 继续校验 Native Search / web_fetch / Maps / Weather 的真实执行轨迹；unsupported verified claim 降级为 unresolved。
11. Product Runtime、Conversation、Message、RequestRun、Streaming、PostgreSQL、Redis ownership 保持不变。
12. Harness Skills 继续保留；Travel Research 不再依赖额外的并行编排层。

## Consequences

### Positive

- 普通旅行规划不再因为“完整行程”自动付出复杂 Research 成本；
- Main 保留完整旅行决策上下文，同时复杂调查拥有独立 child context；
- Research 深度由模型基于证据迭代决定，而不是预先固定研究轴 / worker 数量；
- Main 只消费压缩 Findings，避免完整 child tool trajectory 污染最终规划上下文；
- cancellation、usage、evidence boundary 更容易与 Product RequestRun 对齐；
- 更少的编排层和框架耦合。

### Trade-offs

- v1 同一 Main run 通过 Host gate 最多启动一次复杂 Research Agent run；
- Research Agent 不通过并行 fan-out 缩短多个独立 topic 的 wall-clock 时间；如果未来真实 eval 证明必要，应通过新的 ADR 决定是否增加受控并行，而不是恢复旧实现；
- media 继续只作为兼容 / presentation 字段，不在本 ADR 扩张图片架构。

## Supersedes

ADR-0002 保留为历史决策记录，但其 dedicated Travel Researcher 形态不再描述当前实现。本 ADR 是当前 Travel Research Source of Truth。
