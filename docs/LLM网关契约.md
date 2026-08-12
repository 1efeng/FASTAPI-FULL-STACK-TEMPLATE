# LiteLLM 网关契约

> 更新时间：2026-08-13
> 状态：v8 clean baseline

> P0-1 唯一 LLM Gateway Contract。  
> 生产选型：**LiteLLM Proxy**。  
> 本项目不自研通用 LLM Gateway。

# 1. Owner

LiteLLM 负责：

- OpenAI-compatible provider abstraction；
- model groups / deployments；
- provider routing；
- bounded retry；
- fallback；
- per-call timeout；
- cooldown / health-aware routing；
- RPM / TPM / max parallel 等模型基础设施限制；
- Virtual Key / service access；
- spend / cost tracking；
- gateway telemetry。

# 2. 不负责

LiteLLM 不负责：

- Travel Agent 用户意图；
- Business Authentication / Authorization；
- Business quota；
- Idempotency；
- 整个用户请求的 End-to-End Deadline；
- Tool resilience；
- conversation state；
- business usage attribution；
- final persistence。

# 3. Application Integration

生产：

```text
Main / Researcher
→ OpenAI-compatible model client
→ LiteLLM Proxy
→ logical model
→ provider deployment
```

Application 不直接持有生产 Provider keys。

Application 最少只知道：

```text
LITELLM_BASE_URL
LITELLM_SERVICE_KEY
LOGICAL_MODEL
```

# 4. Logical Model Groups

P0 可以先：

```text
travel-agent
  ├── Primary deployment(s): DeepSeek
  └── Fallback group: compatible secondary provider
```

P1 再引入：

```text
travel-main
travel-research
```

业务 role 选哪个 logical model 是 Travel Agent policy；deployment / provider 选路由由 LiteLLM。

# 5. Retry / Fallback

LiteLLM 是 LLM provider retry 的唯一主 Owner。

规则：

- retry finite；
- fallback finite；
- provider / deployment error 分类按 LiteLLM 能力；
- Application / SDK 不再做同级 provider retry；
- total user deadline 耗尽时 Application 可以阻止新的 LLM call。

# 6. Timeout

区分：

```text
LiteLLM per-call timeout
≠
Travel Agent end-to-end request deadline
```

Application 计算 remaining deadline，并把可用时间限制到当前 downstream call。

# 7. Provider Isolation

架构语义使用 LiteLLM：

- reactive cooldown；
- failure thresholds / allowed failures policy；
- proactive health check（启用时）；
- health-aware routing；
- fallback。

不在应用层实现 `CLOSED / OPEN / HALF_OPEN` 自研 Circuit Breaker。

# 8. Shared State

生产多副本时，按启用能力配置 LiteLLM 所需：

- PostgreSQL；
- Redis。

LiteLLM persistence 与 Travel Agent business tables 使用独立 migration ownership。

# 9. Auth / Key

Travel Agent 服务通过 LiteLLM Virtual / Service Key 访问 Gateway。

不要给每个 C-End 用户直接发 LiteLLM key；C-End Auth 仍在 Application。

# 10. Spend / Cost

LiteLLM 是模型基础设施 cost/spend Source of Truth。

Application 从 LiteLLM metadata / response / logging payload 获取：

- call id；
- actual model；
- usage；
- response cost；
- status。

业务库只做 attribution，不重新计算供应商价格。

# 11. Metadata

每次真实 LLM call 应尽可能关联：

```text
request_id
trace_id
agent_role
conversation_id（按隐私策略）
logical_model
litellm_call_id
actual_model / deployment
usage
cost
status
```

# 12. Observability

必须观察：

- request count；
- model/deployment；
- latency；
- retry；
- fallback；
- cooldown / unhealthy deployment；
- 429 / 5xx；
- RPM / TPM；
- parallel requests；
- spend / cost。

# 13. HA

生产不允许单一 LiteLLM 容器成为新的关键单点。

目标：

```text
LB / service endpoint
→ LiteLLM replica 1
→ LiteLLM replica 2+
```

实际副本数由压测和 SLA 决定。

# 14. Version

- Docker image pin exact tested version；
- production 禁止依赖漂移标签作为唯一版本策略；
- config 与 image 版本一起审查；
- migration / rollback 路径进入 release checklist。

# 15. 禁止重复实现

```text
CustomCircuitBreaker
ProviderRouter
RetryBudgetManager
ProviderHealthManager
LLMCostCalculator
```

如果 LiteLLM 某个缺口真实存在，先 ADR，再做最小 adapter。
