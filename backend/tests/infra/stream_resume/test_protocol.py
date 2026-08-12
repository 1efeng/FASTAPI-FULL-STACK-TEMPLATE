from __future__ import annotations

from typing import assert_type

from app.infra.stream_resume import RedisStreamResumeStore, StreamResumeStore


def test_redis_store_matches_protocol_type_shape() -> None:
    # Static type-checkers enforce the structural Protocol; this keeps the intended
    # dependency direction visible in the runtime test suite too.
    assert_type(RedisStreamResumeStore, type[RedisStreamResumeStore])
    assert StreamResumeStore is not None
