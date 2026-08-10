#!/usr/bin/env bash
# LiteLLM fallback failure-injection smoke.
#
# Brings up the LiteLLM gateway with the hermetic failure-injection config
# (infra/litellm/config.fallback-smoke.yaml) plus the local failure_injector
# stub, then runs backend/tests/integration/test_litellm_failures.py.
#
# Prereqs: docker compose, .env, and the stack images built.
#   ./backend/scripts/litellm-failure-smoke.sh
#
# Networking: the stub runs inside the backend container; LiteLLM reaches it at
# http://backend:STUB_PORT on the compose default network.
#
# Optional env: FAILURE_INJECTOR_PORT (default 9000).

set -euo pipefail

STUB_PORT="${FAILURE_INJECTOR_PORT:-9000}"
STUB_BASE_URL="http://backend:${STUB_PORT}"
cd "$(dirname "$0")/../.."

cleanup() {
  # Stop the background gateway + exec'd stub.
  kill "${GATEWAY_PID}" "${STUB_PID}" 2>/dev/null || true
  docker compose exec -T backend sh -c \
    "pkill -f 'failure_injector:app' || true" 2>/dev/null || true
}
trap cleanup EXIT

echo ">> starting stack"
docker compose build backend
docker compose up -d db redis backend

echo ">> starting failure-injection stub on :${STUB_PORT}"
docker compose exec -T backend sh -c \
  "cd /app/backend/tests/integration && uvicorn failure_injector:app --host 0.0.0.0 --port ${STUB_PORT} --log-level warning" &
STUB_PID=$!

echo ">> starting LiteLLM with config.fallback-smoke.yaml"
docker compose run --rm --no-deps \
  -e "STUB_BASE_URL=${STUB_BASE_URL}" \
  -v "$(pwd)/infra/litellm/config.fallback-smoke.yaml:/app/config.fallback-smoke.yaml:ro" \
  litellm --config /app/config.fallback-smoke.yaml --port 4000 &
GATEWAY_PID=$!

echo ">> running failure-injection tests"
docker compose exec -T \
  -e RUN_LITELLM_FAILURE_INTEGRATION=1 \
  -e "FAILURE_INJECTOR_PORT=${STUB_PORT}" \
  -e LITELLM_BASE_URL=http://litellm:4000 \
  backend bash scripts/tests-start.sh tests/integration/test_litellm_failures.py
