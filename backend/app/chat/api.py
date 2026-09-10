from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from app.agent.agent import get_agent
from app.chat.protocol.adapter import input_messages, serialize_state
from app.chat.protocol.run_registry import run_registry
from app.chat.protocol.schema import CommandRequest, ResumeParams, RunStartParams, StreamRequest
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
    return f"{owner_id}:{thread_id}"


def _config(owner_id: str, thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": _checkpoint_thread_id(owner_id, thread_id)}}


def _replay_cursor(request: StreamRequest) -> int | None:
    return request.last_event_id if request.last_event_id is not None else request.since


async def _publish_stream(stream: Any, owner_id: str, thread_id: str) -> None:
    session = get_stream_session(owner_id, thread_id)
    async for event in stream:
        await session.publish(event)


async def _run_agent(owner_id: str, thread_id: str, params: RunStartParams) -> None:
    stream_options = params.stream.model_dump(exclude_none=True) if params.stream else {}
    stream = get_agent().astream_events(
        {"messages": input_messages(params.input)},
        config=_config(owner_id, thread_id),
        version="v3",
        **stream_options,
    )
    await _publish_stream(stream, owner_id, thread_id)


async def _resume_agent(owner_id: str, thread_id: str, value: Any) -> None:
    stream = get_agent().astream_events(
        Command(resume=value),
        config=_config(owner_id, thread_id),
        version="v3",
    )
    await _publish_stream(stream, owner_id, thread_id)


@router.post("/{thread_id}/commands")
async def command(thread_id: str, command: CommandRequest, current_user: CurrentUser) -> dict[str, Any]:
    data = command.model_dump(exclude_none=True)
    owner_id = str(current_user.id)

    existing_run_id = run_registry.find_command(owner_id, thread_id, command.id)
    if existing_run_id:
        return {"type": "success", "id": command.id, "result": {"run_id": existing_run_id}}

    if data.get("method") == "run.resume":
        params = ResumeParams.model_validate(data.get("params", {}))
        run_id = str(uuid4())
        task = asyncio.create_task(_resume_agent(owner_id, thread_id, params.value))
        run_registry.register(owner_id, thread_id, run_id, command.id, task)
        task.add_done_callback(lambda _: run_registry.remove(owner_id, run_id))
        return {"type": "success", "id": command.id, "result": {"run_id": run_id}}

    if data.get("method") != "run.start":
        return {"type": "error", "id": command.id, "error": "unknown_command"}

    run_id = str(uuid4())
    params = RunStartParams.model_validate(data.get("params", {}))
    task = asyncio.create_task(_run_agent(owner_id, thread_id, params))
    run_registry.register(owner_id, thread_id, run_id, command.id, task)
    task.add_done_callback(lambda _: run_registry.remove(owner_id, run_id))

    return {"type": "success", "id": command.id, "result": {"run_id": run_id}}


@router.post("/{thread_id}/stream")
async def stream_events(thread_id: str, request: StreamRequest, current_user: CurrentUser) -> StreamingResponse:
    return StreamingResponse(
        _session(current_user, thread_id).subscribe(_replay_cursor(request)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/{thread_id}/state")
async def thread_state(thread_id: str, current_user: CurrentUser) -> dict[str, Any]:
    snapshot = await get_agent().aget_state(_config(str(current_user.id), thread_id))
    return serialize_state(snapshot, thread_id=thread_id)


@router.post("/{thread_id}/runs/{run_id}/cancel", status_code=204)
async def cancel_run(thread_id: str, run_id: str, current_user: CurrentUser, action: str = "cancel") -> Response:
    _ = thread_id
    if action != "cancel":
        raise HTTPException(status_code=400, detail="unsupported action")

    cancelled = run_registry.cancel_transport(str(current_user.id), run_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="run not found")

    return Response(status_code=204)
