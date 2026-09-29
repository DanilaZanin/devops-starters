SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE ?= docker compose

.PHONY: help check-prereqs up lint test load query down reset

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

check-prereqs: ## Verify docker and docker compose are usable
	@command -v docker >/dev/null || { echo "docker not found"; exit 1; }
	@docker compose version >/dev/null 2>&1 || { echo "docker compose v2 plugin not found"; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "docker daemon not reachable (is colima or Docker Desktop running?)"; exit 1; }
	@command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }
	@echo "prereqs ok"

.env:
	cp .env.example .env

up: check-prereqs .env ## Start the S3 server, the Iceberg REST catalog and Trino, wait until Trino answers
	$(COMPOSE) up -d --build
	@for i in $$(seq 1 60); do $(COMPOSE) exec -T trino trino --execute 'SELECT 1' >/dev/null 2>&1 && exit 0; sleep 5; done; echo "Trino did not become ready within 5 minutes"; exit 1

lint: .env ## Static checks that need no running containers
	python3 tests/check_compose.py

test: check-prereqs lint ## Config checks, then an end-to-end smoke run including the duplicate-load trap
	bash tests/smoke.sh

load: up ## Load the sample data (safe to run repeatedly)
	$(COMPOSE) exec -T trino trino -f /sample_data/load_sample_data.sql

query: ## Run the example queries
	$(COMPOSE) exec -T trino trino -f /sample_data/example_queries.sql

down: .env ## Stop containers, keep data
	$(COMPOSE) down

reset: .env ## Stop containers and delete all data
	$(COMPOSE) down -v --remove-orphans
