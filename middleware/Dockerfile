# syntax=docker/dockerfile:1.7
# Saleor-Odoo Bridge middleware. Multi-stage:
#   1. builder — install deps + project into /opt/venv (no uv at runtime).
#   2. dev     — same builder image; live-reload via compose volume (dev only).
#   3. prod    — slim runtime, copy /opt/venv + src, non-root, no source mount.

ARG PYTHON_VERSION=3.12.7

# ─── builder ─────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN pip install uv

# Deps layer — copy only pyproject for caching.
COPY pyproject.toml ./
RUN uv venv /opt/venv && \
    uv pip install --python /opt/venv/bin/python \
    "fastapi[standard]>=0.115" \
    "uvicorn[standard]>=0.32" \
    "httpx>=0.27" \
    "joserfc>=1.0" \
    "redis>=5.2" \
    "pydantic>=2.10" \
    "pydantic-settings>=2.7" \
    "python-multipart>=0.0.12" \
    "structlog>=24.4" \
    "gql[httpx]>=3.5" \
    "arq>=0.26" \
    "tenacity>=9.0" \
    "typer>=0.12" \
    "rich>=13.0"

# Project source + editable install (so the package resolves via venv).
COPY src ./src
COPY tests ./tests
RUN uv pip install --python /opt/venv/bin/python -e .

# ─── dev ─────────────────────────────────────────────────────────────────
# Used by odoo-saleor-integration/docker-compose.yml; compose mounts ./src
# read-only over /app/src for live editing.
FROM builder AS dev

ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["uvicorn", "saleor_bridge.main:app", "--host", "0.0.0.0", "--port", "8080"]

# ─── prod ────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-bookworm AS prod

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1001 app && \
    useradd  --system --uid 1001 --gid app --home /app --shell /usr/sbin/nologin app

COPY --from=builder --chown=app:app /opt/venv /opt/venv
COPY --from=builder --chown=app:app /app/src  /app/src
COPY --chown=app:app pyproject.toml /app/

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["uvicorn", "saleor_bridge.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2", "--no-access-log"]
