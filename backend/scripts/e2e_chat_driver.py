#!/usr/bin/env python3
"""E2E driver: exercise the full Product travel-agent stack with a real chat.

Chain under test (all real, no mocks):
  auth/login -> POST /conversations -> POST /chat (non-streaming)
    -> ChatService -> PydanticAIExecutor -> LiteLLM gateway -> DeepSeek
    -> durable request_run + conversation messages
Then reads back request_run + conversation detail to record key data:
  end-to-end latency, answer text, reasoning summary, source URLs,
  request status, idempotency replay.

Credentials are read from container env (FIRST_SUPERUSER*) so nothing is printed.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

# ruff: noqa: T201

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
API_PREFIX = os.environ.get("E2E_API_PREFIX", "/api/v1")
TIMEOUT = httpx.Timeout(240.0, connect=10.0)

GOLDEN_MESSAGE = """我和女朋友两个人，都是二十多岁，正常体力，想从郑州去北京玩 3 天。计划 2026 年 8 月 26 日出发，8 月 28 日回来，总预算 5000 元，往返郑州和北京的交通费也包含在预算里。

我们都是第一次去北京，所以希望这次以北京最经典、最有代表性的体验为主，但不想为了多打卡几个景点把每天排得特别赶。除了经典景点，也希望能有一点适合两个人一起散步、拍照、吃饭的时间，让这趟旅行不只是赶景点。

住宿不用豪华，干净安全、交通方便就行；吃饭想体验一些北京特色，但不追求高端餐厅。我们可以正常走路、坐地铁，也能接受早起，但不想连续几天都特别累。

现在还没有买高铁票、订酒店或者预约任何景点，所以具体每天怎么安排都可以调整。请根据这些条件，帮我们规划一份实际可执行的 3 天北京旅行方案。"""


def safe_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return value
    return value


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def main() -> int:
    base = BASE.rstrip("/")
    api = f"{base}{API_PREFIX}"

    email = os.environ.get("FIRST_SUPERUSER", "").strip()
    password = os.environ.get("FIRST_SUPERUSER_PASSWORD", "").strip()
    if not email or not password:
        print("ENVIRONMENT_BLOCKED: FIRST_SUPERUSER credentials not available in env")
        return 2

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        # 1) login
        login = await client.post(
            f"{api}/login/access-token",
            data={"username": email, "password": password},
        )
        if login.status_code != 200:
            print(json.dumps({"step": "login", "status": "FAIL", "http": login.status_code, "body": login.text[:500]}, ensure_ascii=False))
            return 1
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2) create conversation
        conv = await client.post(
            f"{api}/conversations/",
            headers=headers,
            json={"title": "E2E 北京3日游测试"},
        )
        if conv.status_code != 200:
            print(json.dumps({"step": "create_conversation", "status": "FAIL", "http": conv.status_code, "body": conv.text[:500]}, ensure_ascii=False))
            return 1
        conversation_id = conv.json()["id"]

        # 3) chat (real full chain)
        wall_started = time.perf_counter()
        chat = await client.post(
            f"{api}/chat",
            headers={**headers, "Idempotency-Key": "e2e-beijing-3day-1"},
            json={
                "conversation_id": conversation_id,
                "message": GOLDEN_MESSAGE,
                "enable_web_search": True,
                "enable_thinking": True,
            },
        )
        wall_elapsed = time.perf_counter() - wall_started
        if chat.status_code != 200:
            print(json.dumps({"step": "chat", "status": "FAIL", "http": chat.status_code, "body": chat.text[:1000]}, ensure_ascii=False))
            return 1
        chat_body = chat.json()

        # 4) request_run detail
        request_id = chat_body["request_id"]
        run = await client.get(f"{api}/chat/requests/{request_id}", headers=headers)
        run_body = run.json() if run.status_code == 200 else None

        # 5) conversation detail (messages + reasoning + sources)
        detail = await client.get(f"{api}/conversations/{conversation_id}", headers=headers)
        detail_body = detail.json() if detail.status_code == 200 else None

        # 6) idempotency replay check
        replay = await client.post(
            f"{api}/chat",
            headers={**headers, "Idempotency-Key": "e2e-beijing-3day-1"},
            json={
                "conversation_id": conversation_id,
                "message": GOLDEN_MESSAGE,
                "enable_web_search": True,
                "enable_thinking": True,
            },
        )
        replay_body = replay.json() if replay.status_code == 200 else None

        started = parse_dt((run_body or {}).get("started_at"))
        finished = parse_dt((run_body or {}).get("finished_at"))
        run_latency = (finished - started).total_seconds() if started and finished else None

        messages = (detail_body or {}).get("messages", [])
        assistant = next((m for m in messages if m.get("role") == "assistant"), None)

        record: dict[str, Any] = {
            "step": "chat",
            "status": chat_body.get("status"),
            "replayed": chat_body.get("replayed", False),
            "request_id": request_id,
            "conversation_id": conversation_id,
            "wall_elapsed_seconds": round(wall_elapsed, 3),
            "request_run_latency_seconds": round(run_latency, 3) if run_latency is not None else None,
            "request_run": {
                "status": (run_body or {}).get("status"),
                "error_code": (run_body or {}).get("error_code"),
                "started_at": (run_body or {}).get("started_at"),
                "finished_at": (run_body or {}).get("finished_at"),
            },
            "answer_chars": len(assistant.get("content", "")) if assistant else 0,
            "reasoning_summary_chars": len(assistant.get("reasoning_summary") or "") if assistant else 0,
            "source_urls": assistant.get("source_urls", []) if assistant else [],
            "source_url_count": len(assistant.get("source_urls", [])) if assistant else 0,
            "message_roles": [m.get("role") for m in messages],
            "idempotency_replay": {
                "status": (replay_body or {}).get("status"),
                "replayed": (replay_body or {}).get("replayed", False),
                "same_request_id": (replay_body or {}).get("request_id") == request_id,
            },
            "answer": (assistant or {}).get("content"),
            "reasoning_summary": (assistant or {}).get("reasoning_summary"),
        }
        print(json.dumps(record, ensure_ascii=False, indent=2))

    return 0


def asyncio_run() -> int:
    import asyncio

    return asyncio.run(main())


if __name__ == "__main__":
    sys.exit(asyncio_run())