FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

FROM base AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --compile-bytecode

COPY src/ ./src/
RUN uv sync --frozen --no-dev --compile-bytecode

FROM base AS final

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY aegra.json ./
COPY src/ ./src/

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 2026

USER app

CMD ["aegra", "serve"]
