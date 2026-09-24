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
COPY . .
RUN npm run build

FROM base AS prod
ENV NODE_ENV=production
RUN addgroup -S app && adduser -S app -G app
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
COPY --from=build --chown=app:app /app/public ./public
USER app
EXPOSE 3000
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
