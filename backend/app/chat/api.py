from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

from app.agent.agent import get_agent
from app.chat.protocol.adapter import (
    AgentEventAdapter,
    input_messages,
    protocol_message,
    run_completed,
    run_failed,
    run_interrupted,
    run_started,
    serialize_state,
)
from app.chat.protocol.run_registry import run_registry
from app.chat.protocol.schema import CommandRequest, StreamRequest
from app.chat.protocol.session import AgentStreamSession, get_stream_session
from app.core.deps import CurrentUser

router = APIRouter(prefix="/threads", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _session(current_user: CurrentUser, thread_id: str) -> AgentStreamSession:
    return get_stream_session(str(current_user.id), thread_id)


def _checkpoint_thread_id(owner_id: str, thread_id: str) -> str:
    """Return the internal LangGraph thread id scoped to one authenticated user."""
    return f"{owner_id}:{thread_id}"


def _config(owner_id: str, thread_id: str) -> dict[str, dict[str, str]]:
    return {
        "configurable": {
            "thread_id": _checkpoint_thread_id(owner_id, thread_id),
        }
    }


def _replay_cursor(request: StreamRequest) -> int | None:
    """Accept the explicit app cursor and the stock SDK `since` cursor."""
    if request.last_event_id is not None:
        return request.last_event_id
    return request.since


async def _run_agent(
    owner_id: str,
    thread_id: str,
    run_id: str,
    payload: dict[str, Any],
) -> None:
    session = get_stream_session(owner_id, thread_id)
    adapter = AgentEventAdapter()

    for event in run_started(run_id):
        await session.publish(protocol_message(event))

    try:
        async for event in get_agent().astream_events(
            {"messages": input_messages(payload.get("input"))},
            config=_config(owner_id, thread_id),
            version="v2",
        ):
            for protocol_event in adapter.adapt(event):
                await session.publish(protocol_message(protocol_event))
    except asyncio.CancelledError:
        # This reports transport-task cancellation to subscribers. It is not a
        # durable LangGraph interrupt and does not add resume semantics.
        await session.publish(protocol_message(run_interrupted(run_id)))
        raise
    except Exception as error:
        await session.publish(protocol_message(run_failed(run_id, error)))
        raise
    else:
        await session.publish(protocol_message(run_completed(run_id)))


@router.post("/{thread_id}/commands")
async def command(
    thread_id: str,
    command: CommandRequest,
    current_user: CurrentUser,
) -> dict[str, Any]:
    data = command.model_dump(exclude_none=True)

    if data.get("method") != "run.start":
        return {
            "type": "error",
            "id": command.id,
            "error": "unknown_command",
            "message": "unsupported command",
        }

    owner_id = str(current_user.id)
    run_id = str(uuid4())
    task = asyncio.create_task(
        _run_agent(owner_id, thread_id, run_id, data.get("params", {}))
    )
    run_registry.register(owner_id, run_id, task)
    task.add_done_callback(lambda _task: run_registry.remove(owner_id, run_id))

    return {
        "type": "success",
        "id": command.id,
        "result": {"run_id": run_id},
    }


@router.post("/{thread_id}/stream")
async def stream_events(
    thread_id: str,
    request: StreamRequest,
    current_user: CurrentUser,
) -> StreamingResponse:
    return StreamingResponse(
        _session(current_user, thread_id).subscribe(_replay_cursor(request)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/{thread_id}/state")
async def thread_state(thread_id: str, current_user: CurrentUser) -> dict[str, Any]:
    owner_id = str(current_user.id)
    snapshot = await get_agent().aget_state(_config(owner_id, thread_id))
    return serialize_state(snapshot, thread_id=thread_id)


@router.post("/{thread_id}/runs/{run_id}/cancel", status_code=204)
async def cancel_run(
    thread_id: str,
    run_id: str,
    current_user: CurrentUser,
    action: str = "interrupt",
) -> Response:
    # The public thread id scopes this HTTP route. Runtime lookup remains the
    # minimal authenticated-user + run-id transport registry requested here.
    _ = thread_id

    if action != "interrupt":
        raise HTTPException(status_code=400, detail="unsupported action")

    task = run_registry.get(str(current_user.id), run_id)
    if not task:
        raise HTTPException(status_code=404, detail="run not found")

    # Transport-level cancellation only. This cancels the process-local asyncio task.
    # It is not a durable LangGraph interrupt/resume operation.
    task.cancel()
    return Response(status_code=204)
