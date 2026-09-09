# Frontend AGENTS.md

本文件补充根目录 `AGENTS.md`，仅约束 `frontend/`。

## 总体原则

保持当前 React + TypeScript + TanStack Router/Query + generated OpenAPI client 架构。

不要为了 Agent 功能引入新的前端架构体系。

当前项目不采用重型 Feature-Sliced / DDD 前端目录。

## 目录职责

优先保持：

```text
src/
├── client/       # OpenAPI 自动生成代码
├── components/   # 可复用 UI/业务组件
├── hooks/        # React hooks / client-side effects
├── lib/          # 纯工具与稳定 helper
├── routes/       # 页面与路由组件
└── main.tsx
```

规则：

- 页面放 `routes/`。
- 可复用 Chat UI 放 `components/Chat/`。
- 流式请求状态和副作用优先放 `hooks/useChatStream.ts`。
- 纯 SSE parser/helper 真有复用价值时再放 `lib/`。
- 不新增 `features/`、`entities/`、`widgets/`、`services/`、`stores/` 等目录，除非未来项目规模真实需要。

## Chat 第一阶段

保持最小结构即可：

```text
src/
├── components/
│   └── Chat/
│       ├── ChatMessage.tsx
│       └── ChatInput.tsx
├── hooks/
│   └── useChatStream.ts
└── routes/
    └── _layout/
        └── index.tsx
```

Tool / HITL 出现后再增加例如：

- `ToolActivity.tsx`
- `ApprovalCard.tsx`
- `AgentActivity.tsx`

不要提前创建空目录和占位组件。

## API 使用

普通 REST：继续使用 `src/client/` generated OpenAPI client。

Agent streaming：使用独立 `fetch + ReadableStream` / SSE parser。

不要修改 generated client 来硬塞 streaming 能力。

不要让 React UI 直接解析 LangChain/LangGraph 原始事件；只消费后端稳定的应用事件协议。

## State

第一阶段优先 React local state + hooks。

不要为了 Chat 提前引入：

- Redux
- Zustand
- event bus
- 自研全局 Agent store

只有状态确实跨多个页面、组件树和生命周期复杂到 local state/hook 难以维护时，再评估。

## Routes

TanStack Router 的 `routes/` 是页面入口，不把页面再套一层 feature page。

页面负责组合组件，不应承担完整 SSE parser、协议转换或复杂业务状态机。

## Auth

沿用当前认证方式，除非任务明确要求安全升级。

不要在 Agent 主线开发中顺手重构整套登录认证。

需要访问流式接口时，复用当前 access token 获取方式，并保证 401/403 行为与现有应用一致。

## UI

复用现有 Radix/shadcn 风格 `components/ui` 和 Sidebar。

优先把模板品牌替换成真实 Agent 产品，而不是重写 UI 基础设施。

不要重复创建已有 Button/Dialog/Sidebar/Toast 等基础组件。

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