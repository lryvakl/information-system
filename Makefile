SHELL := /bin/bash
COMPOSE := docker compose
VENV := .venv
PY := $(VENV)/bin/python

.PHONY: help env up down restart logs ps clean dev test lint format simulate replay

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

env: ## Create .env with random secrets (keeps an existing one)
	@if [ -f .env ]; then echo ".env already exists"; else \
		cp .env.example .env; \
		for key in POSTGRES_PASSWORD GRAFANA_DB_PASSWORD API_DB_PASSWORD EXPORTER_DB_PASSWORD RABBITMQ_PASSWORD GRAFANA_ADMIN_PASSWORD; do \
			sed -i.bak "s|^$$key=.*|$$key=$$(openssl rand -hex 16)|" .env; \
		done; \
		sed -i.bak "s|^JWT_SECRET=.*|JWT_SECRET=$$(openssl rand -hex 32)|" .env; \
		sed -i.bak "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$$(openssl rand -base64 12 | tr -d '/+=')|" .env; \
		rm -f .env.bak; \
		echo "Created .env. Admin login: admin / $$(grep ^ADMIN_PASSWORD .env | cut -d= -f2)"; \
	fi

up: env ## Build and start the whole platform
	$(COMPOSE) up -d --build
	@echo "Open http://localhost:$${GATEWAY_PORT:-8080}  (admin password: grep ADMIN_PASSWORD .env)"

down: ## Stop containers (data is kept)
	$(COMPOSE) down

restart: ## Rebuild and restart application services
	$(COMPOSE) up -d --build auth race-engine race-control pitwall-api

logs: ## Follow application logs
	$(COMPOSE) logs -f race-engine race-control auth pitwall-api

ps: ## Show container status
	$(COMPOSE) ps

clean: ## Stop and DELETE all data volumes
	$(COMPOSE) down -v

simulate: ## Switch the race engine to synthetic races
	RACE_SOURCE=simulation $(COMPOSE) up -d race-engine

replay: ## Switch the race engine to real race replays (OpenF1)
	RACE_SOURCE=replay $(COMPOSE) up -d race-engine

dev: ## Create a local virtualenv with all services for tests/linting
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -e "libs/common[db,mq,web]" -e services/auth -e services/race_engine \
		-e services/race_control -e services/pitwall_api pytest httpx ruff

test: ## Run unit tests
	$(VENV)/bin/pytest

lint: ## Static checks
	$(VENV)/bin/ruff check . && $(VENV)/bin/ruff format --check .

format: ## Auto-format code
	$(VENV)/bin/ruff format . && $(VENV)/bin/ruff check --fix .
