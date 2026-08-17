#!/usr/bin/env python3
"""Isolated DeepSeek Responses/native web-search capability spike.

This script deliberately bypasses the product AgentExecutor and does not import
formal chat/research runtime modules. It reports wire evidence rather than
inferring native search from answer text.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic_ai import Agent
from pydantic_ai.capabilities import WebSearch
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

# This is an evidence-producing CLI, not application logging.
# ruff: noqa: T201

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIMEOUT = httpx.Timeout(90.0, connect=15.0)
DIRECT_MODEL = "deepseek-v4-flash"
LITELLM_MODEL = "travel-agent-llm"
BASIC_PROMPT = "只回答 OK"
SEARCH_PROMPT = "北京今天有什么最新新闻？请基于联网搜索结果回答，并给出来源。"


def load_dotenv(path: Path) -> None:
    """Load only values needed by this spike without printing them."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in {
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_BASE_URL",
            "LITELLM_BASE_URL",
            "LITELLM_SERVICE_KEY",
            "LLM_LOGICAL_MODEL",
        }:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default).strip()
    return value.rstrip("/")


def safe_url(url: str) -> str:
    """Return an endpoint with credentials/query fragments removed."""
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def redact(value: str) -> str:
    value = re.sub(r"(?i)(bearer\s+)[^\s,]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(api[_ -]?key|authorization)([\s:=]+)[^\s,}]+", r"\1\2[REDACTED]", value)
    return value[:800]


def jsonable(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "<max-depth>"
    if value is None or isinstance(value, str | int | float | bool):
        return value[:1000] if isinstance(value, str) else value
    if isinstance(value, Mapping):
        return {str(key): jsonable(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item, depth=depth + 1) for item in value[:50]]
    if dataclasses.is_dataclass(value):
        return jsonable(dataclasses.asdict(value), depth=depth + 1)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return jsonable(model_dump(mode="json"), depth=depth + 1)
    if hasattr(value, "__dict__"):
        return jsonable(vars(value), depth=depth + 1)
    return redact(repr(value))


def print_json(label: str, value: Any) -> None:
    print(f"{label}={json.dumps(jsonable(value), ensure_ascii=False, sort_keys=True)}")


def collect_text(value: Any) -> list[str]:
    text: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in {"text", "value", "output_text"} and isinstance(item, str):
                text.append(item)
            else:
                text.extend(collect_text(item))
    elif isinstance(value, list | tuple):
        for item in value:
            text.extend(collect_text(item))
    return text


def collect_sources(value: Any) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []

    def walk(item: Any, context: str = "") -> None:
        if isinstance(item, Mapping):
            current_type = str(item.get("type", context))
            url = item.get("url")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                source = {"url": safe_url(url), "type": current_type}
                for title_key in ("title", "name"):
                    if isinstance(item.get(title_key), str):
                        source["title"] = str(item[title_key])[:300]
                        break
                if source not in sources:
                    sources.append(source)
            for key, child in item.items():
                walk(child, str(key))
        elif isinstance(item, list | tuple):
            for child in item:
                walk(child, context)

    walk(value)
    return sources[:100]


def response_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    output = payload.get("output")
    output_items = output if isinstance(output, list) else []
    output_types = [item.get("type") for item in output_items if isinstance(item, Mapping)]
    evidence_types = [
        item_type
        for item_type in output_types
        if isinstance(item_type, str) and "search" in item_type.lower()
    ]
    annotations = []
    for item in output_items:
        if isinstance(item, Mapping):
            value = item.get("content")
            if isinstance(value, list):
                for content in value:
                    if isinstance(content, Mapping) and isinstance(content.get("annotations"), list):
                        annotations.extend(content["annotations"])
    return {
        "top_level_keys": sorted(payload),
        "response_id": payload.get("id"),
        "output_item_types": output_types,
        "native_search_item_types": evidence_types,
        "text": "".join(collect_text(payload))[:6000],
        "sources": collect_sources(payload),
        "annotations": jsonable(annotations),
        "usage": payload.get("usage"),
    }


def error_summary(response: httpx.Response) -> dict[str, Any]:
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    error = body.get("error") if isinstance(body, Mapping) else None
    if isinstance(error, Mapping):
        error_type = error.get("type") or error.get("code")
        message = error.get("message") or error.get("detail") or str(error)
    else:
        error_type = None
        message = str(body)
    return {
        "http_status": response.status_code,
        "error_type": error_type,
        "sanitized_message": redact(str(message)),
        "endpoint": safe_url(str(response.request.url)),
    }


def response_endpoint_candidates(base_url: str) -> list[str]:
    configured = os.environ.get("DEEPSEEK_RESPONSES_URL", "").strip()
    if configured:
        return [safe_url(configured)]
    if base_url.endswith("/v1"):
        return [f"{base_url}/responses"]
    return [f"{base_url}/v1/responses", f"{base_url}/responses"]


async def post_json(
    client: httpx.AsyncClient,
    endpoint: str,
    payload: Mapping[str, Any],
    api_key: str,
) -> tuple[httpx.Response | None, dict[str, Any] | None]:
    try:
        response = await client.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
    except httpx.HTTPError as exc:
        print_json("transport_error", {"type": type(exc).__name__, "message": redact(str(exc)), "endpoint": endpoint})
        return None, None
    if response.is_success:
        try:
            return response, response.json()
        except ValueError:
            print_json("schema_error", {"message": "successful response was not JSON", "endpoint": endpoint})
            return response, None
    print_json("error", error_summary(response))
    return response, None


async def stream_json(
    client: httpx.AsyncClient,
    endpoint: str,
    payload: Mapping[str, Any],
    api_key: str,
) -> dict[str, Any]:
    event_types: list[str] = []
    text_delta_count = 0
    usage: Any = None
    try:
        async with client.stream(
            "POST",
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        ) as response:
            if not response.is_success:
                return {"status": response.status_code, "error": error_summary(response)}
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if isinstance(event_type, str):
                    event_types.append(event_type)
                    if "text" in event_type.lower() and "delta" in event_type.lower():
                        text_delta_count += 1
                if isinstance(event.get("usage"), Mapping):
                    usage = event["usage"]
                response_object = event.get("response")
                if isinstance(response_object, Mapping) and isinstance(response_object.get("usage"), Mapping):
                    usage = response_object["usage"]
    except httpx.HTTPError as exc:
        return {"transport_error": {"type": type(exc).__name__, "message": redact(str(exc)), "endpoint": endpoint}}
    unique_events = list(dict.fromkeys(event_types))
    return {
        "status": 200,
        "event_types": unique_events,
        "native_search_events": [event for event in unique_events if "search" in event.lower()],
        "text_delta_count": text_delta_count,
        "usage": usage,
    }


def print_raw_result(label: str, response: httpx.Response, payload: Mapping[str, Any]) -> None:
    print_json(label, response_summary(payload))
    print_json(f"{label}_headers", {key.lower(): value for key, value in response.headers.items() if key.lower().startswith("x-litellm")})


async def run_direct(client: httpx.AsyncClient, base_url: str, api_key: str) -> tuple[bool, dict[str, Any] | None]:
    endpoints = response_endpoint_candidates(base_url)
    basic: tuple[httpx.Response, dict[str, Any]] | None = None
    print_json("DIRECT_RESPONSES_ENDPOINT_CANDIDATES", endpoints)
    for endpoint in endpoints:
        response, payload = await post_json(client, endpoint, {"model": DIRECT_MODEL, "input": BASIC_PROMPT, "stream": False}, api_key)
        if response is not None and payload is not None:
            basic = response, payload
            print_raw_result("DIRECT_BASIC", response, payload)
            break
        if response is not None and response.status_code not in {404, 405}:
            break
    if basic is None:
        print("SMOKE_A_RESPONSES=FAIL")
        return False, None
    print("SMOKE_A_RESPONSES=PASS")
    response, _ = basic
    search_payload = {
        "model": DIRECT_MODEL,
        "input": SEARCH_PROMPT,
        "tools": [{"type": "web_search"}],
        "stream": False,
    }
    search_response, search_result = await post_json(client, str(response.request.url), search_payload, api_key)
    if search_response is None or search_result is None:
        print("SMOKE_B_NATIVE_SEARCH=FAIL")
    else:
        print_raw_result("DIRECT_NATIVE_SEARCH", search_response, search_result)
        evidence = response_summary(search_result)
        status = "PASS" if evidence["native_search_item_types"] and evidence["sources"] else "PARTIAL"
        print(f"SMOKE_B_NATIVE_SEARCH={status}")
    return True, search_result


async def run_litellm(client: httpx.AsyncClient, base_url: str, api_key: str) -> tuple[bool, dict[str, Any] | None, str]:
    endpoint = f"{base_url}/v1/responses"
    basic_payload = {"model": LITELLM_MODEL, "input": BASIC_PROMPT, "stream": False}
    response, payload = await post_json(client, endpoint, basic_payload, api_key)
    if response is None or payload is None:
        print("LITELLM_RESPONSES_BASIC=FAIL")
        return False, None, endpoint
    print_raw_result("LITELLM_BASIC", response, payload)
    print("LITELLM_RESPONSES_BASIC=PASS")
    search_payload = {"model": LITELLM_MODEL, "input": SEARCH_PROMPT, "tools": [{"type": "web_search"}], "stream": False}
    search_response, search_result = await post_json(client, endpoint, search_payload, api_key)
    if search_response is None or search_result is None:
        print("SMOKE_C_LITELLM_NATIVE_SEARCH=FAIL")
    else:
        print_raw_result("LITELLM_NATIVE_SEARCH", search_response, search_result)
        evidence = response_summary(search_result)
        status = "PASS" if evidence["native_search_item_types"] and evidence["sources"] else "PARTIAL"
        print(f"SMOKE_C_LITELLM_NATIVE_SEARCH={status}")
    return True, search_result, endpoint


def result_usage(result: Any) -> Any:
    """Read the locked PydanticAI result usage API across result types."""
    value = getattr(result, "usage", None)
    return value() if callable(value) else value


async def run_raw_streams(
    client: httpx.AsyncClient,
    deepseek_endpoint: str,
    deepseek_key: str,
    litellm_endpoint: str,
    litellm_key: str,
) -> None:
    search_input = {"input": SEARCH_PROMPT, "tools": [{"type": "web_search"}], "stream": True}
    direct = await stream_json(
        client,
        deepseek_endpoint,
        {"model": DIRECT_MODEL, **search_input},
        deepseek_key,
    )
    print_json("DIRECT_STREAM", direct)
    litellm = await stream_json(
        client,
        litellm_endpoint,
        {"model": LITELLM_MODEL, **search_input},
        litellm_key,
    )
    print_json("LITELLM_STREAM", litellm)


async def run_pydanticai(litellm_base_url: str, service_key: str) -> tuple[bool, Agent[Any] | None]:
    provider = OpenAIProvider(base_url=f"{litellm_base_url}/v1", api_key=service_key)
    model = OpenAIResponsesModel(LITELLM_MODEL, provider=provider)
    agent = Agent(model, capabilities=[WebSearch()], defer_model_check=True)
    try:
        result = await agent.run(SEARCH_PROMPT)
    except Exception as exc:  # Diagnostics must retain the layer and sanitized cause.
        print_json("PYDANTICAI_ERROR", {"type": type(exc).__name__, "message": redact(str(exc))})
        print("SMOKE_D_PYDANTICAI=FAIL")
        return False, agent
    print_json("PYDANTICAI_OUTPUT", result.output)
    print_json("PYDANTICAI_USAGE", result_usage(result))
    messages = result.new_messages()
    print_json("PYDANTICAI_MESSAGE_COUNT", len(messages))
    response_count = 0
    evidence_count = 0
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        response_count += 1
        for part in message.parts:
            part_payload = jsonable(part)
            print_json("PYDANTICAI_PART", {"type": type(part).__name__, "value": part_payload, "sources": collect_sources(part_payload)})
            if "search" in type(part).__name__.lower() or "web_search" in json.dumps(part_payload).lower():
                evidence_count += 1
    print_json("PYDANTICAI_MODEL_RESPONSE_COUNT", response_count)
    status = "PASS" if evidence_count else "PARTIAL"
    print(f"SMOKE_D_PYDANTICAI={status}")
    return True, agent


async def run_pydanticai_stream(agent: Agent[Any] | None) -> None:
    if agent is None:
        print("SMOKE_E_STREAMING=FAIL")
        return
    event_types: list[str] = []
    text_chunks = 0
    search_evidence = 0
    source_urls: list[str] = []
    try:
        async with agent.run_stream(SEARCH_PROMPT) as result:
            async for response in result.stream_response():
                event_types.append(type(response).__name__)
                for part in response.parts:
                    part_type = type(part).__name__
                    event_types.append(part_type)
                    if isinstance(part, TextPart):
                        text_chunks += 1
                    if "search" in part_type.lower() or getattr(part, "tool_name", "") == "web_search":
                        search_evidence += 1
                    source_urls.extend(source["url"] for source in collect_sources(jsonable(part)))
            print_json("PYDANTICAI_STREAM_USAGE", result_usage(result))
            print_json("PYDANTICAI_STREAM_MESSAGES", len(result.new_messages()))
    except Exception as exc:
        print_json("PYDANTICAI_STREAM_ERROR", {"type": type(exc).__name__, "message": redact(str(exc))})
        print("SMOKE_E_STREAMING=FAIL")
        return
    unique_events = list(dict.fromkeys(event_types))
    print_json("PYDANTICAI_STREAM_EVENT_TYPES", unique_events)
    print_json("PYDANTICAI_STREAM_TEXT_EVENT_COUNT", text_chunks)
    print_json("PYDANTICAI_STREAM_SEARCH_EVIDENCE_COUNT", search_evidence)
    print_json("PYDANTICAI_STREAM_SOURCE_URLS", list(dict.fromkeys(source_urls)))
    if search_evidence and text_chunks:
        print("SMOKE_E_STREAMING=PASS")
    elif text_chunks:
        print("SMOKE_E_STREAMING=PARTIAL")
    else:
        print("SMOKE_E_STREAMING=FAIL")


async def main() -> int:
    load_dotenv(ROOT / ".env")
    deepseek_base = env("DEEPSEEK_BASE_URL")
    deepseek_key = env("DEEPSEEK_API_KEY")
    litellm_base = env("LITELLM_BASE_URL", "http://localhost:4000")
    litellm_key = env("LITELLM_SERVICE_KEY")
    if not deepseek_base or not deepseek_key:
        print("SMOKE_A_RESPONSES=FAIL")
        print_json("CONFIG_ERROR", {"missing": [name for name, value in (("DEEPSEEK_BASE_URL", deepseek_base), ("DEEPSEEK_API_KEY", deepseek_key)) if not value]})
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        direct_pass, _ = await run_direct(client, deepseek_base, deepseek_key) if deepseek_base and deepseek_key else (False, None)
        litellm_pass, _, litellm_endpoint = await run_litellm(client, litellm_base, litellm_key) if litellm_key else (False, None, f"{litellm_base}/v1/responses")
        pydantic_agent: Agent[Any] | None = None
        if litellm_pass:
            if direct_pass and deepseek_base and deepseek_key:
                await run_raw_streams(
                    client,
                    response_endpoint_candidates(deepseek_base)[0],
                    deepseek_key,
                    litellm_endpoint,
                    litellm_key,
                )
            _, pydantic_agent = await run_pydanticai(litellm_base, litellm_key)
            await run_pydanticai_stream(pydantic_agent)
        else:
            print("SMOKE_D_PYDANTICAI=FAIL")
            print("SMOKE_E_STREAMING=FAIL")
        print_json("SPIKE_ENDPOINTS", {"deepseek_base_url": safe_url(deepseek_base), "litellm_responses": safe_url(litellm_endpoint)})
        print_json("SPIKE_GATE_SUMMARY", {"direct_basic": direct_pass, "litellm_basic": litellm_pass})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
