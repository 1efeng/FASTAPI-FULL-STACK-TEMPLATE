# ADR-0002: 使用专用 Travel Researcher 隔离 Research Context

## Status

Accepted

## Context

旅行当前事实搜索可能产生大量网页、地图、天气和冲突信息，直接让 Main 承担全部 Research 会污染最终 reasoning context。

## Decision

完整旅行规划使用 `travel-researcher` 作为独立 Research Workspace。

## Consequences

- Main 保持最终取舍上下文清洁；
- Researcher 不澄清用户、不输出完整计划；
- Research Tool 失败在 Researcher 层形成 Findings / uncertainty；
- 普通单点旅行问答仍允许 Main 直接用 Tool。
