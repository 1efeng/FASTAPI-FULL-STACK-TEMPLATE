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
SMOKE_GATEWAY_NAME="travel-agent-litellm-fallback-$$"
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
# The production image intentionally excludes tests; copy only the integration
# fixtures needed by this hermetic smoke into the ephemeral backend container.
docker compose cp backend/tests backend:/app/backend/tests

echo ">> starting failure-injection stub on :${STUB_PORT}"
docker compose exec -T backend sh -c \
  "cd /app/backend/tests/integration && uvicorn failure_injector:app --host 0.0.0.0 --port ${STUB_PORT} --log-level warning" &
STUB_PID=$!

for _ in {1..30}; do
  if docker compose exec -T backend sh -c \
    "curl -fsS http://127.0.0.1:${STUB_PORT}/health" \
    >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! docker compose exec -T backend sh -c \
  "curl -fsS http://127.0.0.1:${STUB_PORT}/health" \
  >/dev/null 2>&1; then
  echo ">> failure injector did not become ready" >&2
  exit 1
fi

echo ">> starting LiteLLM with config.fallback-smoke.yaml"
docker compose run --rm --no-deps \
  --name "${SMOKE_GATEWAY_NAME}" \
  -e "STUB_BASE_URL=${STUB_BASE_URL}" \
  -v "$(pwd)/infra/litellm/config.fallback-smoke.yaml:/app/config.fallback-smoke.yaml:ro" \
  litellm --config /app/config.fallback-smoke.yaml --port 4000 &
GATEWAY_PID=$!

for _ in {1..60}; do
  if docker compose exec -T backend sh -c \
    "curl -fsS http://${SMOKE_GATEWAY_NAME}:4000/health/liveliness" \
    >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! docker compose exec -T backend sh -c \
  "curl -fsS http://${SMOKE_GATEWAY_NAME}:4000/health/liveliness" \
  >/dev/null 2>&1; then
  echo ">> LiteLLM smoke gateway did not become ready" >&2
  exit 1
fi

echo ">> running failure-injection tests"
docker compose exec -T \
  -e RUN_LITELLM_FAILURE_INTEGRATION=1 \
  -e "FAILURE_INJECTOR_PORT=${STUB_PORT}" \
  -e "LITELLM_BASE_URL=http://${SMOKE_GATEWAY_NAME}:4000" \
  backend sh -c \
  'LITELLM_SERVICE_KEY="${LITELLM_MASTER_KEY:-sk-local-master}" bash scripts/tests-start.sh tests/integration/test_litellm_failures.py'
