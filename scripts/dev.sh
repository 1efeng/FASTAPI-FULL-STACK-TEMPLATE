#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    echo ""
    echo "Shutting down..."
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null
    wait
    echo "Done."
}
trap cleanup EXIT INT TERM

# Clean up orphaned empty dirs and __pycache__ left by git mv / branch switches
find "$ROOT_DIR/backend/app" -type d -empty -not -path "*__pycache__*" -delete 2>/dev/null || true
find "$ROOT_DIR/backend/app" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Read POSTGRES_HOST_PORT from .env (default 5433)
PG_HOST_PORT=$(grep -E '^POSTGRES_HOST_PORT=' "$ROOT_DIR/.env" 2>/dev/null | cut -d= -f2 || true)
PG_HOST_PORT="${PG_HOST_PORT:-5433}"

# --- Database ---
echo "==> Starting database (docker compose up -d db)"
docker compose -f "$ROOT_DIR/compose.yml" -f "$ROOT_DIR/compose.override.yml" up -d --remove-orphans db

echo "==> Waiting for database..."
for i in $(seq 1 60); do
    if docker compose -f "$ROOT_DIR/compose.yml" -f "$ROOT_DIR/compose.override.yml" exec -T db pg_isready -U postgres -d app &>/dev/null; then
        echo "    Database is ready."
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "ERROR: Database did not become ready in time."
        exit 1
    fi
    sleep 1
done

# --- Backend setup ---
if [ ! -d "$BACKEND_DIR/.venv" ]; then
    echo "==> Installing backend dependencies (uv sync)"
    (cd "$BACKEND_DIR" && uv sync)
fi

# Override POSTGRES_PORT to match the host-mapped port for local backend
export POSTGRES_PORT="$PG_HOST_PORT"

echo "==> Running migrations and initializing data"
(cd "$BACKEND_DIR" && \
    uv run python scripts/prestart.py && \
    uv run alembic upgrade head && \
    uv run python scripts/init_data.py)

# --- Frontend setup ---
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "==> Installing frontend dependencies (bun install)"
    (cd "$FRONTEND_DIR" && bun install)
fi

# --- Start both ---
echo ""
echo "==> Starting backend (http://localhost:8000) and frontend (http://localhost:5173)"
echo "    Press Ctrl+C to stop both."
echo ""

(cd "$BACKEND_DIR" && uv run fastapi dev app/main.py) &
BACKEND_PID=$!

(cd "$FRONTEND_DIR" && bun run dev) &
FRONTEND_PID=$!

wait
