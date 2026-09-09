# Agent Engineering Platform — 实现步骤

> 执行分支：`agent101-foundation`
>
> 本文档是当前项目的**实现执行清单**。`docs/agent-engineering-roadmap.md` 继续负责解释为什么这样学、为什么这样选技术；本文档只回答：**下一步具体改什么、改哪些文件、做到什么算完成。**

## 0. 当前基线

当前目标架构：

```text
React + TypeScript
        ↓
@ai-sdk/react useChat
        ↓
DefaultChatTransport
        ↓ HTTP POST + SSE
FastAPI
        ↓
LangChain
        ↓
LangGraph
        ↓
PostgreSQL
```

当前已经完成：

- [x] FastAPI + SQLAlchemy Async + PostgreSQL 基础底座
- [x] JWT 登录和 `CurrentUser`
- [x] React + TanStack Router/Query
- [x] 从 Mastra 项目迁入 Chat 页面视觉和主要交互
- [x] `/` 作为全屏 Chat 页面
- [x] 前端使用 `@ai-sdk/react` 的 `useChat`
- [x] 前端使用 `DefaultChatTransport`
- [x] 消息展示切换到 AI SDK `UIMessage.parts`
- [x] Stop 使用 `useChat().stop()`
- [x] 删除自研 `useChatStream.ts`
- [x] 确定 LangGraph 是唯一 Agent Runtime
- [x] 确定 AI SDK 只负责前端 Chat 状态和传输协议，不负责 Python Agent Runtime

当前**尚未完成**：

- [ ] 前端新增 AI SDK 依赖后的 lockfile / build 实际验证
- [ ] AI SDK 请求体与当前 FastAPI `ChatRequest` 对齐
- [ ] FastAPI `/api/v1/chat/stream`
- [ ] AI SDK UI Message Stream 编码器
- [ ] LangChain Model 接入
- [ ] Tool Calling
- [ ] LangGraph Agent Loop
- [ ] Postgres Checkpointer
- [ ] HITL / interrupt / resume
- [ ] Tool Governance

---

# Stage 0 — 先把当前分支恢复到可验证状态

**目标：** 不接模型，先确保当前 UI 迁移代码能编译，并把 AI SDK 前后端协议边界锁死。

## Task 0.1 — 更新前端依赖并跑 Build

**预计：0.5–1 小时**

执行：

```bash
cd frontend
bun install
bun run build
bun run lint
```

检查：

- `ai`
- `@ai-sdk/react`
- lockfile 是否更新
- `DefaultChatTransport` 当前版本 API 是否与代码一致
- `ChatStatus` / `UIMessage` / `isToolUIPart` 是否类型通过

**产出物：**

- lockfile 更新
- TypeScript build 通过

**完成标准：**

```text
bun run build ✅
bun run lint  ✅
```

出现类型错误时只修 AI SDK 迁移相关问题，不顺手重构前端目录。

---

## Task 0.2 — 对齐 AI SDK 请求体

**预计：1 小时**

AI SDK `DefaultChatTransport` 默认 POST body 会包含：

```json
{
  "id": "chat-id",
  "messages": [],
  "trigger": "submit-message",
  "messageId": "..."
}
```

当前 Python `ChatRequest` 是：

```python
class ChatRequest(BaseModel):
    message: str
    thread_id: str | None
```

第一阶段不要在 Python 里完整复刻 AI SDK `UIMessage` schema。

在前端 `DefaultChatTransport` 使用 `prepareSendMessagesRequest`，把请求压缩成当前应用真正需要的最小格式：

```text
AI SDK useChat
    ↓
prepareSendMessagesRequest
    ↓
{
  thread_id,
  message
}
    ↓
FastAPI ChatRequest
```

建议行为：

- 从最后一条 user `UIMessage.parts` 中提取 text part
- `id` 映射为 `thread_id`
- 第一阶段仅接受普通文本消息
- attachment / tool approval 等以后真实出现时再扩展请求 schema

**修改文件：**

```text
frontend/src/components/Chat/ChatPage.tsx
backend/app/chat/schema.py   # 原则上无需大改
```

**完成标准：**

前端实际发送：

```json
{
  "thread_id": "...",
  "message": "你好"
}
```

FastAPI Pydantic 可以直接校验，无重复 UIMessage schema。

---

# Stage 1 — 跑通纯协议 Vertical Slice

**目标：** 先证明 `useChat → FastAPI → AI SDK UI Message Stream → UI` 完全通，再接真实 LLM。

这是整个项目最重要的第一条竖切。

## Task 1.1 — 实现 AI SDK UI Message Stream 编码器

**预计：1–2 小时**

新增：

```text
backend/app/chat/events.py
```

不要建立一个通用 Event Framework，只提供当前 Chat 所需的小函数，例如：

```python
encode_chunk(chunk: dict) -> str
text_stream(...)
error_chunk(...)
```

SSE 每个 chunk 使用：

```text
data: <JSON>\n\n
```

第一阶段最小消息序列：

```text
data: {"type":"start","messageId":"..."}

data: {"type":"text-start","id":"text-1"}

data: {"type":"text-delta","id":"text-1","delta":"你"}

data: {"type":"text-delta","id":"text-1","delta":"好"}

data: {"type":"text-end","id":"text-1"}

data: {"type":"finish","finishReason":"stop"}

data: [DONE]

```

响应 Headers 至少包含：

```text
Content-Type: text/event-stream
Cache-Control: no-cache
x-vercel-ai-ui-message-stream: v1
X-Accel-Buffering: no
```

> AI SDK `DefaultChatTransport` 当前会把响应当作 JSON SSE stream 解析，因此不要再输出旧的 `event: message.delta` 自定义协议。

**完成标准：**

给定字符串数组：

```python
["你", "好"]
```

编码器能产生符合 AI SDK UI Message Stream 的合法 SSE。

---

## Task 1.2 — 实现 Fake `/chat/stream`

**预计：1–2 小时**

修改：

```text
backend/app/chat/api.py
```

先不调用任何模型。

实现：

```text
POST /api/v1/chat/stream
```

输入：

```json
{
  "thread_id": "xxx",
  "message": "你好"
}
```

输出固定但真实流式的：

```text
你好，我已经收到你的消息。
```

每隔极短间隔或逐 chunk yield，验证浏览器确实逐步更新，而不是请求结束后一次性显示。

继续使用现有认证：

```text
Authorization Bearer Token
        ↓
CurrentUser
```

不要让请求 body 自带 `user_id`。

**完成标准：**

浏览器：

```text
输入：你好
      ↓
立即出现生成状态
      ↓
文字逐步出现
      ↓
status 回到 ready
```

Stop：

```text
生成中点击 Stop
→ 当前 fetch 被 AbortController 中断
→ UI 不再继续追加文本
```

此时才算前后端协议跑通。

---

## Task 1.3 — Stream Contract Test

**预计：1 小时**

新增后端测试：

```text
backend/tests/chat/test_stream.py
```

至少验证：

- 401 未登录不能调用
- 空 message 被 Pydantic 拒绝
- Content-Type 正确
- `x-vercel-ai-ui-message-stream=v1`
- 包含 `start`
- 包含 `text-start`
- 包含 `text-delta`
- 包含 `text-end`
- 包含 `finish`
- 最后包含 `[DONE]`

**完成标准：**

协议测试不依赖真实 LLM。

---

# Stage 2 — Chapter 1：LangChain Model Streaming

**目标：** 把 Fake Stream 换成真实 LangChain ChatModel，形成第一个可面试展示的 AI vertical slice。

## Task 2.1 — 添加最小 Agent 依赖

**预计：0.5–1 小时**

只增加当前需要的依赖：

```bash
cd backend
uv add langchain langchain-openai
uv sync
```

暂时不要因为未来 Chapter 3 顺手加入大量 Agent 生态包。

然后运行：

```bash
pytest
ruff check .
mypy app
```

Python 3.14 当前底座已经通过既有 CI；只有真实依赖冲突时再讨论 Python 版本，不预防性降级。

---

## Task 2.2 — 模型配置

**预计：1 小时**

修改：

```text
backend/app/core/config.py
.env.example
```

保持 OpenAI-compatible boundary，例如：

```text
LLM_API_KEY
LLM_BASE_URL
LLM_MODEL
```

不要引入：

- LiteLLM
- 自研 Provider Registry
- Model Gateway
- 多 Provider UI

第一阶段只需：

```text
settings
   ↓
ChatOpenAI(...)
```

后面真出现第二 Provider 再抽象。

---

## Task 2.3 — 实现 `chat/agent.py`

**预计：1–2 小时**

职责：

```text
加载 travel-planning Skill
        ↓
构造 ChatModel
        ↓
组合 system prompt + user message
        ↓
返回 async token stream
```

当前保持简单：

```text
backend/app/chat/
├── api.py
├── schema.py
├── agent.py
├── events.py
└── skills/
```

不要新增：

```text
ChatService
AgentService
LLMService
RuntimeFacade
ProviderManager
```

如果 `agent.py` 只有几十到一百多行，这是正常的。

---

## Task 2.4 — LangChain Stream → AI SDK Stream Adapter

**预计：2–3 小时**

主链：

```text
ChatModel.astream()
      ↓
AIMessageChunk
      ↓
提取 text delta
      ↓
events.py
      ↓
AI SDK UIMessageChunk
      ↓
FastAPI StreamingResponse
```

第一阶段只映射 text。

不要在这里提前处理：

- tool call
- reasoning
- approval
- source
- artifact

真实功能出现时再映射对应 UIMessageChunk。

**完成标准：**

真实模型：

```text
React useChat
→ FastAPI
→ LangChain model
→ token/chunk 流
→ AI SDK UI message stream
→ React UIMessage.parts
```

完全跑通。

---

## Task 2.5 — Cancellation / Error / Usage

**预计：2–3 小时**

补齐 Chapter 1 最有价值的工程部分。

### Cancellation

浏览器 `useChat.stop()`：

```text
AbortController
→ HTTP disconnect
→ FastAPI streaming task 收到取消
→ 停止继续消费模型 stream
```

需要确认取消不会被吞掉后继续在后台生成。

### Error Mapping

不要把 Provider 原始异常完整透给用户。

应用级分类即可：

```text
auth_error
rate_limit
provider_timeout
provider_unavailable
invalid_request
internal_error
```

日志保留真实异常；前端只显示稳定用户文案。

### Usage / latency

至少记录：

```text
model
latency_ms
input_tokens
output_tokens
status
user_id
thread_id
```

先结构化日志，不需要 LangSmith。

**完成标准：**

- 成功流式输出
- Stop 有效
- Provider 报错 UI 不崩
- 日志能看到 latency / usage

到这里 **Chapter 1 完成**。

---

# Stage 3 — Chapter 2：Tool Calling + Agent Harness

**目标：** 不自己造 Tool Runtime，使用 LangChain 的成熟能力，并加入应用层 Tool Governance。

## Task 3.1 — 添加第一个 READ Tool

**预计：2–3 小时**

先做一个低风险 Tool，例如：

```text
search_attractions
```

或：

```text
get_weather
```

使用：

```python
@tool
Pydantic / type hints
```

不要写：

```text
ToolRegistry
ToolExecutor
ToolSchemaParser
```

**完成标准：**

模型能决定：

```text
用户问题
→ Tool Call
→ Tool Result
→ 最终回答
```

---

## Task 3.2 — 使用 `create_agent`

**预计：2–3 小时**

把普通 Tool Calling 主线切换到 LangChain 当前官方 `create_agent`。

目标：

```text
FastAPI
 ↓
create_agent
 ↓
LangGraph-backed agent runtime
 ↓
Tool
```

这一阶段不要急着自己写 `StateGraph`。

先学会成熟 Agent Harness：

- tool selection
- tool execution
- ToolMessage feedback
- multi-step loop
- middleware

---

## Task 3.3 — Tool Stream 映射到 AI SDK UI

**预计：2–4 小时**

此时才扩展 `events.py`。

映射至少覆盖：

```text
Tool Call Start
→ tool-input-start

Tool args ready
→ tool-input-available

Tool result
→ tool-output-available

Tool failure
→ tool-output-error
```

前端继续只认 `UIMessage.parts`。

不要重新创造：

```text
tool.started
tool.completed
```

第二套协议。

`ChatActivity` 从 tool part 的 state 推导：

```text
input-streaming / input-available
→ 正在使用 xxx…

output-available
→ 正在整理结果…
```

---

## Task 3.4 — Tool Governance：READ Retry

**预计：2 小时**

使用官方 middleware / retry 能力处理 READ Tool 短暂失败。

原则：

```text
READ + transient
→ 可以 retry
```

例如：

- timeout
- 429
- temporary upstream 5xx

不要把 WRITE Tool 混入同一通用 retry 策略。

---

## Task 3.5 — 第一个 WRITE Tool

**预计：3–4 小时**

实现一个真实但可控的副作用，例如：

```text
save_travel_plan
```

执行顺序：

```text
trusted CurrentUser
      ↓
final authorization
      ↓
idempotency check
      ↓
side effect
      ↓
persist result
      ↓
audit
```

不要让 LLM 提供可信 `user_id`。

### 关键面试点

WRITE timeout：

```text
不能直接认为失败
        ↓
UNKNOWN outcome
        ↓
query / reconcile
```

这部分是 Agent101 比“只会 LangChain API”更有价值的内容。

---

# Stage 4 — Chapter 3：自己实现 LangGraph Agent Loop

**目标：** 理解 Runtime，不是创建第二套 Runtime。

## Task 4.1 — 最小 StateGraph

**预计：3–4 小时**

新增：

```text
backend/app/chat/graph.py
backend/app/chat/state.py
```

实现：

```text
START
  ↓
model_node
  ↓
should_continue
  ├─ ToolNode
  │    ↓
  │  model_node
  └─ END
```

自己写：

- State
- model node
- conditional routing
- termination decision

继续复用：

- `@tool`
- official `ToolNode`
- ToolMessage

不要自己重写 Tool Executor。

**完成标准：**

能向面试官画出并解释：

```text
为什么 Tool Call 不是 Tool Execution
为什么 Tool Result 要回填为 ToolMessage
为什么 Graph 会循环
什么时候 END
```

---

## Task 4.2 — Budget / Convergence

**预计：2–3 小时**

在 Graph State 中加入最小控制：

```text
step_count
max_steps
```

必要时再加入：

```text
repeated_action_count
last_action_signature
```

解决：

- 无限 Tool loop
- 重复调用相同 Tool
- Agent 不收敛

不要建立复杂 Budget Platform。

---

## Task 4.3 — Replan

**预计：3–4 小时**

只有前面 Agent Loop 已稳定，再加入：

```text
plan
 ↓
execute
 ↓
evaluate
 ├─ continue
 ├─ replan
 └─ finish
```

目标是证明你理解 Agent Runtime 的“状态 + 路由 + 决策”，不是追求一个巨大 Graph。

---

# Stage 5 — Persistence / HITL / Durable

## Task 5.1 — Postgres Checkpointer

**预计：2–4 小时**

接入 LangGraph 官方 Postgres saver。

架构：

```text
Application Data
SQLAlchemy AsyncSession
       ↓
asyncpg
       ↓
PostgreSQL

LangGraph State
AsyncPostgresSaver
       ↓
psycopg
       ↓
same PostgreSQL
```

禁止：

- 为 LangGraph checkpoint table 建 SQLAlchemy Model
- Alembic 重复管理 checkpoint tables
- 自己再设计 `chat_checkpoints`

**完成标准：**

进程重启后，同一个 `thread_id` 的 Graph 能从 checkpointer 恢复正确状态。

---

## Task 5.2 — HITL interrupt / resume

**预计：3–4 小时**

对 HIGH-RISK Tool 增加审批：

```text
Agent wants tool
     ↓
interrupt
     ↓
FastAPI stream
     ↓
AI SDK tool-approval-request
     ↓
Approval UI
     ↓
approve / reject
     ↓
Command(resume)
```

前端到这一步再增加 `ApprovalCard`。

不要提前造通用 Approval Engine。

---

## Task 5.3 — Crash / Resume Test

**预计：2–4 小时**

必须验证：

```text
Graph 执行中断
→ Worker / process 重启
→ 使用相同 thread_id
→ 从 checkpoint 继续
```

重点检查：

- 已完成副作用不会被错误重复执行
- pending approval 不丢失
- messages 不重复

---

# Stage 6 — Durable Governance

只有前面的真实恢复场景跑通后做。

## Task 6.1 — Idempotency

**预计：2–3 小时**

针对 WRITE Tool 提取最小公共能力：

```text
chat/governance/idempotency.py
```

前提是至少两个 Tool 已出现重复逻辑；只有一个 Tool 时可以先留在 Tool 内部。

---

## Task 6.2 — Unknown Outcome + Reconciliation

**预计：3–4 小时**

实现一个可演示案例：

```text
调用外部写操作
     ↓
客户端/上游 timeout
     ↓
状态 UNKNOWN
     ↓
通过业务查询接口确认结果
     ↓
SUCCEEDED / FAILED
```

这是项目最有含金量的生产工程点之一。

---

## Task 6.3 — Audit

**预计：2–3 小时**

优先使用 LangChain middleware / ToolRuntime 扩展点。

记录：

```text
tool_name
user_id
thread_id
run_id（框架可取时）
tool_call_id
started_at
duration_ms
status
error_type
```

不要默认完整记录敏感 tool args。

Audit 写入失败不应把一个已经成功完成的外部副作用强行变成“Tool failed”。

---

# Stage 7 — 会话产品能力

**不是 Agent Runtime 前置条件。**

只有前面 Chat/Graph 主线完成后再做。

## Task 7.1 — Thread Metadata

需要产品级会话列表时，再增加 SQLAlchemy 数据：

```text
ChatThread
- id
- user_id
- title
- created_at
- updated_at
```

用途：

- 左侧会话列表
- owner 校验
- 标题
- 搜索
- 归档

不要因为 LangGraph 已经保存 messages 就把整个 Graph state 再复制一套到 application DB。

---

## Task 7.2 — Thread Sidebar 接真实数据

当前迁移过来的 Sidebar 是 UI shell。

到这里再接：

```text
GET /chat/threads
GET /chat/threads/{id}
DELETE /chat/threads/{id}
```

普通 CRUD 继续走 generated OpenAPI client。

Chat streaming 继续走 AI SDK Transport。

---

# Stage 8 — 最终 E2E / 面试交付

## Task 8.1 — E2E

**预计：3–4 小时**

至少覆盖：

```text
登录
→ 新建对话
→ 输入问题
→ 流式文字
→ Tool 调用
→ Tool 结果
→ 最终回复
→ Stop
→ 新建会话
```

HITL 完成后增加：

```text
high-risk tool
→ approval card
→ approve
→ resume
```

---

## Task 8.2 — Recovery E2E

**预计：2–4 小时**

演示：

```text
开始 Agent Run
→ interrupt / kill worker
→ restart
→ resume
→ 不重复副作用
```

这是 Chapter 3 durable 部分最终应该留下的可观察成果。

---

## Task 8.3 — README / Architecture

**预计：2 小时**

最终 README 必须能回答：

1. 项目解决什么问题？
2. 为什么前端选择 AI SDK UI？
3. 为什么后端选择 FastAPI + LangChain + LangGraph？
4. 为什么 LangGraph 是唯一 Runtime？
5. Tool Runtime 与 Tool Governance 有什么区别？
6. 为什么 WRITE timeout 不能盲目 retry？
7. Checkpoint 和业务数据库分别保存什么？
8. Stop / interrupt / resume 怎么工作？

---

# 推荐提交顺序

不要做一个“大爆炸 PR”。按能力提交：

```text
1. ✅ Migrate Chat UI to AI SDK
2.    Add AI SDK stream contract
3.    Add LangChain model streaming
4.    Add chat cancellation and error mapping
5.    Add LangChain tool calling
6.    Add tool governance
7.    Add LangGraph agent loop
8.    Add Postgres checkpointing
9.    Add HITL approval and resume
10.   Add recovery and reconciliation tests
```

每个 commit 都应该是一个可以解释的能力边界。

---

# 当前明确 Skip

在上面主线完成前，不做：

```text
Redis
Celery
Kafka
Temporal
Inngest
Kubernetes
LiteLLM
LangSmith
RAG / Vector DB
MCP Platform
自研 Tool Runtime
自研 Durable Runtime
自研 Checkpoint
双 Runtime
双 Agent State Source of Truth
复杂 Conversation/Run/Step 数据库宇宙
```

MCP 只有 Chapter 2 核心 Tool 流程已经稳定，且需要演示外部工具协议时再加一个最小示例。

---

# 执行优先级

如果面试准备时间紧，只完成以下主线：

```text
P0
Stage 0  当前代码 build
Stage 1  AI SDK ↔ FastAPI stream
Stage 2  LangChain Model
Stage 3  Tool Calling + Governance
Stage 4  LangGraph Agent Loop
Stage 5  Postgres Checkpointer + HITL

P1
Stage 6  Unknown Outcome / Reconciliation
Stage 8  E2E + README

P2
Stage 7  完整 Thread 产品能力
MCP
更复杂 UI
```

最小可面试版本不是“做完所有功能”，而是这条链真正跑通：

```text
React / AI SDK
      ↓
FastAPI Streaming
      ↓
LangChain Tool Agent
      ↓
LangGraph Runtime
      ↓
Postgres Checkpointer
      ↓
HITL + Governance
```

---

# 每个阶段的统一完成标准

每一个 Stage 都必须满足：

```text
代码可运行
+ 有可见 UI / API 结果
+ 有最小测试
+ lint/type-check 不新增错误
+ 没有增加第二套 Runtime / State
+ 能用 2~3 分钟讲清楚为什么这么设计
```

**不要用“看完课程”“学习了多少小时”作为进度。只认仓库里可运行、可测试、可演示的产出物。**
