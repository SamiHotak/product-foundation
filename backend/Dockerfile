# syntax=docker/dockerfile:1
# Backend image. Targets:
#   dev  -> used by deploy/docker-compose.dev.yml (code is mounted, auto-reload)
#   prod -> used in production (phase 5): code copied in, non-root user

FROM python:3.12-slim AS base
# PIP_DEFAULT_TIMEOUT / PIP_RETRIES: on slow internet, wait longer and retry instead of failing.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10
WORKDIR /app
RUN useradd --create-home --uid 1000 app

FROM base AS dev
COPY requirements.txt requirements-dev.txt ./
# The cache mount keeps downloaded packages between builds, so a retry
# after a network error continues instead of downloading everything again.
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-dev.txt
COPY . .
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS prod
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt
COPY --chown=app:app . .
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 --start-period=15s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"
# --workers 2: one slow request can't block the API. --timeout-keep-alive 65: longer than
# Caddy's idle connection time (30 s), otherwise Caddy sometimes reuses a connection uvicorn
# just closed and the visitor gets a 502 (same bug as the dev "socket hang up").
# --forwarded-allow-ips=*: only Caddy can reach this port (no published port), and Caddy
# replaces any X-Forwarded-For a visitor sends, so client IPs (rate limits) can't be faked.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "65", "--proxy-headers", "--forwarded-allow-ips=*"]
