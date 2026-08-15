#!/usr/bin/env bash
# LiteLLM fallback failure-injection smoke.
#
# Brings up the LiteLLM gateway with the hermetic failure-injection config
# (infra/litellm/config.fallback-smoke.yaml), then runs the integration test.
# The pytest fixture is the sole owner of the failure_injector stub.
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
SMOKE_WALL_CLOCK_SECONDS="${LITELLM_FAILURE_SMOKE_WALL_CLOCK_SECONDS:-120}"
GATEWAY_PID=""
cd "$(dirname "$0")/../.."

print_diagnostics() {
  echo ">> pytest result: exit ${1}" >&2
  echo ">> LiteLLM gateway recent logs" >&2
  docker logs --tail 100 "${SMOKE_GATEWAY_NAME}" 2>&1 || true
  echo ">> LiteLLM gateway container status" >&2
  docker inspect --format '{{.State.Status}} exit={{.State.ExitCode}}' \
    "${SMOKE_GATEWAY_NAME}" 2>&1 || true
  echo ">> /v1/models result" >&2
  docker compose exec -T backend sh -c \
    "curl -sS -w '\\nHTTP_STATUS=%{http_code}\\n' \
    -H 'Authorization: Bearer ${LITELLM_MASTER_KEY:-sk-local-master}' \
    http://${SMOKE_GATEWAY_NAME}:4000/v1/models" 2>&1 || true
  echo ">> direct smoke-ok result" >&2
  docker compose exec -T backend sh -c \
    "curl -sS -w '\\nHTTP_STATUS=%{http_code}\\n' \
    -H 'Authorization: Bearer ${LITELLM_MASTER_KEY:-sk-local-master}' \
    -H 'Content-Type: application/json' \
    -d '{\"model\":\"smoke-ok\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}]}' \
    http://${SMOKE_GATEWAY_NAME}:4000/v1/chat/completions" 2>&1 || true
}

cleanup() {
  status=$?
  set +e
  if [[ "${status}" -ne 0 ]]; then
    print_diagnostics "${status}"
  fi
  if [[ -n "${GATEWAY_PID}" ]]; then
    kill "${GATEWAY_PID}" 2>/dev/null || true
    wait "${GATEWAY_PID}" 2>/dev/null || true
  fi
  docker rm -f "${SMOKE_GATEWAY_NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 124' INT TERM

echo ">> starting stack"
docker compose build backend
docker compose up -d db redis backend
# The production image intentionally excludes tests; copy only the integration
# fixtures needed by this hermetic smoke into the ephemeral backend container.
docker compose cp backend/tests backend:/app/backend/tests

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

echo ">> running failure-injection tests (wall clock: ${SMOKE_WALL_CLOCK_SECONDS}s)"
SMOKE_TEST_CMD=(
  docker compose exec -T
  -e RUN_LITELLM_FAILURE_INTEGRATION=1
  -e "FAILURE_INJECTOR_PORT=${STUB_PORT}"
  -e "LITELLM_BASE_URL=http://${SMOKE_GATEWAY_NAME}:4000"
  -e "LITELLM_FAILURE_SMOKE_CLIENT_TIMEOUT_SECONDS=20"
  backend sh -c
  'LITELLM_SERVICE_KEY="${LITELLM_MASTER_KEY:-sk-local-master}" bash scripts/tests-start.sh -s tests/integration/test_litellm_failures.py'
)
set +e
if command -v timeout >/dev/null 2>&1; then
  timeout --foreground "${SMOKE_WALL_CLOCK_SECONDS}s" "${SMOKE_TEST_CMD[@]}"
  smoke_status=$?
elif command -v python3 >/dev/null 2>&1; then
  python3 - "${SMOKE_WALL_CLOCK_SECONDS}" "${SMOKE_TEST_CMD[@]}" <<'PY'
import os
import signal
import subprocess
import sys

seconds = float(sys.argv[1])
process = subprocess.Popen(sys.argv[2:], start_new_session=True)
try:
    process.wait(timeout=seconds)
except subprocess.TimeoutExpired:
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    raise SystemExit(124)
raise SystemExit(process.returncode)
PY
  smoke_status=$?
else
  echo ">> no reliable watchdog is available; smoke is ENVIRONMENT_BLOCKED" >&2
  smoke_status=125
fi
set -e

if [[ "${smoke_status}" -ne 0 ]]; then
  exit "${smoke_status}"
fi
