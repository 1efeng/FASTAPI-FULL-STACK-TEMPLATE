# Frontend AGENTS.md

本文件补充根目录 `AGENTS.md`，仅约束 `frontend/`。

## 总体原则

保持当前 React + TypeScript + TanStack Router/Query + generated OpenAPI client 架构。

Chat 前端统一采用：

- **assistant-ui**：Chat UI 的唯一组件来源（styled elements + primitives）。
- **@langchain/react `useStream`**：Agent Runtime 连接的唯一方式（底层为 `@langchain/langgraph-sdk`）。
- **shadcn/ui**：仅用于通用 UI 组件。

网络协议是 **LangGraph Agent Streaming Protocol over SSE**，主链路为：

```text
assistant-ui → useStream → LangGraph SSE → FastAPI/LangGraph
```

详细链路与根目录 `AGENTS.md` 的“前后端 Chat 协议”一致：

```text
assistant-ui Thread / ThreadList（styled elements）
  ↓
useLangGraphRuntime（@assistant-ui/react-langgraph）
  ↓
useStream（@langchain/react，基于 @langchain/langgraph-sdk）
  ↓
HTTP POST + LangGraph Agent Streaming Protocol over SSE
  ↓
FastAPI + LangGraph（backend/app/chat/protocol/）
```

不要为了 Agent 功能引入新的前端架构体系。

当前项目不采用重型 Feature-Sliced / DDD 前端目录。

## 目录职责

优先保持：

```text
src/
├── client/                 # OpenAPI 自动生成代码
├── components/
│   ├── assistant-ui/
│   │   └── elements/       # assistant-ui CLI 安装的 styled elements
│   └── Chat/               # 页面级 Chat 组装（assistant-ui 之上）
├── hooks/                  # 非 useStream 已覆盖的 React hooks / client effects
├── lib/                    # 纯工具与稳定 helper
├── routes/                 # 页面与路由组件
└── main.tsx
```

规则：

- 页面放 `routes/`。
- Chat 组件一律来自 assistant-ui：Thread、ThreadList 等用 `npx assistant-ui@latest add thread thread-list` 安装到 `components/assistant-ui/elements/`，定制走 assistant-ui primitives。
- Chat 消息状态、发送、stop、error、streaming status 由 `useStream` + assistant-ui runtime 负责，不再维护自研流式消息 hook / `ChatMessage` / SSE parser。
- 不新增 `features/`、`entities/`、`widgets/`、`services/`、`stores/` 等目录，除非未来项目规模真实需要。

## Chat UI 结构

保持最小结构：

```text
src/
├── components/
│   ├── assistant-ui/
│   │   └── elements/       # assistant-ui CLI 安装（thread、thread-list 等）
│   └── Chat/
│       └── ChatPage.tsx    # 组装 assistant-ui elements / primitives
└── routes/
    └── _layout/
        └── index.tsx
```

规则：

- 不要手写 `ChatMessages` / `ChatComposer` / `ChatThreadSidebar` 等平行组件；Thread / Composer / ThreadList 由 assistant-ui elements 提供，需要定制时用 `ThreadPrimitive` / `ComposerPrimitive` / `MessagePrimitive` 等 primitives。
- Tool / approval / reasoning 等复杂 message part 使用 assistant-ui 官方能力（tool UI / generative UI 等），出现需求再按需安装对应 element。
- 不要提前创建空目录和占位组件。

## API 使用

普通 REST：继续使用 `src/client/` generated OpenAPI client。

Agent Chat：

```text
assistant-ui Thread
  ↓
useStream + HttpAgentServerAdapter（@langchain/react）
  ↓
POST /threads/{thread_id}/stream（LangGraph Agent Streaming Protocol over SSE）
  ↓
FastAPI + LangGraph
```

- 不要修改 generated client 来硬塞 streaming 能力。
- 认证 Header 通过 useStream / adapter 请求配置动态获取当前 access token，401/403 行为与现有应用一致。
- thread_id 作为 LangGraph thread identity（后端按 owner 隔离），不设计平行的前端消息协议。
- 前端不手写 LangGraph SSE parser；FastAPI 边界（`backend/app/chat/protocol/`）负责把 LangGraph 事件转成 LangGraph 兼容 SSE，`useStream` 直接消费。

## Chat 边界

本仓库的 Chat 前端职责划分：

- **assistant-ui**：唯一 Chat UI 组件来源。elements 管样式与结构，primitives 管定制；不引入其他 Chat UI 组件库，不手写平行 Chat 组件。
- **@langchain/react `useStream`**：唯一 Agent Runtime 连接方式。它管理 messages、thread state、streaming、interrupt/resume；前端不实现第二套 Agent Runtime。
- **shadcn/ui**：只负责通用 UI（Button、Dialog、Input、Select 等）。assistant-ui elements 内建在 shadcn/ui 约定上，项目的非 Chat 组件统一用 shadcn/ui。
- **网络协议**：LangGraph Agent Streaming Protocol over SSE。

禁止：

- 自研 SSE parser、平行 Chat Runtime、第二套消息状态机。
- 引入与 LangGraph Agent Streaming Protocol 平行或替代的前端流式协议/传输层，不使用旧版前端聊天传输方案。

## State

第一阶段优先 `useStream`（LangGraph SDK React）+ assistant-ui runtime 管理 Chat / thread state，UI 局部状态用 React local state。

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

Chat UI 复用 assistant-ui styled elements（`components/assistant-ui/elements/`），样式定制基于 shadcn/ui 约定；需要哪个组件用 `npx assistant-ui@latest add <item>` 按需安装，不要一次性整套复制。

后续 Tool、Approval、Reasoning 等复杂 message part 优先评估 assistant-ui 官方组件；不需要时不要把源项目的 Workspace、Artifact、Speech、Mastra Durable UI 组件一起迁入。

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

assistant-ui / LangGraph SDK API 变化较快，修改 transport/message-parts 前先对照当前安装版本和官方文档。
