from __future__ import annotations


class StreamResumeError(RuntimeError):
    """Base error for the transport-resume infrastructure."""


class StreamResumeTimeout(StreamResumeError):
    """Redis says ACTIVE, but no producer acknowledged the resume request."""

    def __init__(self, stream_id: str, timeout_seconds: float) -> None:
        super().__init__(
            f"Timed out after {timeout_seconds:g}s waiting for active stream producer "
            f"{stream_id!r}."
        )
        self.stream_id = stream_id
        self.timeout_seconds = timeout_seconds


class StreamProducerFailed(StreamResumeError):
    """The producer failed before completing the transport stream."""

    def __init__(self, stream_id: str, reason: str | None = None) -> None:
        message = f"Producer for stream {stream_id!r} failed."
        if reason:
            message += f" Reason: {reason}"
        super().__init__(message)
        self.stream_id = stream_id
        self.reason = reason


class StreamProducerInterrupted(StreamResumeError):
    """The owning process/context shut down before the producer completed."""

    def __init__(self, stream_id: str) -> None:
        super().__init__(
            f"Producer for stream {stream_id!r} was interrupted before completion."
        )
        self.stream_id = stream_id
