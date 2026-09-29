SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE ?= docker compose

.PHONY: help check-prereqs up lint test down reset logs psql

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

check-prereqs: ## Verify docker, docker compose and python3 are usable
	@command -v docker >/dev/null || { echo "docker not found"; exit 1; }
	@docker compose version >/dev/null 2>&1 || { echo "docker compose v2 plugin not found"; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "docker daemon not reachable (is colima or Docker Desktop running?)"; exit 1; }
	@command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }
	@echo "prereqs ok"

.env:
	cp .env.example .env

up: check-prereqs .env ## Build and start the whole pipeline
	$(COMPOSE) up -d --build

lint: .env ## Static checks that need no running containers
	python3 tests/check_compose.py

test: check-prereqs lint ## Config checks, then an end-to-end smoke run (takes a few minutes)
	bash tests/smoke.sh

logs: ## Follow producer and Spark logs
	$(COMPOSE) logs -f producer spark-job

psql: ## Open psql on the results database
	$(COMPOSE) exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

down: .env ## Stop containers, keep data
	$(COMPOSE) down

reset: .env ## Stop containers and delete all data (Kafka, Postgres, Spark checkpoints)
	$(COMPOSE) down -v --remove-orphans
