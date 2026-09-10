# Agent Streaming Architecture

## Current flow

```
React
 ↓
useStream
 ↓
HttpAgentServerAdapter
 ↓
FastAPI Protocol Adapter
 ↓
create_agent
 ↓
LangGraph
```

## Connection lifecycle

- Browser disconnect only removes the current subscription.
- A reconnect with the same threadId subscribes again and can replay buffered events.
- `stop` is different from disconnect: it requests cancellation of the active run.

## Current guarantees

The current implementation provides:

- process local active run tracking
- same process event replay buffer
- SSE reconnect support

The current implementation does not provide:

- worker crash recovery
- distributed durable execution
- multi worker coordination

These require a separate durable execution layer.
