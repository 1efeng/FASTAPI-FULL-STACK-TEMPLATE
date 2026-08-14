from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from typing import Literal

from ._backend import ResumeBackend
from .errors import StreamProducerFailed, StreamProducerInterrupted, StreamResumeTimeout
from .protocol import ChunkStream, StreamFactory, StreamState

logger = logging.getLogger(__name__)
_INTERNAL_VERSION = 1
type _NextOutcome = Literal["chunk", "end", "fenced"]


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

    Producer fencing (P0-1): a producer holds a renewable lease identified by a
    ``producer_token``. State and lease are separate keys, so losing the lease
    fences the producer (stops publishing and terminal writes) without letting it
    overwrite a new owner's state.
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
        self._lease_backend = backend
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

    def _lease_key(self, stream_id: str) -> str:
        return f"{self._key_prefix}:lease:{stream_id}"

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
        await self._lease_backend.ensure_ready()
        token = uuid.uuid4().hex
        claimed = await self._lease_backend.claim_lease(
            self._lease_key(stream_id),
            self._state_key(stream_id),
            token,
            ttl_seconds=self._ttl_seconds,
        )
        if not claimed:
            return None
        return await self._create_claimed_producer_stream(
            stream_id, producer, token
        )

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
        await self._lease_backend.ensure_ready()
        token = uuid.uuid4().hex
        claimed = await self._lease_backend.claim_lease(
            self._lease_key(stream_id),
            self._state_key(stream_id),
            token,
            ttl_seconds=self._ttl_seconds,
        )
        if claimed:
            return await self._create_claimed_producer_stream(
                stream_id, producer, token
            )
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
        token: str,
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

                # A request channel can briefly have handlers from both the stale
                # and replacement producer during lease takeover. Only the current
                # token owner may ACK/replay; otherwise the new subscriber could
                # receive stale backlog before the replacement owner's response.
                still_owner = await self._lease_backend.renew_lease(
                    self._lease_key(stream_id),
                    self._state_key(stream_id),
                    token,
                    ttl_seconds=self._ttl_seconds,
                )
                if not still_owner:
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

        # Record ACTIVE atomically under the lease token so a producer that lost
        # ownership during setup cannot overwrite a replacement owner.
        active = await self._lease_backend.set_state_if_lease_owner(
            self._lease_key(stream_id),
            self._state_key(stream_id),
            token,
            StreamState.ACTIVE.value,
            ttl_seconds=self._ttl_seconds,
        )
        if not active:
            await self._lease_backend.release_lease(
                self._lease_key(stream_id), token
            )
            raise StreamProducerInterrupted(stream_id)

        try:
            await self._backend.subscribe(request_channel, handle_request)
            # Attach the primary HTTP consumer before starting a potentially fast
            # source so no initial chunks can be lost.
            primary = await self._open_consumer(stream_id, skip_characters=0)
        except BaseException:
            with suppress(Exception):
                await self._backend.unsubscribe(request_channel)
            await self._write_terminal(stream_id, StreamState.INTERRUPTED, token)
            await self._lease_backend.release_lease(
                self._lease_key(stream_id), token
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
                token=token,
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
        token: str,
    ) -> None:
        source: ChunkStream | None = None
        fenced = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(stream_id, token, fenced),
            name=f"stream-resume:heartbeat:{stream_id}",
        )
        try:
            source = producer()
            while True:
                outcome, chunk = await self._next_chunk_or_fenced(
                    source, fenced
                )
                if outcome == "fenced":
                    await self._notify_interrupted(listeners, gate)
                    return
                if outcome == "end":
                    break
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
            if fenced.is_set():
                await self._notify_interrupted(listeners, gate)
                return
            wrote_terminal = await self._write_terminal(
                stream_id, StreamState.DONE, token
            )
            if wrote_terminal:
                async with gate:
                    payload = _encode("done")
                    for listener_id in tuple(listeners):
                        await self._backend.publish(
                            self._listener_channel(listener_id), payload
                        )
            else:
                await self._notify_interrupted(listeners, gate)

        except asyncio.CancelledError:
            await self._stop_heartbeat(heartbeat)
            if not fenced.is_set():
                await self._write_terminal(
                    stream_id, StreamState.INTERRUPTED, token
                )
            await self._notify_interrupted(listeners, gate)
            raise
        except Exception as exc:
            await self._stop_heartbeat(heartbeat)
            if not fenced.is_set():
                logger.exception("Producer failed for stream %s", stream_id)
                wrote_terminal = await self._write_terminal(
                    stream_id, StreamState.FAILED, token
                )
                if wrote_terminal:
                    # Provider details/stack traces must never become payload.
                    reason = type(exc).__name__
                    async with gate:
                        payload = _encode("failed", reason=reason)
                        for listener_id in tuple(listeners):
                            await self._backend.publish(
                                self._listener_channel(listener_id), payload
                            )
                else:
                    await self._notify_interrupted(listeners, gate)
            else:
                await self._notify_interrupted(listeners, gate)
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
            with suppress(Exception):
                await self._lease_backend.release_lease(
                    self._lease_key(stream_id), token
                )

    async def _next_chunk_or_fenced(
        self,
        source: AsyncIterator[str],
        fenced: asyncio.Event,
    ) -> tuple[_NextOutcome, str | None]:
        """Race the producer's next chunk against loss of lease ownership."""

        async def read_next() -> tuple[_NextOutcome, str | None]:
            try:
                return "chunk", await anext(source)
            except StopAsyncIteration:
                return "end", None

        async def wait_for_fence() -> tuple[_NextOutcome, str | None]:
            await fenced.wait()
            return "fenced", None

        next_chunk = asyncio.create_task(read_next())
        lease_lost = asyncio.create_task(wait_for_fence())
        try:
            done, _ = await asyncio.wait(
                {next_chunk, lease_lost},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if lease_lost in done:
                next_chunk.cancel()
                await asyncio.gather(next_chunk, return_exceptions=True)
                return lease_lost.result()

            lease_lost.cancel()
            await asyncio.gather(lease_lost, return_exceptions=True)
            return next_chunk.result()
        finally:
            for task in (next_chunk, lease_lost):
                if not task.done():
                    task.cancel()
            await asyncio.gather(next_chunk, lease_lost, return_exceptions=True)

    async def _write_terminal(
        self, stream_id: str, state: StreamState, token: str
    ) -> bool:
        """Atomically write state only if this producer still owns the lease.

        The ownership check and state write are one backend operation; a stale
        producer cannot pass a check and then overwrite a replacement owner.
        """
        return await self._lease_backend.set_state_if_lease_owner(
            self._lease_key(stream_id),
            self._state_key(stream_id),
            token,
            state.value,
            ttl_seconds=self._ttl_seconds,
        )

    async def _notify_interrupted(
        self,
        listeners: set[str],
        gate: asyncio.Lock,
    ) -> None:
        """Unblock subscribers owned by a producer that was fenced/interrupted."""
        async with gate:
            payload = _encode("interrupted")
            for listener_id in tuple(listeners):
                with suppress(Exception):
                    await self._backend.publish(
                        self._listener_channel(listener_id), payload
                    )

    async def _heartbeat(
        self, stream_id: str, token: str, fenced: asyncio.Event
    ) -> None:
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval_seconds)
                renewed = await self._lease_backend.renew_lease(
                    self._lease_key(stream_id),
                    self._state_key(stream_id),
                    token,
                    ttl_seconds=self._ttl_seconds,
                )
                if not renewed:
                    fenced.set()
                    logger.warning(
                        "stream-resume producer fenced (lease lost): %s", stream_id
                    )
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            # Redis outage or unexpected error: treat as lease loss so the producer
            # stops publishing rather than silently continuing without fencing.
            fenced.set()
            logger.exception(
                "stream-resume heartbeat failed (fencing): %s", stream_id
            )

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
