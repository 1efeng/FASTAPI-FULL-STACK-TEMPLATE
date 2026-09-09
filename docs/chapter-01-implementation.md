# Chapter 1 — Model Engineering 实现步骤

> 执行分支：`agent101-foundation`
>
> 本章目标：完成 **AI SDK UI → FastAPI → LangChain ChatModel → AI SDK UI Message Stream** 的可运行流式 Chat vertical slice。
>
> 本章不实现 Tool Calling、LangGraph Agent Loop、Checkpoint、HITL、MCP、Durable Runtime。

## 1. 本章最终链路

```text
React Chat UI
  ↓
@ai-sdk/react useChat
  ↓
DefaultChatTransport
  ↓ POST { id, messages, ... }
FastAPI /api/v1/chat/stream
  ↓
chat/protocol/messages.py
  ↓ AI SDK UIMessage[] → LangChain messages
chat/agent.py
  ↓
LangChain ChatModel.astream()
  ↓
chat/protocol/stream.py
  ↓ LangChain chunk → AI SDK UI Message Stream
SSE
  ↓
useChat / UIMessage.parts
```

核心原则：

> 前端保持 AI SDK 原生协议；Python 后端通过一个 feature-local `protocol/` 目录做适配。协议适配层不是 Agent Runtime。

---

## 2. Chapter 1 当前目录

```text
backend/app/chat/
├── __init__.py
├── api.py
├── schema.py
├── agent.py
├── protocol/
│   ├── __init__.py
│   ├── messages.py
│   └── stream.py
└── skills/
    └── travel-planning/
        └── SKILL.md
```

职责：

- `api.py`: FastAPI、JWT dependency、`StreamingResponse`
- `schema.py`: AI SDK transport 请求边界
- `agent.py`: ChatModel、server-owned system instructions、Travel Skill
- `protocol/messages.py`: `UIMessage[] → LangChain BaseMessage[]`
- `protocol/stream.py`: `AIMessageChunk → AI SDK UI Message Stream SSE`

不要新增：

```text
ChatService
AgentService
RuntimeFacade
ProviderRegistry
EventBus
StreamRuntime
```

---

# Stage 0 — 前端 AI SDK 基线

## Task 0.1 — AI SDK UI 基线

状态：**已完成**

前端已经使用：

```text
@ai-sdk/react useChat
DefaultChatTransport
UIMessage.parts
ChatStatus
useChat.stop()
```

并已删除自研：

```text
useChatStream.ts
custom SSE parser
custom ChatMessage store
```

仍需本地验证：

```bash
cd frontend
bun install
bun run build
```

---

## Task 0.2 — 请求协议保持 AI SDK 原生

状态：**已完成代码改造**

不再使用：

```json
{
  "thread_id": "...",
  "message": "..."
}
```

也不在前端用 `prepareSendMessagesRequest` 把 AI SDK 请求压成自定义协议。

FastAPI 直接接收 AI SDK transport 的：

```json
{
  "id": "chat-id",
  "messages": [
    {
      "role": "user",
      "parts": [{"type": "text", "text": "你好"}]
    }
  ],
  "trigger": "submit-message"
}
```

当前 Python schema 只声明真正需要的：

```python
class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]
```

额外 transport 字段由 Pydantic 忽略。

---

# Stage 1 — AI SDK ↔ LangChain 协议层

## Task 1.1 — `protocol/messages.py`

状态：**已完成第一章文本能力**

完整负责：

```text
AI SDK UIMessage[]
        ↓
LangChain BaseMessage[]
```

Chapter 1 支持：

- user text → `HumanMessage`
- assistant text history → `AIMessage`
- 多个 text part 合并
- 忽略当前章节未支持的 file/tool/reasoning part

产品 system instructions 由后端 `agent.py` 持有，不依赖浏览器决定。

进入 Tool 章节后，再参考成熟 FastAPI + LangGraph 社区实现扩展 tool history 的：

```text
AIMessage(tool_calls)
→ ToolMessage
→ AIMessage(text)
```

不要现在提前加入。

---

## Task 1.2 — `protocol/stream.py`

状态：**已完成第一章文本能力**

输出标准 AI SDK UI Message Stream：

```text
data: {"type":"start"}

data: {"type":"start-step"}

data: {"type":"text-start","id":"..."}

data: {"type":"text-delta","id":"...","delta":"你"}

data: {"type":"text-delta","id":"...","delta":"好"}

data: {"type":"text-end","id":"..."}

data: {"type":"finish-step"}

data: {"type":"finish"}

data: [DONE]
```

响应：

```text
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
x-vercel-ai-ui-message-stream: v1
```

LangChain 原始 chunk 不直接暴露给浏览器。

---

# Stage 2 — LangChain Model Boundary

## Task 2.1 — 最小依赖

状态：**代码已更新，等待本地 `uv sync` 验证**

新增：

```text
langchain
langchain-openai
```

不提前安装：

```text
langgraph-checkpoint-postgres
MCP
RAG packages
```

需要本地执行：

```bash
cd backend
uv sync
pytest
ruff check .
mypy app
```

---

## Task 2.2 — Provider 配置

状态：**已完成基础配置**

```text
LLM_MODEL
LLM_API_KEY
LLM_BASE_URL
```

其中：

```text
LangChain ChatOpenAI
+
LLM_BASE_URL
```

用于接 OpenAI-compatible provider。

不要在第一章增加 Model Gateway / LiteLLM / Provider Registry。

---

## Task 2.3 — `chat/agent.py`

状态：**已完成基础实现**

职责：

```text
Travel Skill
   ↓
SystemMessage
   ↓
ChatOpenAI
```

`api.py` 不直接初始化 Provider SDK。

第一章调用方式：

```text
ChatModel.astream(messages)
```

不要使用：

```text
create_agent
StateGraph
ToolNode
checkpointer
```

---

## Task 2.4 — FastAPI `/chat/stream`

状态：**已完成代码实现**

```text
POST /api/v1/chat/stream
```

链路：

```text
CurrentUser auth
   ↓
ChatRequest.messages
   ↓
ui_message_stream()
   ↓
StreamingResponse
```

浏览器请求 body 不允许决定受保护的 `user_id`。

---

# Stage 3 — Contract Tests

## Task 3.1 — Message adapter tests

状态：**已添加**

```text
backend/tests/chat/test_protocol_messages.py
```

验证：

- UI text history 转成 LangChain messages
- assistant 历史可回传给模型
- 非文本 part 在 Chapter 1 被安全忽略

---

## Task 3.2 — Stream adapter tests

状态：**已添加**

```text
backend/tests/chat/test_protocol_stream.py
```

使用 fake streaming model，不访问付费模型。

验证：

```text
start
start-step
text-start
text-delta
text-end
finish-step
finish
[DONE]
```

以及 provider exception → AI SDK `error` chunk。

---

# Stage 4 — Chapter 1 剩余工程化任务

下面这些还没有完成，按顺序继续。

## Task 4.1 — 本地构建与依赖锁验证

执行：

```bash
cd backend
uv sync
pytest tests/chat -q
ruff check app/chat tests/chat
mypy app

cd ../frontend
bun install
bun run build
```

完成标准：全部通过。

> 当前 ChatGPT 执行环境无法访问 GitHub 网络，因此不能把远端代码 clone 下来代替你的本地/CI 验证。

---

## Task 4.2 — 真实模型 E2E

在 `.env` 配置：

```text
LLM_MODEL=<model>
LLM_API_KEY=<key>
LLM_BASE_URL=<OpenAI-compatible base url, optional>
```

验证：

1. 登录。
2. 首页输入“你好”。
3. Network 看到 `POST /api/v1/chat/stream`。
4. request body 是 AI SDK `messages`。
5. response 为持续 SSE。
6. assistant 文本逐步出现。
7. status 最终回到 ready。

---

## Task 4.3 — Error Mapping

当前只有统一用户错误：

```text
模型调用失败，请稍后重试。
```

下一步至少区分：

```text
AUTH_ERROR
RATE_LIMIT
TIMEOUT
PROVIDER_ERROR
CANCELLED
UNKNOWN
```

原则：

- 原始异常写日志
- 用户只接收稳定文案
- 不泄露 API key / JWT / provider request body

---

## Task 4.4 — Stop / Cancellation

前端已经：

```text
useChat.stop()
```

需要真实 E2E 验证：

```text
Abort request
→ FastAPI async stream cancelled
→ model stream 不继续后台消费
```

本章不为 Stop 引入 Redis / run table / worker control channel。

---

## Task 4.5 — Latency / Usage Logging

每次 Chat 最少记录：

```text
user_id
model
first_token_latency_ms
total_latency_ms
input_tokens
output_tokens
status
error_type
```

usage 获取不到允许为空。

第一章不引入 LangSmith。

---

## Task 4.6 — Structured Output 示例

单独做一个小测试，例如：

```python
class TravelIntent(BaseModel):
    destination: str | None
    days: int | None
    budget: str | None
```

学习：

```text
natural language
→ LangChain structured output
→ Pydantic validation
```

不要把主 Chat 改成 JSON workflow。

---

# Chapter 1 完成标准

以下全部满足后再进入 Tool Calling：

- [ ] frontend build 通过
- [ ] backend `uv sync` 通过
- [ ] protocol tests 通过
- [ ] ruff / mypy 无本次新增错误
- [ ] AI SDK 原生 `UIMessage[]` 请求成功进入 FastAPI
- [ ] `protocol/messages.py` 成功转换 LangChain messages
- [ ] LangChain 真实模型流式返回
- [ ] `protocol/stream.py` 输出合法 AI SDK UI Message Stream
- [ ] Travel Skill 生效
- [ ] Provider error 有稳定映射
- [ ] Stop 能停止实际模型 stream
- [ ] latency / usage 基础日志可见
- [ ] structured output demo 有测试

到这里第一章才算完成。

面试表述：

> 前端我没有自己维护流式 Chat 状态机，而是使用 Vercel AI SDK `useChat`。Python 后端保持 LangChain/LangGraph 主线，通过 feature-local `protocol/messages.py` 和 `protocol/stream.py` 适配 AI SDK UI 协议。这样 UI 协议与 Agent Runtime 解耦：后续从普通 ChatModel 升级到 LangGraph Tool Agent 时，React 不需要重写通信层。
