import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from httpx import AsyncClient

import app.chat.api as chat_api
from app.chat.protocol.session import AgentStreamSession


class FakeAgent:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.stream_configs: list[dict[str, Any]] = []
        self.state_configs: list[dict[str, Any]] = []

    async def astream_events(
        self,
        _input: dict[str, Any],
        *,
        config: dict[str, Any],
        version: str,
    ) -> AsyncIterator[dict[str, Any]]:
        assert version == "v2"
        self.stream_configs.append(config)
        self.started.set()
        if False:
            yield {}

    async def aget_state(self, config: dict[str, Any]) -> Any:
        self.state_configs.append(config)
        return SimpleNamespace(
            values={"messages": []},
            next=(),
            tasks=(),
            metadata={},
            config=config,
            parent_config=None,
        )


class SlowAgent:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.completed = asyncio.Event()
        self.cancelled = False

    async def astream_events(
        self,
        _input: dict[str, Any],
        **_: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        self.started.set()
        try:
            await self.release.wait()
            self.completed.set()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if False:
            yield {}


class FakeStreamSession:
    def __init__(self) -> None:
        self.last_event_id: int | None = None

    async def subscribe(self, last_event_id: int | None = None) -> AsyncIterator[str]:
        self.last_event_id = last_event_id
        yield (
            "id: 3\n"
            "event: message\n"
            'data: {"type":"event","event_id":"3","seq":3,'
            '"timestamp":1,"data":{"type":"message"}}\n\n'
        )


class FakeRunRegistry:
    def __init__(self, task: asyncio.Task[Any]) -> None:
        self.task = task
        self.lookup: tuple[str, str] | None = None

    def get(self, user_id: str, run_id: str) -> asyncio.Task[Any] | None:
        self.lookup = (user_id, run_id)
        return self.task


async def test_agent_protocol_command_starts_langgraph_run(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    agent = FakeAgent()
    monkeypatch.setattr(chat_api, "get_agent", lambda: agent)

    response = await client.post(
        "/api/v1/threads/thread-1/commands",
        headers=superuser_token_headers,
        json={
            "id": 1,
            "method": "run.start",
            "params": {
                "assistant_id": "agent",
                "input": {"messages": [{"type": "human", "content": "你好"}]},
            },
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["type"] == "success"
    assert result["result"]["run_id"]

    await asyncio.wait_for(agent.started.wait(), 1)
    internal_thread_id = agent.stream_configs[0]["configurable"]["thread_id"]
    assert internal_thread_id.endswith(":thread-1")
    assert internal_thread_id != "thread-1"


async def test_sse_disconnect_does_not_cancel_agent_run(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    agent = SlowAgent()
    session = AgentStreamSession("thread-disconnect")
    monkeypatch.setattr(chat_api, "get_agent", lambda: agent)
    monkeypatch.setattr(
        chat_api,
        "get_stream_session",
        lambda _owner_id, _thread_id: session,
    )

    response = await client.post(
        "/api/v1/threads/thread-disconnect/commands",
        headers=superuser_token_headers,
        json={
            "id": 1,
            "method": "run.start",
            "params": {"input": {"messages": [{"type": "human", "content": "wait"}]}},
        },
    )
    assert response.status_code == 200
    await asyncio.wait_for(agent.started.wait(), 1)

    subscriber = session.subscribe()
    await asyncio.wait_for(anext(subscriber), 1)
    await subscriber.aclose()

    assert not agent.cancelled
    assert not agent.completed.is_set()

    agent.release.set()
    await asyncio.wait_for(agent.completed.wait(), 1)
    assert not agent.cancelled


async def test_agent_protocol_stream_replays_from_last_event_id(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    session = FakeStreamSession()
    monkeypatch.setattr(
        chat_api,
        "get_stream_session",
        lambda _owner_id, _thread_id: session,
    )

    response = await client.post(
        "/api/v1/threads/thread-1/stream",
        headers=superuser_token_headers,
        json={
            "channels": ["messages", "lifecycle"],
            "last_event_id": 2,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert session.last_event_id == 2
    assert '"seq":3' in response.text


async def test_agent_protocol_state_reads_langgraph_checkpoint(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    agent = FakeAgent()
    monkeypatch.setattr(chat_api, "get_agent", lambda: agent)

    response = await client.get(
        "/api/v1/threads/thread-1/state",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json()["values"] == {"messages": []}
    assert len(agent.state_configs) == 1
    internal_thread_id = agent.state_configs[0]["configurable"]["thread_id"]
    assert internal_thread_id.endswith(":thread-1")


def test_checkpoint_thread_id_is_isolated_by_user() -> None:
    first = chat_api._config("user-a", "shared-thread")
    second = chat_api._config("user-b", "shared-thread")

    assert first["configurable"]["thread_id"] == "user-a:shared-thread"
    assert second["configurable"]["thread_id"] == "user-b:shared-thread"
    assert first != second


async def test_cancel_endpoint_is_transport_level_task_cancel(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    task = asyncio.create_task(asyncio.Event().wait())
    registry = FakeRunRegistry(task)
    monkeypatch.setattr(chat_api, "run_registry", registry)

    response = await client.post(
        "/api/v1/threads/thread-1/runs/run-1/cancel?action=interrupt",
        headers=superuser_token_headers,
    )

    assert response.status_code == 204
    assert registry.lookup is not None
    assert registry.lookup[1] == "run-1"
    await asyncio.sleep(0)
    assert task.cancelled()


async def test_agent_protocol_routes_require_authentication(client: AsyncClient) -> None:
    command = await client.post(
        "/api/v1/threads/thread-1/commands",
        json={"id": 1, "method": "run.start", "params": {"input": {"messages": []}}},
    )
    stream = await client.post(
        "/api/v1/threads/thread-1/stream",
        json={"channels": ["messages"]},
    )
    state = await client.get("/api/v1/threads/thread-1/state")
    cancel = await client.post("/api/v1/threads/thread-1/runs/run-1/cancel")

    assert command.status_code == 401
    assert stream.status_code == 401
    assert state.status_code == 401
    assert cancel.status_code == 401
