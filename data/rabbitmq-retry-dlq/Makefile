SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE ?= docker compose

.PHONY: help check-prereqs up test down reset demo logs lint

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

up: check-prereqs .env ## Start RabbitMQ and the consumer
	$(COMPOSE) up -d --build --wait

test: check-prereqs .env ## Run the trap tests (broken variant must fail, fixed must pass)
	$(COMPOSE) up -d --wait rabbitmq
	uv run pytest -v

demo: up ## Publish sample messages and show where they ended up
	$(COMPOSE) run --rm --no-deps consumer python -m app.demo
	sleep 15
	$(COMPOSE) exec rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged

logs: ## Follow the consumer log
	$(COMPOSE) logs -f consumer

lint: .env ## Static checks that need no running containers
	$(COMPOSE) config --quiet
	uv run python -m compileall -q app traps tests

down: ## Stop containers, keep data
	$(COMPOSE) down

reset: ## Stop containers and delete all data (queues, volumes)
	$(COMPOSE) down -v --remove-orphans
