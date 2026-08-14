from __future__ import annotations

from app.infra.stream_resume import RedisStreamResumeStore, StreamResumeStore


def _as_stream_resume_store(store: RedisStreamResumeStore) -> StreamResumeStore:
    """Make structural compatibility part of static type checking."""
    return store


def test_redis_store_matches_protocol_type_shape() -> None:
    # Static type-checkers enforce the structural Protocol; this keeps the intended
    # dependency direction visible in the runtime test suite too.
    assert _as_stream_resume_store is not None
    assert RedisStreamResumeStore is not None
    assert StreamResumeStore is not None
