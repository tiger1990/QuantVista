# syntax=docker/dockerfile:1
# QuantVista backend — ONE image, three roles (api / worker / beat) by command.
# Multi-stage, non-root, pinned slim base. Build context: ./backend

# ---- builder: install package + deps into an isolated prefix ----
FROM python:3.13-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

# ---- runtime ----
FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
# curl: used by the compose healthcheck to probe /api/v1/health.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 appuser
COPY --from=builder /install /usr/local
WORKDIR /app
# Alembic project (config + hand-written migrations + seeds) for the `migrate` role.
# Not part of the importable wheel (no __init__.py), so copy it explicitly.
COPY src/quantvista/db ./db
USER appuser
EXPOSE 8000
# Default role = api. worker/beat override `command` in docker-compose.
CMD ["uvicorn", "quantvista.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
