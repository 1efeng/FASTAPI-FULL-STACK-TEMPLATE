FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml aegra.json ./
COPY src ./src
RUN pip install --no-cache-dir -e .

EXPOSE 2026

CMD ["aegra", "serve", "--host", "0.0.0.0", "--port", "2026"]
