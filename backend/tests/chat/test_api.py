from collections.abc import AsyncIterator
from typing import Any

from httpx import AsyncClient

import app.chat.api as chat_api


class FakeSession:
    def __init__(self) -> None:
        self.cancelled: tuple[str, bool] | None = None

    async def handle_command(self, command: dict[str, Any]) -> dict[str, Any]:
        assert command["method"] == "run.start"
        return {"type": "success", "id": command["id"], "result": {"run_id": "run-1"}}

    async def event_stream(self, request: dict[str, Any]) -> AsyncIterator[str]:
        assert "messages" in request["channels"]
        yield (
            'id: 1\nevent: message\ndata: '
            '{"type":"event","event_id":"1","seq":1,"method":"lifecycle",'
            '"params":{"namespace":[],"timestamp":1,"data":{"event":"started"}}}\n\n'
        )

    def state(self) -> dict[str, Any]:
        return {
            "values": {"messages": []},
            "next": [],
            "tasks": [],
            "metadata": {"active_run_id": None},
            "checkpoint": None,
            "parent_checkpoint": None,
        }

    async def cancel_run(self, run_id: str, *, wait: bool = False) -> bool:
        self.cancelled = (run_id, wait)
        return True


def _install_fake_session(monkeypatch) -> FakeSession:
    session = FakeSession()
    monkeypatch.setattr(chat_api, "get_thread_session", lambda _owner, _thread: session)
    return session


async def test_agent_protocol_command_starts_run(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    _install_fake_session(monkeypatch)

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
    assert response.json() == {
        "type": "success",
        "id": 1,
        "result": {"run_id": "run-1"},
    }


async def test_agent_protocol_stream_is_plain_sse(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    _install_fake_session(monkeypatch)

    response = await client.post(
        "/api/v1/threads/thread-1/stream",
        headers=superuser_token_headers,
        json={"channels": ["messages", "lifecycle"], "since": 0},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "x-vercel-ai-ui-message-stream" not in response.headers
    assert '"method":"lifecycle"' in response.text


async def test_agent_protocol_state_supports_hydration(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    _install_fake_session(monkeypatch)

    response = await client.get(
        "/api/v1/threads/thread-1/state",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json()["values"] == {"messages": []}


async def test_cancel_endpoint_cancels_server_run(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    session = _install_fake_session(monkeypatch)

    response = await client.post(
        "/api/v1/threads/thread-1/runs/run-1/cancel?wait=1&action=interrupt",
        headers=superuser_token_headers,
    )

    assert response.status_code == 204
    assert session.cancelled == ("run-1", True)


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
