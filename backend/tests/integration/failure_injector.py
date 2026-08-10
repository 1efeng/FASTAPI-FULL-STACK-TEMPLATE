"""Failure-injection stub for the LiteLLM fallback smoke tests.

Serves an OpenAI-compatible ``POST /v1/chat/completions`` endpoint whose
behavior is selected by the requested ``model`` name:

- ``stub-ok``      -> immediate valid completion
- ``stub-timeout`` -> hangs well past any gateway timeout (triggers fallback)
- ``stub-429``     -> HTTP 429 rate-limit signal (triggers fallback)
- ``stub-500``     -> HTTP 500 server error (triggers fallback)

Everything is stub-based; no real provider is ever contacted. Used together
with ``infra/litellm/config.fallback-smoke.yaml``; see
``backend/scripts/litellm-failure-smoke.sh``.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

# Longer than any gateway timeout configured for the smoke models, so the
# gateway (not this stub) is the side that decides the call failed.
HANG_SECONDS = float(os.environ.get("STUB_HANG_SECONDS", "300"))


def _completion(model: str) -> dict[str, Any]:
    return {
        "id": f"stub-{model}",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "OK"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(payload: dict[str, Any]) -> JSONResponse:
    model = payload.get("model", "")
    if model == "stub-timeout":
        await asyncio.sleep(HANG_SECONDS)
        return JSONResponse(_completion(model))
    if model == "stub-429":
        return JSONResponse(
            {"error": {"message": "stub rate limited", "type": "rate_limit"}},
            status_code=429,
        )
    if model == "stub-500":
        return JSONResponse(
            {"error": {"message": "stub server error", "type": "server_error"}},
            status_code=500,
        )
    return JSONResponse(_completion(model))


def run() -> None:
    """Run the stub standalone: ``python failure_injector.py``."""
    import uvicorn

    host = os.environ.get("FAILURE_INJECTOR_HOST", "0.0.0.0")
    port = int(os.environ.get("FAILURE_INJECTOR_PORT", "9000"))
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run()
