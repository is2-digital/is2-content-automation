.PHONY: dev stage prod build down logs db-shell ps restart clean migrate migration \
       test lint format typecheck shell run-pipeline pipeline-status collect help

COMPOSE = docker compose -f docker-compose.yml
ARGS ?=

dev: ## Start development environment
	$(COMPOSE) -f docker-compose.dev.yml --env-file .env.dev up --build

stage: ## Start staging environment (detached)
	$(COMPOSE) -f docker-compose.stage.yml up -d --build

prod: ## Start production environment (detached)
	$(COMPOSE) -f docker-compose.prod.yml up -d --build

build: ## Build images without starting containers
	$(COMPOSE) build

down: ## Stop and remove all containers
	$(COMPOSE) down

logs: ## Tail logs for all services
	$(COMPOSE) logs -f

db-shell: ## Open psql shell in the postgres container
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-ica} -d $${POSTGRES_DB:-n8n_custom_data}

ps: ## Show running containers
	$(COMPOSE) ps

restart: ## Restart all services
	$(COMPOSE) restart

clean: ## Stop containers and remove volumes
	$(COMPOSE) down -v

migrate: ## Run database migrations to latest
	$(COMPOSE) exec app alembic -c alembic.ini upgrade head

migration: ## Create a new migration (usage: make migration msg="description")
	$(COMPOSE) exec app alembic -c alembic.ini revision --autogenerate -m "$(msg)"

test: ## Run tests (usage: make test ARGS="-k test_name")
	$(COMPOSE) exec app pytest $(ARGS)

lint: ## Run ruff linter
	$(COMPOSE) exec app ruff check . $(ARGS)

format: ## Run ruff formatter
	$(COMPOSE) exec app ruff format . $(ARGS)

typecheck: ## Run mypy type checker
	$(COMPOSE) exec app mypy ica $(ARGS)

shell: ## Open a bash shell in the app container
	$(COMPOSE) exec app bash

run-pipeline: ## Trigger the pipeline via API
	$(COMPOSE) exec app python -m ica run $(ARGS)

pipeline-status: ## Show pipeline run status
	$(COMPOSE) exec app python -m ica status $(ARGS)

collect: ## Run manual article collection
	$(COMPOSE) exec app python -m ica collect-articles $(ARGS)

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
