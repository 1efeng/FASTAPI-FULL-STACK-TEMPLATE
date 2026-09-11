# Frontend AGENTS.md

本文件补充根目录 `AGENTS.md`，仅约束 `frontend/`。

## 总体原则

保持当前 React + TypeScript + TanStack Router/Query + generated OpenAPI client 架构。

Agent Chat 前端使用 **`@langchain/react`**（LangGraph 官方统一 React SDK），直接消费 Aegra v2 的 Agent Protocol：

- `StreamProvider` / `useStreamContext` / `HttpAgentServerAdapter`
- messages、thread state、streaming、interrupt/resume 均由 SDK 管理

不要为了 Agent 功能引入新的前端架构体系，也不要重建 `useChat`/DefaultChatTransport/自研 SSE parser。

当前不采用重型 Feature-Sliced / DDD 前端目录。

## 目录职责

优先保持：

```text
src/
├── client/       # OpenAPI 自动生成代码（普通 REST）
├── components/   # 可复用 UI/业务组件
├── hooks/        # 非 SDK 已覆盖的 React hooks / client effects
├── lib/          # 纯工具与稳定 helper
├── routes/       # 页面与路由组件
└── main.tsx
```

规则：

- 页面放 `routes/`。
- Chat UI 放 `components/Chat/`。
- 聊天状态、发送、stop、error、streaming、thread 恢复优先交给 `@langchain/react`（`useStreamContext`）。
- 不再维护自研 `useChatStream.ts` / `ChatMessage` / SSE parser。
- 不新增 `features/`、`entities/`、`widgets/`、`services/`、`stores/` 等目录，除非未来项目规模真实需要。

## Chat 当前结构

```text
src/components/Chat/
├── ChatPage.tsx          # StreamProvider + HttpAgentServerAdapter（Aegra v2 路径）
├── ChatMessages.tsx      # BaseMessage[] 渲染
├── ChatComposer.tsx      # 发送框（stream.isLoading 驱动）
├── ChatActivity.tsx      # 工具/思考进度展示
└── ChatThreadSidebar.tsx # 会话列表（当前静态）
```

Tool / HITL 出现后再增加 Tool/Approval UI；优先复用 LangGraph SDK 提供的事件/values 快照，不先自研第二套 message-part schema。

不要提前创建空目录和占位组件。

## API 使用

普通 REST：继续使用 `src/client/` generated OpenAPI client。

Agent Chat：

```text
Chat 页面
  ↓
StreamProvider / useStreamContext / HttpAgentServerAdapter（@langchain/react）
  ↓
Aegra v2（POST /threads/{id}/commands · POST /threads/{id}/stream/events · GET /threads/{id}/state）
```

关键接线（`ChatPage.tsx`）：

- `assistantId = "travel_planning"`（Aegra graph id，解析为确定性 UUID）。
- Aegra base URL 由 `VITE_AEGRA_URL` 提供，默认 `http://localhost:2026`。
- JWT 经 `authenticatedFetch` 透传（`Authorization: Bearer <access_token>`），Aegra 与 FastAPI 共用 `SECRET_KEY` 校验。
- thread_id 用 `sessionStorage` 持久化（`agent101.chat.threadId`），刷新复用同一 thread，由 Aegra 后台 run 继续执行。

不要修改 generated client 来硬塞 streaming 能力。

## 刷新 / 断线恢复

浏览器刷新 / SSE 断线重连的能力由 Aegra 后台 run + `@langchain/react` 的自动重连与 `since`/`event_id` 去重提供：

- 刷新不创建新 run：复用 `sessionStorage` 中的 thread_id，SDK 从 Aegra values 快照恢复消息。
- 切新对话时若正在执行，仅 `stream.disconnect()` 断开客户端连接，不取消服务端 run。
- 前端不需要自研「恢复状态机」；服务端执行生命周期（lease/reaper/drain）由 Aegra Runtime 负责。

## AI SDK 边界

`@ai-sdk/react` / `ai` 已从依赖移除，不参与 Agent Chat 协议。普通 REST 表单若仍使用相关类型，仅作为类型来源。

## State

优先 React local state + `@langchain/react` 的流状态。

不要为了 Chat 提前引入：

- Redux
- Zustand
- event bus
- 自研全局 Agent store
- 自研 chat stream state machine

只有状态确实跨多个页面、组件树和生命周期复杂到现有方式难以维护时，再评估。

## Routes

TanStack Router 的 `routes/` 是页面入口，不把页面再套一层 feature page。

页面负责组合组件，不承担底层 SSE parser 或 LangGraph 协议转换。

## Auth

沿用当前认证方式，除非任务明确要求安全升级。

不要在 Agent 主线开发中顺手重构整套登录认证。

Agent Chat 需要访问 Aegra 流式接口时，复用当前 access token 获取方式（`authenticatedFetch` 透传），并保证 401/403 行为与现有应用一致。

## UI

- assistant-ui：**当前未引入**。若未来引入，必须是明确的产品决策并同步更新根 `AGENTS.md`；不得为了“规范”同时维护两套 Chat 组件。
- shadcn/ui（`components/ui`）：通用 UI（Button、Dialog、Input、Select 等）的唯一组件来源。
- 后续 Tool、Approval、Reasoning 等复杂 message part 优先评估 LangGraph SDK / Aegra 提供的展示能力；需要哪个组件再按需加入，避免一次性复制整库。

## Testing

每次改动至少保证：

- TypeScript build 通过
- Biome/lint 不新增错误
- 受影响 Playwright 测试通过

新增 Chat 时优先覆盖：

- send message
- 刷新后同 thread 消息恢复
- tool activity rendering
- abort/disconnect（不取消服务端 run）
- error/reconnect UX（出现后）

`@langchain/react` / Aegra 协议变化较快，修改 transport / message 渲染前先对照当前安装版本与官方文档。
