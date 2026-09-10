from typing import Any

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

from app.chat.protocol.session import get_thread_session
from app.core.deps import CurrentUser

router = APIRouter(prefix="/threads", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _session(current_user: CurrentUser, thread_id: str):
    return get_thread_session(str(current_user.id), thread_id)


@router.post("/{thread_id}/commands")
async def command(
    thread_id: str,
    command: dict[str, Any],
    current_user: CurrentUser,
) -> dict[str, Any]:
    """Handle Agent Streaming Protocol commands for one thread."""
    return await _session(current_user, thread_id).handle_command(command)


@router.post("/{thread_id}/stream")
async def stream_events(
    thread_id: str,
    request: dict[str, Any],
    current_user: CurrentUser,
) -> StreamingResponse:
    """Subscribe to buffered + live protocol events without owning the Run."""
    session = _session(current_user, thread_id)
    return StreamingResponse(
        session.event_stream(request),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/{thread_id}/state")
async def thread_state(
    thread_id: str,
    current_user: CurrentUser,
) -> dict[str, Any]:
    """Return process-local state used by HttpAgentServerAdapter hydration."""
    return _session(current_user, thread_id).state()


@router.post("/{thread_id}/runs/{run_id}/cancel", status_code=204)
async def cancel_run(
    thread_id: str,
    run_id: str,
    current_user: CurrentUser,
    wait: int = 0,
    action: str = "interrupt",
) -> Response:
    """Cancel the actual server-side Run; disconnecting SSE never calls this."""
    if action != "interrupt":
        raise HTTPException(status_code=400, detail="Only action=interrupt is supported")

    cancelled = await _session(current_user, thread_id).cancel_run(
        run_id,
        wait=bool(wait),
    )
    if not cancelled:
        raise HTTPException(status_code=404, detail="No active run with this id")
    return Response(status_code=204)
