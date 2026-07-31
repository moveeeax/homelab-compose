ENV_FILE ?= .env
COMPOSE = docker compose --env-file $(ENV_FILE)

.PHONY: help up down restart logs ps pull validate test backup restore

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

up: ## Bring the whole stack up
	$(COMPOSE) up -d

down: ## Stop and remove the stack (keeps named volumes)
	$(COMPOSE) down

restart: ## Restart all services
	$(COMPOSE) restart

logs: ## Follow logs
	$(COMPOSE) logs -f

ps: ## Show running services
	$(COMPOSE) ps

pull: ## Pull the latest images
	$(COMPOSE) pull

validate: ## Render compose config and run tests
	./scripts/validate.sh

test: ## Run the Python test suite
	python3 -m pytest -q

backup: ## Run an ad-hoc backup now
	$(COMPOSE) exec backup backup.sh

restore: ## Restore the latest snapshot (DEST=/restore)
	$(COMPOSE) exec backup restore.sh $(or $(DEST),/restore)
