# Travel Agent Runtime

This directory is the self-contained Aegra runtime for the repository. Its
layout starts from the Aegra 0.10.4 `react-agent` template, with the sample
calculator graph replaced by the application's `travel_planning` LangChain
agent and governance middleware.

## Responsibilities

- Aegra owns Agent Protocol v2, checkpoints, streaming, worker leases,
  recovery and drain behavior.
- `travel_runtime.graph` owns the LangChain agent definition.
- `travel_runtime.auth` validates the JWT issued by FastAPI.
- `travel_runtime.middleware` and `travel_runtime.db` own skill loading and
  write-side-effect idempotency.

The exported graph deliberately has no checkpointer. Aegra injects its
PostgreSQL checkpointer and store when executing a run.

## Local setup

```bash
cd agent-runtime
cp .env.example .env
# Set LLM_API_KEY, LLM_BASE_URL and the same SECRET_KEY as FastAPI.
uv sync --frozen
```

For the usual host development loop, start PostgreSQL first and run Aegra with
hot reload. `--no-db-check` tells the CLI to use the connection already
configured in `agent-runtime/.env` instead of managing another database:

```bash
docker compose -f ../compose.yml -f ../compose.override.yml up -d db
uv run aegra dev --no-db-check
```

Set `POSTGRES_PORT` to the root Compose host port when using that database. For
a single-process development run, keep `REDIS_BROKER_ENABLED=false`.

The CLI-generated Compose file is adapted into a two-instance recovery demo:

```bash
docker compose up --build
```

It starts PostgreSQL on `POSTGRES_HOST_PORT` (default `15433`), Redis on
`REDIS_HOST_PORT` (default `16380`), runs Aegra migrations once, then starts
two Aegra instances on ports `2026` and `2027`. Both instances share the same
PostgreSQL and Redis services. Do not start this isolated validation stack at
the same time as another stack using those host ports.

For the 1w-DAU production baseline, use the repository-level production stack
instead. It keeps FastAPI and Aegra in separate containers while sharing the
application PostgreSQL and Redis, and starts one Aegra instance behind
Traefik:

```bash
cd ..
docker compose -f compose.yml -f compose.production.yml up -d --build
```

Set `AGENT_DOMAIN` and `VITE_AEGRA_URL` in the root `.env` to the public HTTPS
host used by the Agent Protocol endpoint. Scale Aegra only after measuring
queue depth and concurrent SSE connections.

Useful checks:

```bash
uv run aegra version
uv run aegra db current
curl http://localhost:2026/health
```

## Project structure

```text
agent-runtime/
├── aegra.json
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── docker-compose.yml
└── src/travel_runtime/
    ├── graph.py
    ├── auth.py
    ├── middleware.py
    ├── db.py
    └── skills/travel-planning/SKILL.md
```

The official template also generates `state.py`, `context.py`, `prompts.py`,
`tools.py` and `utils.py`. They are not copied here because `create_agent`
already supplies the current state and agent loop, the model configuration is
small, and there are no standalone business tools yet. Add those modules only
when they acquire an independent responsibility.
