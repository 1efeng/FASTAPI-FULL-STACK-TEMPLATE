from pydantic import BaseModel


class Message(BaseModel):
    """Generic API message response."""

    message: str
