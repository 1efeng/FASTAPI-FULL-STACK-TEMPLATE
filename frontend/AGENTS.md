# Frontend AGENTS.md

本文件补充根目录 `AGENTS.md`，仅约束 `frontend/`。

## 总体原则

保持当前 React + TypeScript + TanStack Router/Query + generated OpenAPI client 架构。

Chat 前端采用 Vercel AI SDK UI：

- `@ai-sdk/react` 的 `useChat`
- `ai` 的 `DefaultChatTransport`
- `UIMessage` / message parts / `ChatStatus`

不要为了 Agent 功能引入新的前端架构体系。

当前项目不采用重型 Feature-Sliced / DDD 前端目录。

## 目录职责

优先保持：

```text
src/
├── client/       # OpenAPI 自动生成代码
├── components/   # 可复用 UI/业务组件
├── hooks/        # 非 AI SDK 已覆盖的 React hooks / client effects
├── lib/          # 纯工具与稳定 helper
├── routes/       # 页面与路由组件
└── main.tsx
```

规则：

- 页面放 `routes/`。
- 可复用 Chat UI 放 `components/Chat/`。
- Chat 消息状态、发送、stop、error、streaming status 优先交给 AI SDK `useChat`。
- 不再维护自研 `useChatStream.ts` / `ChatMessage` / SSE parser。
- 不新增 `features/`、`entities/`、`widgets/`、`services/`、`stores/` 等目录，除非未来项目规模真实需要。

## Chat 第一阶段

保持最小结构：

```text
src/
├── components/
│   └── Chat/
│       ├── ChatPage.tsx
│       ├── ChatMessages.tsx
│       ├── ChatComposer.tsx
│       ├── ChatActivity.tsx
│       └── ChatThreadSidebar.tsx
└── routes/
    └── _layout/
        └── index.tsx
```

Tool / HITL 出现后再增加 Tool/Approval UI；优先复用 AI SDK `UIMessage.parts` 与 AI Elements，不先自研第二套 message-part schema。

不要提前创建空目录和占位组件。

## API 使用

普通 REST：继续使用 `src/client/` generated OpenAPI client。

Agent Chat：

```text
useChat
  ↓
DefaultChatTransport
  ↓
POST /api/v1/chat/stream
  ↓
AI SDK UI Message Stream over SSE
```

不要修改 generated client 来硬塞 streaming 能力。

认证 Header 通过 `DefaultChatTransport` 的动态 `headers` 获取当前 access token。

`useChat` 的 `id` 作为 chat/thread identity；后端按当前 AI SDK request contract 接收 `id + messages + trigger + messageId` 等字段，不再设计平行的前端消息协议。

前端不得直接解析 LangChain/LangGraph 原始事件；FastAPI 必须先转换为 AI SDK UI message stream chunks。

## AI SDK 边界

AI SDK 在本项目只负责：

- frontend chat transport
- UI message state
- streaming message parts
- stop / error / chat status
- tool / approval / data part 的 UI 协议

AI SDK 不负责后端 Agent orchestration，不引入 AI SDK Agent Runtime 替代 LangGraph。

后端唯一 Runtime 仍然是 LangChain/LangGraph。

## State

第一阶段优先 React local state + AI SDK `useChat`。

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

需要访问流式接口时，复用当前 access token 获取方式，并保证 401/403 行为与现有应用一致。

## UI

复用现有 Radix/shadcn 风格 `components/ui` 和已经迁移的 Mastra Chat 视觉/交互。

后续 Tool、Approval、Reasoning 等复杂 message part 优先评估 AI Elements 现成组件；不要一次性把整套 AI Elements 组件库复制进来。

需要哪个组件再按需加入哪个组件，避免把源项目的 Workspace、Artifact、Speech、Mastra Durable UI 一起迁入。

## Testing

每次改动至少保证：

- TypeScript build 通过
- Biome/lint 不新增错误
- 受影响 Playwright 测试通过

新增 Chat 时优先覆盖：

- send message
- streaming text
- abort/cancel
- tool activity rendering
- approval flow（出现后）
- error/reconnect UX（出现后）

AI SDK 相关 API 变化较快，修改 transport/message-parts 前先对照当前安装版本和官方文档。
