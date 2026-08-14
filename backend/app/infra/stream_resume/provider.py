"""Stream-resume store provider.

Owns the process-scoped RedisStreamResumeStore singleton. The store uses the
application Redis client (from ``app.infra.redis``); closing the store never
closes that shared client (the store only tears down its own Pub/Sub connection
and producer tasks).
"""

from __future__ import annotations

from app.infra.redis import get_redis
from app.infra.stream_resume import RedisStreamResumeStore

_store: RedisStreamResumeStore | None = None


def get_stream_resume_store() -> RedisStreamResumeStore:
    global _store
    if _store is None:
        _store = RedisStreamResumeStore(get_redis())
    return _store


async def close_stream_resume_store() -> None:
    global _store
    if _store is not None:
        await _store.close()
        _store = None
