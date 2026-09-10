"""HTTP protocol schemas for chat streaming.

Keep request/response contracts separate from agent execution.
"""

from pydantic import BaseModel


class StreamRequest(BaseModel):
    thread_id: str
    message: str
