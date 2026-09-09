# Chapter 1 — Model Engineering 实现步骤

> 执行分支：`agent101-foundation`
>
> 目标：完成第一个真正可运行、可演示、可面试讲解的 **LLM Streaming Chat vertical slice**。
>
> 本章只解决 **Model Engineering**。不提前实现 Tool Calling、Agent Loop、LangGraph Checkpoint、HITL、MCP、Durable Runtime。

---

## 1. 本章最终产物

完成后系统链路应为：

```text
React Chat UI
    ↓
@ai-sdk/react useChat
    ↓
DefaultChatTransport
    ↓ POST + SSE
FastAPI /api/v1/chat/stream
    ↓
LangChain ChatModel
    ↓
OpenAI-compatible LLM
```

并具备：

- 真正 token-by-token / chunk-by-chunk 流式输出
- JWT 登录态透传
- AI SDK UI Message Stream 协议
- Travel Skill 作为 system instructions
- Provider / Model 配置边界
- 基础错误映射
- latency / token usage / model 信息日志
- 用户 Stop / HTTP disconnect 取消
- structured output 示例
- 不依赖真实付费模型的核心测试

---

# Stage 0 — 固定前后端协议

## Task 0.1 — 验证前端 AI SDK Chat 基线

检查：

```text
frontend/package.json
frontend/src/components/Chat/ChatPage.tsx
frontend/src/components/Chat/ChatMessages.tsx
frontend/src/components/Chat/ChatComposer.tsx
```

确认：

- 使用 `@ai-sdk/react` 的 `useChat`
- 使用 `DefaultChatTransport`
- 使用 `UIMessage.parts`
- `stop()` 直接来自 `useChat`
- 不存在自研 `useChatStream.ts`
- 不存在第二套 Chat message store / stream parser

完成标准：

```bash
cd frontend
bun install
bun run build
```

通过。

预计：0.5h

---

## Task 0.2 — 固定请求体边界

AI SDK `DefaultChatTransport` 默认会发送完整：

```json
{
  "id": "chat-id",
  "messages": [],
  "trigger": "submit-message",
  "messageId": "..."
}
```

第一章后端不需要理解完整 AI SDK `UIMessage` schema。

在前端 `DefaultChatTransport` 使用 `prepareSendMessagesRequest`，转换成最小后端请求：

```json
{
  "thread_id": "chat-id",
  "message": "用户最新输入"
}
```

继续匹配：

```python
class ChatRequest(BaseModel):
    message: str
    thread_id: str | None
```

原则：

> AI SDK UIMessage 是前端 UI 数据结构，不直接成为 Python 业务 API schema。

完成标准：

- Browser Network 中 POST body 只有当前后端真实需要的数据
- `Authorization: Bearer <token>` 保持存在
- 后端不复制定义 AI SDK 完整 message schema

预计：0.5h

---

# Stage 1 — 先跑通 AI SDK ↔ FastAPI Streaming Protocol

## Task 1.1 — 实现最小 `/chat/stream`

修改：

```text
backend/app/chat/api.py
```

新增：

```text
POST /api/v1/chat/stream
```

先不要接 LLM，使用异步生成器输出固定文本：

```text
你好，这是流式响应。
```

响应头必须包含：

```text
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
x-vercel-ai-ui-message-stream: v1
X-Accel-Buffering: no
```

AI SDK UI Message Stream 最小序列：

```text
data: {"type":"start","messageId":"..."}

data: {"type":"text-start","id":"text-1"}

data: {"type":"text-delta","id":"text-1","delta":"你"}

data: {"type":"text-delta","id":"text-1","delta":"好"}

data: {"type":"text-end","id":"text-1"}

data: {"type":"finish","finishReason":"stop"}

data: [DONE]
```

注意每条 SSE 后保留空行。

完成标准：

- 前端 `useChat` 能显示 assistant message
- 文本是逐步出现而不是最后一次性出现
- Network 面板 response 为 streaming
- 不出现 AI SDK protocol parse error

预计：1h

---

## Task 1.2 — 抽出轻量 UI Message Stream helper

如果 `api.py` 开始出现重复 JSON + SSE 拼接，新增：

```text
backend/app/chat/events.py
```

仅负责：

```python
encode_ui_message_chunk(...)
encode_done()
```

不要创建：

```text
ProtocolManager
StreamRuntime
EventBus
MessageBroker
```

`events.py` 只是 **LangChain/Python event → AI SDK UI Message Stream chunk** 的适配层。

完成标准：

`api.py` 中看不到大量重复 `json.dumps + data:` 拼接。

预计：0.5h

---

## Task 1.3 — Streaming contract test

新增后端测试，至少验证：

- status 200
- `content-type` 为 event stream
- `x-vercel-ai-ui-message-stream: v1`
- 存在 `text-start`
- 存在 `text-delta`
- 存在 `text-end`
- 存在 `finish`
- 最后存在 `[DONE]`

此测试不调用真实模型。

预计：0.5h

---

# Stage 2 — 接入 LangChain ChatModel

## Task 2.1 — 安装最小 Agent 依赖

在 `backend/`：

```bash
uv add langchain langchain-openai
uv sync
```

第一章先不要为了未来能力额外安装一大批 LangGraph / MCP / RAG 包。

如果当前 LangChain 依赖自动带入 LangGraph，不等于本章需要使用 Graph API。

完成标准：

```bash
pytest
ruff check .
mypy app
```

现有质量门禁不因依赖升级破坏。

预计：0.5h

---

## Task 2.2 — 增加模型配置

修改：

```text
backend/app/core/config.py
```

只增加真实需要的配置，例如：

```text
LLM_BASE_URL
LLM_API_KEY
LLM_MODEL
LLM_TIMEOUT_SECONDS
```

如果当前使用 OpenAI-compatible 国内模型，仍通过 LangChain `ChatOpenAI` 的兼容接口接入。

不要创建自研：

```text
ProviderRegistry
ModelFactoryFramework
LLMGateway
ProviderAdapter hierarchy
```

Provider boundary 保持一个非常薄的初始化函数即可。

预计：0.5h

---

## Task 2.3 — 实现 `agent.py` 的 Model boundary

目标文件：

```text
backend/app/chat/agent.py
```

职责：

- 创建/获取 ChatModel
- 组合 system instructions
- 接受用户消息
- 提供 async streaming iterator

第一版形态保持简单：

```text
stream_chat(...)
    ↓
ChatModel.astream(...)
```

不要在本章使用：

```text
create_agent
StateGraph
ToolNode
checkpointer
```

因为本章目标是先把 **LLM 本身的调用链学明白**。

完成标准：

`api.py` 不直接初始化 `ChatOpenAI`。

预计：1h

---

## Task 2.4 — 把 LangChain chunk 转成 AI SDK chunk

链路：

```text
LangChain AIMessageChunk
        ↓
extract text delta
        ↓
AI SDK text-delta
        ↓
SSE
```

至少处理：

- 正常 text chunk
- 空 chunk
- model exception
- stream completion

第一章不需要支持：

- tool-input-* / tool-output-*
- approval
- reasoning
- source
- file

这些在真实需求出现后再增加。

完成标准：

浏览器真实调用 LLM，assistant 文本持续增量出现。

预计：1h

---

# Stage 3 — Travel Skill / Prompt Engineering

## Task 3.1 — 加载 Travel Skill

运行时 Skill 固定在：

```text
backend/app/chat/skills/travel-planning/SKILL.md
```

由 `agent.py` 加载。

不要使用：

```text
.agents/skills/
.claude/skills/
```

作为产品 Runtime Skill。

第一阶段 Travel Skill 只用于证明：

```text
system instructions
    +
user message
    ↓
model
```

能产生具有业务风格的回答。

预计：0.5h

---

## Task 3.2 — 明确 Prompt boundary

本章理解并能讲清：

```text
System Instructions
       ↓
Travel Skill
       ↓
User Input
       ↓
Model
```

不要做 Prompt SaaS / Prompt DB / Prompt version platform。

如果未来确实需要版本管理，再增加显式 `PROMPT_VERSION` 或文件版本即可。

完成标准：

- 普通问候可以正常回答
- 旅游规划请求明显遵循 Travel Skill 约束
- Skill 修改后无需修改 Agent Runtime 代码

预计：0.5h

---

# Stage 4 — Model Engineering Governance

## Task 4.1 — 错误映射

把 Provider / LangChain 异常映射到应用可理解的错误类别。

第一版至少区分：

```text
AUTH_ERROR
RATE_LIMIT
TIMEOUT
PROVIDER_ERROR
CANCELLED
UNKNOWN
```

不要把 provider 的完整原始异常、API key、request body 直接透传前端。

流已经开始后发生错误：

```text
AI SDK error chunk
→ finish / stream termination
```

流开始前错误：

返回正常 HTTP error response。

预计：1h

---

## Task 4.2 — Latency / Usage / Model 日志

每次请求至少记录：

```text
request_id / thread_id
user_id
model
started_at
first_token_latency（可以获得时）
total_latency
input_tokens（可以获得时）
output_tokens（可以获得时）
status
error_type
```

原则：

- 使用结构化日志
- 不打印 JWT
- 不打印 API key
- 默认不完整记录用户 prompt / model response
- usage 获取不到时允许为空，不为了 usage 造复杂 Runtime

完成标准：

完成一次 Chat 后，可以从后端日志解释：

> 调了哪个模型、多久首 token、多久完成、多少 token、是否成功。

预计：1h

---

## Task 4.3 — Client disconnect / Stop cancellation

前端：

```text
useChat.stop()
```

会取消当前 transport request。

后端需要确保：

```text
HTTP client disconnect
        ↓
cancel async generator / model stream
        ↓
不继续无意义消费模型输出
```

测试：

1. 发一个明显会长回答的问题
2. 流式输出过程中点击 Stop
3. UI 停止继续追加
4. 后端请求尽快结束
5. 日志标记 cancelled，而不是 provider error

不要为了本章 Stop 引入：

- Redis control channel
- run database
- worker event bus
- durable abort system

预计：1h

---

## Task 4.4 — Timeout

给模型调用配置合理 timeout。

必须理解：

```text
Model READ-like generation timeout
```

与后面章节的：

```text
Write Tool timeout → unknown outcome
```

不是同一个问题。

第一章只处理模型请求超时。

预计：0.5h

---

# Stage 5 — Structured Output

## Task 5.1 — 做一个独立 structured output 示例

不要把主 Chat 强行改成 JSON。

增加一个很小的演示/测试，例如：

```python
class TravelIntent(BaseModel):
    destination: str | None
    days: int | None
    budget: str | None
```

使用 LangChain 当前官方 structured output API 验证：

```text
自然语言
   ↓
Pydantic object
```

目的：掌握：

- schema
- validation
- model structured output
- parse failure

不是为了本章提前做 intent classifier workflow。

完成标准：

有自动化测试证明有效输入可以获得 Pydantic 结果，异常输出有明确处理。

预计：1h

---

# Stage 6 — Provider Boundary / Fallback 基础认知

## Task 6.1 — 保持 Provider 可替换，但不造平台

当前只需保证：

```text
LLM_BASE_URL
LLM_API_KEY
LLM_MODEL
```

变化时，Chat 业务代码基本不变。

可以验证两个 OpenAI-compatible model 配置，但不要实现动态模型控制台。

面试要能说明：

> LangChain 提供 Model abstraction；项目用配置隔离 Provider，业务层不依赖厂商 SDK。当前没有需求，所以没有再造 LiteLLM 或 Model Gateway。

预计：0.5h

---

## Task 6.2 — Retry / Fallback 只做最小策略

第一章理解即可：

- rate limit / transient provider failure 可以有限 retry
- invalid auth / bad request 不 retry
- timeout 是否 retry 必须考虑整体延迟预算
- fallback 必须明确模型能力/成本差异

若当前 LangChain 官方 retry 能力已经满足，直接使用官方能力。

不要实现通用 `RetryEngine`。

预计：0.5h

---

# Stage 7 — 测试与 E2E

## Task 7.1 — Model fake

测试中提供 fake streaming model，至少可以产生：

```text
你
好
，
世
界
```

核心 CI 不依赖真实 API key。

用于测试：

- LangChain chunk adapter
- AI SDK SSE protocol
- cancellation
- error mapping

预计：1h

---

## Task 7.2 — Backend integration tests

至少覆盖：

- 未登录访问 Chat → 401
- 空 message → 422
- 正常 fake model stream → 200 + AI SDK chunks
- model failure → 正确 error behavior
- disconnect/cancel 不产生服务器异常

预计：1h

---

## Task 7.3 — Playwright Chat E2E

至少覆盖：

```text
login
→ 打开 /
→ 输入消息
→ 点击发送
→ 用户消息出现
→ assistant 流式文本出现
→ 最终完成
```

再增加 Stop 测试：

```text
发送长回答
→ streaming
→ Stop
→ 不再继续追加
```

E2E 优先使用可控 fake/test model，不依赖公网 LLM。

预计：1.5h

---

# Stage 8 — 第一章收尾

## Task 8.1 — README / Architecture 更新

README 只需要说明第一章实际完成的架构：

```text
React
  ↓ AI SDK UI
FastAPI
  ↓ LangChain
LLM Provider
```

明确：

- AI SDK 仅负责前端 Chat UI/Transport
- LangChain 负责 Python model abstraction
- 尚未进入 Tool / Agent / LangGraph Runtime 阶段

预计：0.5h

---

## Task 8.2 — 第一章最终质量门禁

运行：

```bash
cd backend
uv sync
pytest
ruff check .
mypy app

cd ../frontend
bun install
bun run build
bunx playwright test
```

要求全部通过。

---

# 第一章完成定义（DoD）

只有下面全部满足，才进入 Chapter 2：

- [ ] 前端 `useChat + DefaultChatTransport` 正常工作
- [ ] FastAPI AI SDK UI Message Stream 协议测试通过
- [ ] 真实 LangChain ChatModel 能流式回答
- [ ] Travel Skill 已进入 system instructions
- [ ] JWT user context 已接入 Chat 请求
- [ ] Stop 能取消当前非 durable 流式请求
- [ ] provider error / timeout / cancellation 有清晰映射
- [ ] latency / model / usage 基础观测存在
- [ ] structured output 有独立可运行示例
- [ ] 核心测试不依赖真实付费 LLM
- [ ] backend lint/type/test 通过
- [ ] frontend build/E2E 通过

---

# 第一章明确不做

以下内容全部留到后续章节：

```text
❌ LangChain create_agent
❌ @tool / Tool Calling
❌ Tool Governance
❌ MCP
❌ HITL
❌ LangGraph StateGraph
❌ ToolNode
❌ Postgres Checkpointer
❌ interrupt / resume
❌ Durable Execution
❌ run / step tables
❌ Redis / Celery / Inngest / Temporal
❌ RAG / Vector DB
```

第一章只回答一个问题：

> **如何把一个 LLM 模型调用做成具备清晰 Provider 边界、流式传输、错误治理、可观测性、取消和测试能力的生产化 Chat Model Layer。**

完成后再进入 Chapter 2：Tool / Agent Engineering。
