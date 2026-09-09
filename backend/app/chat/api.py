from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.chat.protocol.stream import SSE_HEADERS, ui_message_stream
from app.chat.schema import ChatRequest
from app.core.deps import CurrentUser

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/stream")
async def stream_chat(request: ChatRequest, _: CurrentUser) -> StreamingResponse:
    """Stream one AI SDK chat turn through LangChain.

    Authentication stays in FastAPI. The frontend sends AI SDK `UIMessage[]`;
    the protocol package translates that request and the LangChain output.
    """
    return StreamingResponse(
        ui_message_stream(request.messages),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
