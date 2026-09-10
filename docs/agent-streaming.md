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
- The frontend sends the authenticated cancel request explicitly, then calls
  `stream.stop({ cancel: false })`. The custom transport's authenticated fetch
  is not used by the SDK's separate runs client.

## Run policy

- One thread can have only one active run.
- A second submit while that run is active is rejected with
  `invalid_argument`; it is not queued or used to interrupt the first run.

## Current guarantees

The current implementation provides:

- process local active run tracking
- same process event replay buffer
- SSE reconnect support

The current implementation does not provide:

- worker crash recovery
- distributed durable execution
- multi worker coordination

Adding those guarantees is outside this process-local implementation.
