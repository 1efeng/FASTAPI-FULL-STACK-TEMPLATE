#!/usr/bin/env python3
"""E2E rerun: original short prompt on the CURRENT code, real full chain.

Same chain as e2e_chat_driver.py but with the original 原文提示词:
  北京3日游 郑州出发 总预算5000 2人情侣 8月26日出发
(Old-code reference on 31c4cbd: 125s / 14 model calls, 18 tool calls,
 hit MAIN_TOOL_CALL_LIMIT=16 -> MODEL_CALL_LIMIT_REACHED failure.)
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
TIMEOUT = httpx.Timeout(300.0, connect=10.0)

ORIGINAL_PROMPT = "北京3日游 郑州出发 总预算5000 2人情侣 8月26日出发"


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
        login = await client.post(
            f"{api}/login/access-token",
            data={"username": email, "password": password},
        )
        if login.status_code != 200:
            print(json.dumps({"step": "login", "status": "FAIL", "http": login.status_code, "body": login.text[:500]}, ensure_ascii=False))
            return 1
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        conv = await client.post(
            f"{api}/conversations/",
            headers=headers,
            json={"title": "E2E 原文提示词对比"},
        )
        if conv.status_code != 200:
            print(json.dumps({"step": "create_conversation", "status": "FAIL", "http": conv.status_code, "body": conv.text[:500]}, ensure_ascii=False))
            return 1
        conversation_id = conv.json()["id"]

        wall_started = time.perf_counter()
        chat = await client.post(
            f"{api}/chat",
            headers={**headers, "Idempotency-Key": "e2e-orig-prompt-1"},
            json={
                "conversation_id": conversation_id,
                "message": ORIGINAL_PROMPT,
                "enable_web_search": True,
                "enable_thinking": True,
            },
        )
        wall_elapsed = time.perf_counter() - wall_started
        if chat.status_code != 200:
            print(json.dumps({"step": "chat", "status": "FAIL", "http": chat.status_code, "body": chat.text[:1000]}, ensure_ascii=False))
            return 1
        chat_body = chat.json()

        request_id = chat_body["request_id"]
        run = await client.get(f"{api}/chat/requests/{request_id}", headers=headers)
        run_body = run.json() if run.status_code == 200 else None

        detail = await client.get(f"{api}/conversations/{conversation_id}", headers=headers)
        detail_body = detail.json() if detail.status_code == 200 else None

        started = parse_dt((run_body or {}).get("started_at"))
        finished = parse_dt((run_body or {}).get("finished_at"))
        run_latency = (finished - started).total_seconds() if started and finished else None

        messages = (detail_body or {}).get("messages", [])
        assistant = next((m for m in messages if m.get("role") == "assistant"), None)

        record: dict[str, Any] = {
            "case": ORIGINAL_PROMPT,
            "status": chat_body.get("status"),
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
            "source_url_count": len(assistant.get("source_urls", [])) if assistant else 0,
            "message_roles": [m.get("role") for m in messages],
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