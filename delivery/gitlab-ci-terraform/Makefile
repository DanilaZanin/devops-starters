# Self-contained: everything this module needs is in this directory.
# Requires: python3 (3.12+), terraform. docker is needed only for `make up`.
SHELL := /bin/bash
.DEFAULT_GOAL := help

VENV := .venv
BIN := $(VENV)/bin
IMAGE := gitlab-ci-terraform-demo:local
CONTAINER := gitlab-ci-terraform-demo

.PHONY: help check-prereqs venv lint traps validate test lock up down reset

help:
	@echo "make check-prereqs  verify python3 and terraform are installed"
	@echo "make test           lint + app tests + trap tests (broken pipelines must fail) + terraform validate"
	@echo "make lock           regenerate terraform/.terraform.lock.hcl for linux and macOS (needs network)"
	@echo "make up             build the demo image and run it on 127.0.0.1:8080"
	@echo "make down           stop the demo container"
	@echo "make reset          down + remove .venv, caches and terraform/.terraform"

check-prereqs:
	@fail=0; \
	for tool in python3 terraform; do \
	  if ! command -v $$tool >/dev/null 2>&1; then echo "missing: $$tool"; fail=1; fi; \
	done; \
	if ! command -v docker >/dev/null 2>&1; then echo "note: docker not found (only needed for make up)"; fi; \
	if [ $$fail -ne 0 ]; then exit 1; fi; \
	echo "prerequisites ok"

venv: $(VENV)/.installed

$(VENV)/.installed: requirements-dev.txt
	python3 -m venv $(VENV)
	$(BIN)/pip install --quiet --upgrade pip
	$(BIN)/pip install --quiet -r requirements-dev.txt
	@touch $@

lint: venv
	$(BIN)/ruff check app tests checks
	terraform fmt -check -recursive terraform

# App tests plus the trap tests in tests/test_traps.py: the shipped pipeline
# must pass the policy and every broken variant must be reported.
traps: venv
	$(BIN)/pytest -q

validate:
	terraform -chdir=terraform init -backend=false -input=false -lockfile=readonly
	terraform -chdir=terraform validate

test: check-prereqs lint traps validate

lock:
	terraform -chdir=terraform init -backend=false -input=false
	terraform -chdir=terraform providers lock -platform=linux_amd64 -platform=linux_arm64 -platform=darwin_arm64

up:
	docker build -t $(IMAGE) app
	-docker rm -f $(CONTAINER) >/dev/null 2>&1
	docker run -d --name $(CONTAINER) -p 127.0.0.1:8080:8080 $(IMAGE)
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
	  if curl -fsS http://127.0.0.1:8080/health; then echo; exit 0; fi; sleep 1; \
	done; echo "health check failed"; docker logs $(CONTAINER); exit 1

down:
	-docker rm -f $(CONTAINER)

reset: down
	rm -rf $(VENV) .pytest_cache .ruff_cache terraform/.terraform
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
