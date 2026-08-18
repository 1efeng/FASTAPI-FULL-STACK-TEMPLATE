#!/usr/bin/env python3
"""Benchmark DeepSeek V4 Flash native travel-planning capability.

This is an isolated experiment. It bypasses the product Travel Agent, LiteLLM,
Travel Skills, Research Agent, and custom tools so B0/B1 differ only by whether
DeepSeek's official server-side Web Search tool is available.

B0: Golden User Request -> deepseek-v4-flash
B1: Golden User Request -> deepseek-v4-flash + DeepSeek server-side Web Search

The script intentionally does not print model thinking/reasoning content. It
prints final answer text plus observable wire-level metrics such as latency,
usage, stop reason, content block types, Web Search calls, and source URLs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx

# This is an evidence-producing CLI, not application logging.
# ruff: noqa: T201

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_URL = "https://api.deepseek.com/anthropic"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_MAX_TOKENS = 16000
DEFAULT_TIMEOUT_SECONDS = 180.0

GOLDEN_USER_REQUEST = """我和女朋友两个人，都是二十多岁，正常体力，想从郑州去北京玩 3 天。计划 2026 年 8 月 26 日出发，8 月 28 日回来，总预算 5000 元，往返郑州和北京的交通费也包含在预算里。

我们都是第一次去北京，所以希望这次以北京最经典、最有代表性的体验为主，但不想为了多打卡几个景点把每天排得特别赶。除了经典景点，也希望能有一点适合两个人一起散步、拍照、吃饭的时间，让这趟旅行不只是赶景点。

住宿不用豪华，干净安全、交通方便就行；吃饭想体验一些北京特色，但不追求高端餐厅。我们可以正常走路、坐地铁，也能接受早起，但不想连续几天都特别累。

现在还没有买高铁票、订酒店或者预约任何景点，所以具体每天怎么安排都可以调整。请根据这些条件，帮我们规划一份实际可执行的 3 天北京旅行方案。"""


def load_dotenv(path: Path) -> None:
    """Load only DeepSeek values needed by this benchmark without printing them."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in {"DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"}:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def safe_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def normalize_base_url(value: str) -> str:
    base = value.strip().rstrip("/")
    if not base:
        return DEFAULT_BASE_URL
    # The project may use the OpenAI-compatible DeepSeek base URL. This benchmark
    # intentionally targets the Anthropic-compatible endpoint because DeepSeek's
    # server-side Web Search is exposed there.
    if base == "https://api.deepseek.com":
        return DEFAULT_BASE_URL
    return base


def final_text(payload: Mapping[str, Any]) -> str:
    parts: list[str] = []
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    for block in content:
        if not isinstance(block, Mapping):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(str(block["text"]))
    return "\n".join(parts).strip()


def content_types(payload: Mapping[str, Any]) -> list[str]:
    content = payload.get("content")
    if not isinstance(content, list):
        return []
    return [
        str(block.get("type"))
        for block in content
        if isinstance(block, Mapping) and block.get("type") is not None
    ]


def web_search_count(payload: Mapping[str, Any]) -> int:
    return sum(block_type == "server_tool_use" for block_type in content_types(payload))


def collect_source_urls(payload: Mapping[str, Any]) -> list[str]:
    urls: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key == "url" and isinstance(item, str) and item.startswith(("http://", "https://")):
                    cleaned = safe_url(item)
                    if cleaned not in urls:
                        urls.append(cleaned)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    # Do not expose search snippets or thinking text; only source URLs are kept.
    content = payload.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, Mapping) and block.get("type") in {
                "web_search_tool_result",
                "text",
            }:
                walk(block)
    return urls


def safe_usage(payload: Mapping[str, Any]) -> dict[str, Any]:
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        return {}
    # Usage is provider telemetry, not model reasoning; retain it verbatim.
    return {str(key): value for key, value in usage.items()}


async def run_case(
    *,
    client: httpx.AsyncClient,
    api_key: str,
    base_url: str,
    model: str,
    mode: Literal["b0", "b1"],
    max_tokens: int,
    thinking: Literal["auto", "enabled", "disabled"],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": GOLDEN_USER_REQUEST}],
    }
    if thinking != "auto":
        body["thinking"] = {"type": thinking}
    if mode == "b1":
        body["tools"] = [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 10,
            }
        ]

    started = time.perf_counter()
    response = await client.post(
        f"{base_url}/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=body,
    )
    elapsed = time.perf_counter() - started

    try:
        payload: Any = response.json()
    except ValueError:
        payload = {"raw_text": response.text[:2000]}

    if response.status_code >= 400 or not isinstance(payload, Mapping):
        return {
            "mode": mode.upper(),
            "status": "FAIL",
            "http_status": response.status_code,
            "elapsed_seconds": round(elapsed, 3),
            "thinking_mode": thinking,
            "error": payload,
        }

    return {
        "mode": mode.upper(),
        "status": "PASS",
        "http_status": response.status_code,
        "elapsed_seconds": round(elapsed, 3),
        "thinking_mode": thinking,
        "model": payload.get("model"),
        "stop_reason": payload.get("stop_reason"),
        "content_types": content_types(payload),
        "web_search_calls": web_search_count(payload),
        "source_urls": collect_source_urls(payload),
        "usage": safe_usage(payload),
        "answer": final_text(payload),
    }


def print_case(result: Mapping[str, Any]) -> None:
    answer = result.get("answer", "")
    metrics = {key: value for key, value in result.items() if key != "answer"}
    print("\n" + "=" * 88)
    print(f"{result.get('mode')} RESULT")
    print("=" * 88)
    print(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True))
    if answer:
        print("\n--- FINAL ANSWER ---\n")
        print(answer)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("b0", "b1", "all"), default="all")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--thinking",
        choices=("auto", "enabled", "disabled"),
        default="auto",
        help="DeepSeek thinking mode. auto preserves the provider default (currently enabled).",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print("ENVIRONMENT_BLOCKED: DEEPSEEK_API_KEY is not configured")
        return 2

    base_url = normalize_base_url(os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL))
    modes: tuple[Literal["b0", "b1"], ...] = (
        ("b0", "b1") if args.mode == "all" else (args.mode,)
    )

    print("DeepSeek Travel Baseline")
    print(f"model={args.model}")
    print(f"endpoint={safe_url(base_url)}")
    print(f"modes={','.join(mode.upper() for mode in modes)}")
    print("prompt=Golden User Request (fixed)")

    timeout = httpx.Timeout(args.timeout, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        results = []
        for mode in modes:
            result = await run_case(
                client=client,
                api_key=api_key,
                base_url=base_url,
                model=args.model,
                mode=mode,
                max_tokens=args.max_tokens,
                thinking=args.thinking,
            )
            results.append(result)
            print_case(result)

    if any(result.get("status") != "PASS" for result in results):
        return 1
    if "b1" in modes and not any(result.get("web_search_calls", 0) for result in results if result.get("mode") == "B1"):
        print("\nB1 WARNING: request succeeded but no server-side Web Search call was observed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
