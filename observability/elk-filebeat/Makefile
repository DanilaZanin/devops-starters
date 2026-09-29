SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE ?= docker compose

.PHONY: help check-prereqs up lint test logs down reset

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

check-prereqs: ## Verify docker, docker compose, python3 and vm.max_map_count
	@command -v docker >/dev/null || { echo "docker not found"; exit 1; }
	@docker compose version >/dev/null 2>&1 || { echo "docker compose v2 plugin not found"; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "docker daemon not reachable (is colima or Docker Desktop running?)"; exit 1; }
	@command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }
	@if [ "$$(uname -s)" = Linux ] && [ -r /proc/sys/vm/max_map_count ] && [ "$$(cat /proc/sys/vm/max_map_count)" -lt 262144 ]; then \
		echo "vm.max_map_count is below 262144, Elasticsearch may refuse to start:"; \
		echo "  sudo sysctl -w vm.max_map_count=262144"; exit 1; fi
	@echo "prereqs ok"

.env:
	cp .env.example .env

up: check-prereqs .env ## Start Elasticsearch, Kibana, Filebeat and two demo containers
	$(COMPOSE) up -d --build
	@echo "Kibana: http://127.0.0.1:5601 (user: elastic, password: ELASTIC_PASSWORD from .env)"

lint: .env ## Static checks that need no running containers
	python3 tests/check_compose.py

test: check-prereqs lint ## Config checks, then an end-to-end smoke run (wipes this module's data first)
	bash tests/cleanup_selftest.sh
	bash tests/smoke.sh

logs: ## Follow Filebeat's own log
	$(COMPOSE) logs -f filebeat

down: .env ## Stop containers, keep data
	$(COMPOSE) down

reset: .env ## Stop containers and delete all data (indices, Filebeat registry)
	$(COMPOSE) down -v --remove-orphans
