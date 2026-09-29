SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE ?= docker compose

.PHONY: help check-prereqs up test demo down reset lint

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

check-prereqs: ## Verify docker, docker compose and uv are usable
	@command -v docker >/dev/null || { echo "docker not found"; exit 1; }
	@docker compose version >/dev/null 2>&1 || { echo "docker compose v2 plugin not found"; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "docker daemon not reachable (is colima or Docker Desktop running?)"; exit 1; }
	@command -v uv >/dev/null || { echo "uv not found, see https://docs.astral.sh/uv/"; exit 1; }
	@echo "prereqs ok"

.env:
	cp .env.example .env

up: check-prereqs .env ## Start Redis and the app on http://127.0.0.1:8000
	$(COMPOSE) up -d --build --wait

test: check-prereqs .env ## Run the trap tests (broken variant must fail, fixed must pass)
	$(COMPOSE) up -d --wait redis
	uv run pytest -v

demo: up ## Fire 50 parallel requests at a cold key and show how they were served
	curl -s -X DELETE http://127.0.0.1:8000/products/42/cache
	@echo
	seq 50 | xargs -P 50 -I{} curl -s -o /dev/null -D - http://127.0.0.1:8000/products/42 | grep -i '^x-cache' | tr -d '\r' | sort | uniq -c

lint: .env ## Static checks that need no running containers
	$(COMPOSE) config --quiet
	uv run python -m compileall -q app traps tests

down: ## Stop containers
	$(COMPOSE) down

reset: ## Stop containers and remove volumes and orphans
	$(COMPOSE) down -v --remove-orphans
