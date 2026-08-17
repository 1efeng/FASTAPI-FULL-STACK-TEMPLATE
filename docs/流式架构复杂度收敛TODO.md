# 流式架构复杂度收敛 TODO

> 目的：删除没有实际收益、重复维护或仅为历史兼容留下的复杂度。
> 保留 Product 生命周期、F5 active stream resume、取消 CAS、deadline、幂等和 durable history。

## 一、明确保留的边界

- 浏览器协议唯一使用 Vercel AI UI protocol。
- `StreamResumeStore` 只负责 active stream 的 F5/断线重连。
- Product Runtime 负责 RequestRun、Conversation、Message、cancel、deadline、终态事务。
- Agent Runtime 只通过 `AgentExecutor` 执行。
- `finish` 必须在 assistant message 和 RequestRun completed 提交后发送。
- 不处理 producer 崩溃后的 execution durability。
- 不新增第二套浏览器事件协议。

## 二、前端收敛

- [x] 统一 API base URL：原生请求和 OpenAPI 请求不能使用不同的 API 地址来源。
- [x] 统一认证失败入口：删除 response interceptor，保留 QueryCache / MutationCache 单一处理。
- [x] 删除废弃的 `travel_agent_request_id`。
- [x] 删除 conversation localStorage，URL 作为唯一 conversation identity。
- [x] 集中清理 `requestIdRef` 和 active request storage。
- [x] 修复正常完成、取消、404、会话切换时的 active request 清理。
- [x] 将 active request storage 从 `use-product-chat.ts` 拆出为纯函数模块。
- [x] 将 conversation API 从 `use-product-chat.ts` 拆出。
- [x] 重连状态从多个 ref 收敛为一个明确 reconcile 状态，避免重复 resume。
- [x] 重连异常不再无条件静默吞掉。
- [x] 删除未使用的 Reasoning 泛化 API 和临时兼容逻辑。

## 三、后端收敛

- [x] 删除 `start_or_resume()` 后 API 层无意义的二次 `resume()`。
- [x] 消除 `prepare_turn()` 与 `chat()` 对 existing request 的重复 replay 查询。
- [x] 合并流终态决策、CAS 持久化和 terminal chunk 生成。
- [x] 拆分 `stream_factory()` 内部职责，不改变 ownership。
- [x] 集中 Vercel UI chunk 编码和解析，避免多个模块重复掌握 SSE 格式。
- [x] 明确 `stream_vercel_events` 是 UI protocol adapter，不伪装成 framework-neutral domain event。
- [x] 删除无调用方的 reasoning SSE wrapper。
- [x] 删除确认不再使用的 `/chat/stream/dispatch` spike endpoint。
- [x] 合并重复的 boolean request parsing。

## 四、测试与验收

- [ ] 正常首条消息仍能流式展示 reasoning、source、text。
- [ ] thinking 开关仍由 provider 原生参数控制。
- [ ] 401/403 只触发一次登录跳转。
- [ ] F5 只 resume 一次，204 能恢复 durable history。
- [ ] 正常完成后旧 request ID 不会被 cancel/reconnect 使用。
- [ ] cancel、deadline、provider error 均只产生一个 Product terminal。
- [ ] source 首次流式展示、F5 replay、刷新历史均一致。
- [ ] 运行后端相关测试、前端 TypeScript、Biome、production build。
- [ ] 条件允许时运行真实 Playwright E2E。

## 五、非目标

- 不改模型供应商和模型质量策略。
- 不引入自动大小模型路由。
- 不重写 `StreamResumeStore`。
- 不把 Redis 改成 execution durability。
- 不做无关 UI 重构。

## 六、执行记录

- 状态：第二批已完成，待全量验收
- 首次建立：2026-08-17
- 已完成：
  - 前端：删除废弃 request key、conversation localStorage、统一 API base URL、统一认证失败入口、集中 requestIdRef 清理、拆分 active-request-storage 与 conversation-api、重连异常兜底 durable history
  - 后端：删除二次 resume、消除重复 replay、合并流终态 helper、删除 reasoning SSE wrapper、删除 spike endpoint、合并 boolean parsing、拆分 stream_factory、集中 Vercel protocol primitives
  - 前端：reconcile refs 收敛为单一状态对象、Reasoning 泛化 API 精简
