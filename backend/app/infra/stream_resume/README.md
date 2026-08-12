# Stream Resume Infrastructure

This module implements **active HTTP/UI stream resumption only**.

## Ownership boundary

It owns:

- one active producer claim per `stream_id`
- cross-replica producer discovery via Redis Pub/Sub
- producer-memory replay buffer
- reconnect/replay of opaque string chunks
- transport states: `MISSING / ACTIVE / DONE / FAILED / INTERRUPTED`

It does **not** own:

- Product `RequestRun` lifecycle
- Conversation / Message persistence
- Auth/AuthZ / idempotency / quota
- Product cancellation
- PydanticAI cancellation tokens
- Vercel AI protocol encoding
- process-crash execution durability (future DBOS/Temporal concern)

## Identity

For Travel Agent, use:

```text
stream_id = str(request_id)
```

Do not introduce a second business `stream_id` column unless a future infrastructure
implementation genuinely requires it.

## Intended integration

```text
PydanticAI
  -> VercelAIAdapter.encode_stream()   # protocol owner
  -> AsyncIterator[str]
  -> RedisStreamResumeStore            # this module
  -> FastAPI StreamingResponse
  -> AI SDK useChat / ChatTransport
```

The Product layer must still gate terminal success until the durable assistant-message +
RequestRun completion transaction commits.

## Redis lifecycle

`RedisStreamResumeStore` receives the existing application Redis client. Calling
`store.close()` does **not** close that Redis client; it only closes this module's Pub/Sub
connection and in-process producer tasks.

## Example

```python
from app.infra.stream_resume import RedisStreamResumeStore

store = RedisStreamResumeStore(redis_client)

async def producer():
    # Later: yield strings from PydanticAI VercelAIAdapter.encode_stream(...)
    yield "data: ...\\n\\n"

stream = await store.start_or_resume(str(request_id), producer)
```

On browser reconnect, call `resume(str(request_id))`. For the first production version,
prefer replaying the current assistant stream from the beginning (`skip_characters=0`)
unless the AI SDK E2E spike proves a cursor/skip mechanism is necessary.
