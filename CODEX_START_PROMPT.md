# Codex 首次接手提示词

把下面整段发给当前 Codex 项目：

```text
这是当前 Travel Agent v7 项目。

项目已经基于 FASTAPI-FULL-STACK-TEMPLATE，并已升级到 Python 3.14。
不要重新创建项目，不要降级 Python，不要第一步就进行大范围重构。

先完整阅读：
1. AGENTS.md
2. CODEX_HANDOFF.md
3. IMPLEMENTATION_NOTES.md
4. docs/文档体系.md
5. docs/产品文档.md
6. docs/架构v7.md
7. docs/开发文档.md
8. docs/路线图.md
9. docs/施工路线图.md
10. 当前任务相关 Contract

然后审计当前真实仓库：
- git status / branch
- top-level tree
- backend/app tree
- frontend tree
- pyproject.toml
- uv.lock
- compose files
- Alembic state
- current tests
- auth/user implementation
- item 标准业务 Module 参考实现是否保持可运行
- Redis/LiteLLM/LangGraph/LangSmith/OTel 是否已经存在
- 是否已经迁入任何 v6 Travel Agent 文件

运行仓库当前已经支持的安全 baseline checks。

修改业务代码之前：
1. 根据真实代码更新 IMPLEMENTATION_NOTES.md；
2. 对照 docs/施工路线图.md；
3. 找到第一个“真正未完成且前置依赖已满足”的最小任务；
4. 只实现这一项；
5. 保持仓库可运行；
6. 跑相关测试；
7. 更新 施工路线图.md 与 IMPLEMENTATION_NOTES.md。

Framework Ownership：
Travel Agent = 产品/业务
Deep Agents = Agent Harness/Context
LangGraph = Checkpoint/Resume
LiteLLM = LLM routing/retry/fallback/health/cost
LangSmith = AI Trace/Eval
OpenTelemetry = Distributed Trace
FastAPI = HTTP/Native SSE
PostgreSQL = Durable State
Redis = Shared Runtime State

禁止自研：
CircuitBreaker、ProviderRouter、Checkpoint Schema、通用 Context Summarizer、
SSE Framework、TraceIdManager、LLM Pricing Engine、Eval Platform。

第一次完成后向我报告：
- verified current state
- tests/checks run
- docs updated
- completed smallest task
- blockers
- next smallest task
```
