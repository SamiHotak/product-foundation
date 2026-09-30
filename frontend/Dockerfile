# syntax=docker/dockerfile:1
# Frontend image. Targets:
#   dev  -> deploy/docker-compose.dev.yml (code mounted, hot reload)
#   prod -> production (phase 5): standalone Next.js server, non-root
#   e2e  -> Playwright tests in Docker (make e2e, CI). No Node needed on Windows.

FROM node:24-alpine AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

FROM base AS deps
COPY package.json package-lock.json ./
# Cache mount + retries: survives slow or unstable internet, and a retry reuses downloads.
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund --fetch-retries=10 --fetch-retry-mintimeout=20000 \
    --fetch-retry-maxtimeout=120000 --fetch-timeout=600000

FROM deps AS dev
COPY . .
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]

FROM deps AS build
# Build-time settings (production deploy passes them, see .github/workflows/deploy.yml).
# API_INTERNAL_URL: where the Next.js server finds FastAPI (baked into its /api rewrite).
# NEXT_PUBLIC_SENTRY_*: browser + server error reports; empty = Sentry is not built in.
ARG API_INTERNAL_URL=http://backend:8000
ARG NEXT_PUBLIC_SENTRY_DSN=
ARG NEXT_PUBLIC_SENTRY_RELEASE=
ENV API_INTERNAL_URL=$API_INTERNAL_URL \
    NEXT_PUBLIC_SENTRY_DSN=$NEXT_PUBLIC_SENTRY_DSN \
    NEXT_PUBLIC_SENTRY_RELEASE=$NEXT_PUBLIC_SENTRY_RELEASE
COPY . .
RUN npm run build

FROM base AS prod
# HOSTNAME: Docker sets it to the container id, and Next.js would listen only on that name.
# KEEP_ALIVE_TIMEOUT: longer than Caddy's idle connection time (30 s, deploy/Caddyfile),
# otherwise Caddy sometimes reuses a connection Node just closed and the visitor gets a 502.
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000 \
    KEEP_ALIVE_TIMEOUT=65000
RUN addgroup -S app && adduser -S app -G app
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
COPY --from=build --chown=app:app /app/public ./public
USER app
EXPOSE 3000
# /robots.txt needs no database: the check says "Next.js runs", not "the API is up".
HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=20s \
  CMD node -e "fetch('http://127.0.0.1:3000/robots.txt').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]

# Playwright image: Chromium + all system libraries. Its version MUST match
# @playwright/test in package.json (update both together).
FROM mcr.microsoft.com/playwright:v1.63.0-noble AS e2e
WORKDIR /app
ENV CI=1 NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund --fetch-retries=10 --fetch-retry-mintimeout=20000 \
    --fetch-retry-maxtimeout=120000 --fetch-timeout=600000
COPY . .
CMD ["npx", "playwright", "test"]
