.PHONY: dev stage prod build down logs db-shell ps restart clean

COMPOSE = docker compose -f docker-compose.yml

dev: ## Start development environment
	$(COMPOSE) -f docker-compose.dev.yml up --build

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

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
