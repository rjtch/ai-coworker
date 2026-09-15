# Podman- and Docker-compatible image for AI Coworker API.
# Uses PyPI uv (no ghcr.io) and psycopg[binary] (no system libpq).

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH" \
    HOME=/home/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --root-user-action=ignore "uv==0.11.32" \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin app

COPY --chown=app:app pyproject.toml README.md uv.lock ./
COPY --chown=app:app src ./src

RUN uv sync --frozen --no-dev --no-editable \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "ai_coworker.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
