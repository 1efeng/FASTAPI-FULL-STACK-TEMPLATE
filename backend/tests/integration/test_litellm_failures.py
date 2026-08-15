"""Integration tests for LiteLLM fallback behavior under failure injection.

These verify the three M2 LiteLLM items that a plain live smoke cannot cover:

- ``smoke-timeout``: primary hangs -> router falls back to ``smoke-ok``
- ``smoke-429``:    primary returns 429 -> router falls back to ``smoke-ok``
- ``smoke-all-down``: primary and fallback both fail -> clean 5xx surfaced

The LiteLLM gateway must be running with
``infra/litellm/config.fallback-smoke.yaml`` (see
``backend/scripts/litellm-failure-smoke.sh``) and the failure-injection stub
must be reachable at ``FAILURE_INJECTOR_PORT``. Set
``RUN_LITELLM_FAILURE_INTEGRATION=1`` to run; otherwise the module skips.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from openai import APIStatusError, AsyncOpenAI

_RUN_KEY = "RUN_LITELLM_FAILURE_INTEGRATION"
pytestmark = pytest.mark.skipif(
    os.getenv(_RUN_KEY) != "1",
    reason=f"set {_RUN_KEY}=1 to run against the live failure-injection gateway",
)

STUB_PORT = int(os.environ.get("FAILURE_INJECTOR_PORT", "9000"))
STUB_BASE_URL = f"http://127.0.0.1:{STUB_PORT}"
SMOKE_CLIENT_TIMEOUT_SECONDS = float(
    os.getenv("LITELLM_FAILURE_SMOKE_CLIENT_TIMEOUT_SECONDS", "20")
)
EXPECTED_MODEL_GROUPS = {
    "smoke-ok",
    "smoke-timeout",
    "smoke-429",
    "smoke-all-down",
    "smoke-down",
}


def _stub_process() -> subprocess.Popen[bytes]:
    integration_dir = Path(__file__).resolve().parent
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "failure_injector:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(STUB_PORT),
            "--log-level",
            "warning",
        ],
        cwd=str(integration_dir),
    )


def _wait_until_ready(timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=2.0) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(f"{STUB_BASE_URL}/health")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
    raise RuntimeError(f"failure injector never became ready at {STUB_BASE_URL}")


@pytest.fixture(scope="module")
def stub_server() -> Iterator[str]:
    """Start the failure-injection stub in a child process for the module."""
    process = _stub_process()
    try:
        _wait_until_ready()
        yield STUB_BASE_URL
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def _gateway_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=os.environ.get("LITELLM_SERVICE_KEY", "sk-local-master"),
        base_url=f"{os.environ['LITELLM_BASE_URL'].rstrip('/')}/v1",
        timeout=SMOKE_CLIENT_TIMEOUT_SECONDS,
        max_retries=0,
    )


@pytest_asyncio.fixture(scope="module", autouse=True)
async def smoke_preflight(stub_server: str) -> None:
    """Prove model registration and the fallback target before failure tests."""
    assert stub_server == STUB_BASE_URL
    client = _gateway_client()
    try:
        models = await client.models.list()
        model_ids = {model.id for model in models.data}
        sys.stderr.write(f"SMOKE /v1/models: {sorted(model_ids)}\n")
        assert EXPECTED_MODEL_GROUPS <= model_ids

        response = await client.chat.completions.create(
            model="smoke-ok",
            messages=[{"role": "user", "content": "ping"}],
        )
        content = response.choices[0].message.content
        sys.stderr.write(
            f"SMOKE DIRECT smoke-ok: status=200 content={content!r}\n"
        )
        assert content == "OK"
    except Exception as exc:
        sys.stderr.write(
            f"SMOKE PREFLIGHT: FAIL {type(exc).__name__}: {exc}\n"
        )
        raise
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_timeout_failure_falls_back() -> None:
    response = await _gateway_client().chat.completions.create(
        model="smoke-timeout",
        messages=[{"role": "user", "content": "ping"}],
    )
    assert response.choices[0].message.content == "OK"


@pytest.mark.asyncio
async def test_429_failure_falls_back() -> None:
    response = await _gateway_client().chat.completions.create(
        model="smoke-429",
        messages=[{"role": "user", "content": "ping"}],
    )
    assert response.choices[0].message.content == "OK"


@pytest.mark.asyncio
async def test_all_providers_unavailable_surfaces_clean_error() -> None:
    with pytest.raises(APIStatusError) as excinfo:
        await _gateway_client().chat.completions.create(
            model="smoke-all-down",
            messages=[{"role": "user", "content": "ping"}],
        )
    assert 500 <= excinfo.value.status_code < 600
