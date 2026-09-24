# Everyday commands. Run them from the repo root (PowerShell, cmd or WSL).
# Windows: install make once with `winget install ezwinports.make`.

COMPOSE = docker compose -f deploy/docker-compose.dev.yml
s ?=

.PHONY: help dev down logs ps restart test lint format api-client e2e check migrate migration seed example-job shell psql clean

help: ## Show all commands
	@echo "make dev          Start everything (first run takes a few minutes)"
	@echo "make down         Stop everything (data is kept)"
	@echo "make logs         Follow logs (one service: make logs s=backend)"
	@echo "make ps           Show running services"
	@echo "make restart      Restart services (one service: make restart s=worker)"
	@echo "make test         Run backend tests incl. real Postgres + Redis"
	@echo "make lint         ruff + mypy (backend), eslint + typecheck (frontend)"
	@echo "make format       Auto-format backend and frontend code"
	@echo "make api-client   Regenerate the typed frontend API client (after API changes)"
	@echo "make e2e          Browser tests (Playwright in Docker) against the running app"
	@echo "make check        Everything CI checks: lint, tests, API client, e2e"
	@echo "make migrate      Apply database migrations"
	@echo "make migration name=add_users   Create a migration from model changes"
	@echo "make seed         Load development data"
	@echo "make example-job  Run the example background job and show progress"
	@echo "make shell        Open a shell in the backend container"
	@echo "make psql         Open the Postgres console"
	@echo "make clean        Stop everything and DELETE local data"

dev: ## Build and start all services in the background
	$(COMPOSE) up -d --build --renew-anon-volumes
	@echo ""
	@echo "App:      http://localhost:3000"
	@echo "API docs: http://localhost:8000/api/docs"
	@echo "Emails:   http://localhost:8025"
	@echo "Logs:     make logs"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100 $(s)

ps:
	$(COMPOSE) ps

restart:
	$(COMPOSE) restart $(s)

test:
	$(COMPOSE) exec -e RUN_INTEGRATION=1 backend pytest --cov=app --cov-report=term-missing

lint:
	$(COMPOSE) exec backend ruff check .
	$(COMPOSE) exec backend ruff format --check .
	$(COMPOSE) exec backend mypy app tests
	$(COMPOSE) exec backend alembic check
	$(COMPOSE) exec frontend npm run lint
	$(COMPOSE) exec frontend npm run typecheck
	$(COMPOSE) exec frontend npm run format:check

format:
	$(COMPOSE) exec backend ruff check --fix .
	$(COMPOSE) exec backend ruff format .
	$(COMPOSE) exec frontend npm run format

api-client:
	$(COMPOSE) exec backend python -m app.scripts.export_openapi --out /frontend-api/openapi.json
	$(COMPOSE) exec frontend npm run api:generate

e2e:
	$(COMPOSE) --profile e2e run --rm --build e2e
	@echo "Report: frontend/playwright-report/index.html"

check: lint test api-client e2e
	@echo ""
	@echo "All checks passed. If 'git status' shows changes in frontend/lib/api, commit them."

migrate:
	$(COMPOSE) exec backend alembic upgrade head

migration:
	$(COMPOSE) exec backend alembic revision --autogenerate -m "$(name)"

seed:
	$(COMPOSE) exec backend python -m app.scripts.seed

example-job:
	$(COMPOSE) exec backend python -m app.scripts.run_example_job

shell:
	$(COMPOSE) exec backend bash

psql:
	$(COMPOSE) exec postgres psql -U app -d app

clean:
	$(COMPOSE) down -v --remove-orphans
