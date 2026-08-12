from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress

from ._backend import ResumeBackend
from .errors import StreamProducerFailed, StreamProducerInterrupted, StreamResumeTimeout
from .protocol import ChunkStream, StreamFactory, StreamState

logger = logging.getLogger(__name__)
_INTERNAL_VERSION = 1


def _encode(kind: str, **payload: object) -> str:
    return json.dumps(
        {"v": _INTERNAL_VERSION, "kind": kind, **payload},
        separators=(",", ":"),
    )


def _decode(message: str) -> dict[str, object]:
    raw = json.loads(message)
    if not isinstance(raw, dict) or raw.get("v") != _INTERNAL_VERSION:
        raise ValueError("Unsupported stream-resume internal message")
    return raw


class ResumableStreamRuntime:
    """Transport-resume runtime over an abstract coordination backend.

    The producer and its replay buffer stay in the producer Python process.
    Redis only coordinates discovery and cross-replica pub/sub. Therefore this
    solves HTTP/UI stream resumption, not process-crash execution durability.
    """

    def __init__(
        self,
        backend: ResumeBackend,
        *,
        key_prefix: str = "travel-agent:stream-resume",
        ttl_seconds: int = 3600,
        resume_ack_timeout_seconds: float = 2.0,
        heartbeat_interval_seconds: float | None = None,
        wait_until: Callable[[Awaitable[object]], None] | None = None,
    ) -> None:
        if ttl_seconds < 10:
            raise ValueError("ttl_seconds must be >= 10")
        if resume_ack_timeout_seconds <= 0:
            raise ValueError("resume_ack_timeout_seconds must be > 0")

        self._backend = backend
        self._key_prefix = key_prefix.rstrip(":")
        self._ttl_seconds = ttl_seconds
        self._resume_ack_timeout_seconds = resume_ack_timeout_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds or min(
            30.0, max(1.0, ttl_seconds / 3)
        )
        self._wait_until = wait_until
        self._producer_tasks: dict[str, asyncio.Task[None]] = {}
        self._closed = False

    def _state_key(self, stream_id: str) -> str:
        return f"{self._key_prefix}:state:{stream_id}"

    def _request_channel(self, stream_id: str) -> str:
        return f"{self._key_prefix}:request:{stream_id}"

    def _listener_channel(self, listener_id: str) -> str:
        return f"{self._key_prefix}:listener:{listener_id}"

    async def status(self, stream_id: str) -> StreamState:
        raw = await self._backend.get(self._state_key(stream_id))
        if raw is None:
            return StreamState.MISSING
        try:
            return StreamState(raw)
        except ValueError:
            logger.error("Unknown stream state %r for %s", raw, stream_id)
            return StreamState.INTERRUPTED

    async def start(
        self,
        stream_id: str,
        producer: StreamFactory,
    ) -> ChunkStream | None:
        self._ensure_open()
        await self._backend.ensure_ready()
        claimed = await self._backend.claim_active(
            self._state_key(stream_id), ttl_seconds=self._ttl_seconds
        )
        if not claimed:
            return None
        return await self._create_claimed_producer_stream(stream_id, producer)

    async def resume(
        self,
        stream_id: str,
        *,
        skip_characters: int = 0,
    ) -> ChunkStream | None:
        self._ensure_open()
        await self._backend.ensure_ready()
        return await self._resume_by_state(stream_id, skip_characters)

    async def start_or_resume(
        self,
        stream_id: str,
        producer: StreamFactory,
        *,
        skip_characters: int = 0,
    ) -> ChunkStream | None:
        self._ensure_open()
        await self._backend.ensure_ready()
        claimed = await self._backend.claim_active(
            self._state_key(stream_id), ttl_seconds=self._ttl_seconds
        )
        if claimed:
            return await self._create_claimed_producer_stream(stream_id, producer)
        return await self._resume_by_state(stream_id, skip_characters)

    async def _resume_by_state(
        self,
        stream_id: str,
        skip_characters: int,
    ) -> ChunkStream | None:
        state = await self.status(stream_id)
        if state in {StreamState.MISSING, StreamState.DONE}:
            return None
        if state is StreamState.FAILED:
            raise StreamProducerFailed(stream_id)
        if state is StreamState.INTERRUPTED:
            raise StreamProducerInterrupted(stream_id)
        return await self._open_consumer(
            stream_id,
            skip_characters=max(0, skip_characters),
        )

    async def _create_claimed_producer_stream(
        self,
        stream_id: str,
        producer: StreamFactory,
    ) -> ChunkStream:
        chunks: list[str] = []
        listeners: set[str] = set()
        gate = asyncio.Lock()
        request_channel = self._request_channel(stream_id)

        async def handle_request(message: str) -> None:
            try:
                request = _decode(message)
                kind = request.get("kind")
                listener_id = request.get("listener_id")
                if not isinstance(listener_id, str):
                    return

                if kind == "detach":
                    async with gate:
                        listeners.discard(listener_id)
                    return
                if kind != "attach":
                    return

                raw_skip = request.get("skip_characters")
                skip = raw_skip if isinstance(raw_skip, int) and raw_skip > 0 else 0
                async with gate:
                    listeners.add(listener_id)
                    backlog = "".join(chunks)[skip:]
                    # Empty data is still the ACK that proves the producer is alive.
                    await self._backend.publish(
                        self._listener_channel(listener_id),
                        _encode("data", data=backlog),
                    )
            except Exception:
                logger.exception("Failed to handle resume request for %s", stream_id)

        await self._backend.subscribe(request_channel, handle_request)

        # Attach the primary HTTP consumer before starting a potentially fast source.
        try:
            primary = await self._open_consumer(stream_id, skip_characters=0)
        except BaseException:
            await self._backend.unsubscribe(request_channel)
            await self._backend.set(
                self._state_key(stream_id),
                StreamState.INTERRUPTED.value,
                ttl_seconds=self._ttl_seconds,
            )
            raise

        task = asyncio.create_task(
            self._run_source(
                stream_id=stream_id,
                producer=producer,
                chunks=chunks,
                listeners=listeners,
                gate=gate,
                request_channel=request_channel,
            ),
            name=f"stream-resume:producer:{stream_id}",
        )
        self._producer_tasks[stream_id] = task
        task.add_done_callback(lambda _: self._producer_tasks.pop(stream_id, None))
        if self._wait_until is not None:
            self._wait_until(task)
        return primary

    async def _run_source(
        self,
        *,
        stream_id: str,
        producer: StreamFactory,
        chunks: list[str],
        listeners: set[str],
        gate: asyncio.Lock,
        request_channel: str,
    ) -> None:
        source: ChunkStream | None = None
        heartbeat = asyncio.create_task(
            self._heartbeat(stream_id),
            name=f"stream-resume:heartbeat:{stream_id}",
        )
        try:
            source = producer()
            async for chunk in source:
                if not isinstance(chunk, str):
                    raise TypeError(
                        "Stream resume producers must yield str, got "
                        f"{type(chunk).__name__}"
                    )
                async with gate:
                    chunks.append(chunk)
                    if listeners:
                        payload = _encode("data", data=chunk)
                        for listener_id in tuple(listeners):
                            await self._backend.publish(
                                self._listener_channel(listener_id), payload
                            )

            await self._stop_heartbeat(heartbeat)
            await self._backend.set(
                self._state_key(stream_id),
                StreamState.DONE.value,
                ttl_seconds=self._ttl_seconds,
            )
            async with gate:
                payload = _encode("done")
                for listener_id in tuple(listeners):
                    await self._backend.publish(
                        self._listener_channel(listener_id), payload
                    )

        except asyncio.CancelledError:
            await self._stop_heartbeat(heartbeat)
            await self._backend.set(
                self._state_key(stream_id),
                StreamState.INTERRUPTED.value,
                ttl_seconds=self._ttl_seconds,
            )
            async with gate:
                payload = _encode("interrupted")
                for listener_id in tuple(listeners):
                    await self._backend.publish(
                        self._listener_channel(listener_id), payload
                    )
            raise
        except Exception as exc:
            await self._stop_heartbeat(heartbeat)
            logger.exception("Producer failed for stream %s", stream_id)
            await self._backend.set(
                self._state_key(stream_id),
                StreamState.FAILED.value,
                ttl_seconds=self._ttl_seconds,
            )
            # Provider details/stack traces must never become transport payload.
            reason = type(exc).__name__
            async with gate:
                payload = _encode("failed", reason=reason)
                for listener_id in tuple(listeners):
                    await self._backend.publish(
                        self._listener_channel(listener_id), payload
                    )
        finally:
            if not heartbeat.done():
                await self._stop_heartbeat(heartbeat)
            if source is not None:
                aclose = getattr(source, "aclose", None)
                if aclose is not None:
                    with suppress(Exception):
                        await aclose()
            with suppress(Exception):
                await self._backend.unsubscribe(request_channel)

    async def _heartbeat(self, stream_id: str) -> None:
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval_seconds)
                await self._backend.expire(
                    self._state_key(stream_id), ttl_seconds=self._ttl_seconds
                )
        except asyncio.CancelledError:
            raise

    async def _stop_heartbeat(self, task: asyncio.Task[None]) -> None:
        if task.done():
            await asyncio.gather(task, return_exceptions=True)
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _open_consumer(
        self,
        stream_id: str,
        *,
        skip_characters: int,
    ) -> ChunkStream:
        listener_id = uuid.uuid4().hex
        listener_channel = self._listener_channel(listener_id)
        request_channel = self._request_channel(stream_id)
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        ack = asyncio.Event()

        async def handle_message(message: str) -> None:
            payload = _decode(message)
            await queue.put(payload)
            ack.set()

        await self._backend.subscribe(listener_channel, handle_message)
        try:
            await self._backend.publish(
                request_channel,
                _encode(
                    "attach",
                    listener_id=listener_id,
                    skip_characters=skip_characters,
                ),
            )
            try:
                await asyncio.wait_for(
                    ack.wait(), timeout=self._resume_ack_timeout_seconds
                )
            except TimeoutError as exc:
                raise StreamResumeTimeout(
                    stream_id, self._resume_ack_timeout_seconds
                ) from exc
        except BaseException:
            await self._backend.unsubscribe(listener_channel)
            raise

        async def generator() -> ChunkStream:
            try:
                while True:
                    payload = await queue.get()
                    kind = payload.get("kind")
                    if kind == "data":
                        data = payload.get("data")
                        if isinstance(data, str) and data:
                            yield data
                    elif kind == "done":
                        return
                    elif kind == "failed":
                        reason = payload.get("reason")
                        raise StreamProducerFailed(
                            stream_id,
                            reason if isinstance(reason, str) else None,
                        )
                    elif kind == "interrupted":
                        raise StreamProducerInterrupted(stream_id)
            finally:
                with suppress(Exception):
                    await self._backend.publish(
                        request_channel,
                        _encode("detach", listener_id=listener_id),
                    )
                with suppress(Exception):
                    await self._backend.unsubscribe(listener_channel)

        return generator()

    async def close(self, *, close_backend: bool = True) -> None:
        if self._closed:
            return
        self._closed = True
        tasks = tuple(self._producer_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._producer_tasks.clear()
        if close_backend:
            await self._backend.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("ResumableStreamRuntime is closed")
