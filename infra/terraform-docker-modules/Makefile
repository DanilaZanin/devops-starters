# Self-contained: everything this module needs is in this directory.
# Requires: terraform >= 1.7 (native tests with mock providers). docker is
# needed only for `make up`. tflint is used if installed.
SHELL := /bin/bash
.DEFAULT_GOAL := help

MODULES := modules/security-group modules/network modules/compute examples/docker-sandbox
EXAMPLE := examples/docker-sandbox

# The docker provider reads DOCKER_HOST; colima and Docker Desktop keep their
# socket in the active docker context. Use it unless DOCKER_HOST is set.
ifeq ($(origin DOCKER_HOST),undefined)
DOCKER_CONTEXT_HOST := $(shell docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null)
ifneq ($(DOCKER_CONTEXT_HOST),)
export DOCKER_HOST := $(DOCKER_CONTEXT_HOST)
endif
endif

.PHONY: help check-prereqs fmt lint validate unit trap test up down reset

help:
	@echo "make check-prereqs  verify terraform (>= 1.7) is installed"
	@echo "make test           fmt, validate, terraform test for every module, trap (broken must fail)"
	@echo "make up             apply examples/docker-sandbox on your local docker (2 nginx containers)"
	@echo "make down           destroy it"
	@echo "make reset          down + remove .terraform directories and local state"

check-prereqs:
	@if ! command -v terraform >/dev/null 2>&1; then echo "missing: terraform"; exit 1; fi
	@v=$$(terraform version | head -1 | sed -E 's/^Terraform v//'); \
	if [ "$$(printf '%s\n1.7.0\n' "$$v" | sort -V | head -1)" != "1.7.0" ]; then \
	  echo "terraform $$v is too old: native tests with mock providers need >= 1.7"; exit 1; \
	fi; \
	echo "terraform $$v ok"
	@if ! command -v docker >/dev/null 2>&1; then echo "note: docker not found (only needed for make up)"; fi
	@if ! command -v tflint >/dev/null 2>&1; then echo "note: tflint not found (lint step will be skipped)"; fi

fmt:
	terraform fmt -check -recursive -diff

lint:
	@if command -v tflint >/dev/null 2>&1; then \
	  tflint --recursive --config=$(CURDIR)/.tflint.hcl; \
	else \
	  echo "tflint not installed, skipping"; \
	fi

validate:
	@set -e; for d in $(MODULES); do \
	  echo ">> validate $$d"; \
	  terraform -chdir=$$d init -backend=false -input=false >/dev/null; \
	  terraform -chdir=$$d validate; \
	done

unit:
	@set -e; for d in $(MODULES); do \
	  echo ">> terraform test $$d"; \
	  terraform -chdir=$$d test; \
	done

# The trap: the compute module without its per-replica port offset must fail
# its own tests, and only on the distinct-host-ports assertion.
trap:
	./traps/port-offset.sh

test: check-prereqs fmt lint validate unit trap

up: check-prereqs
	terraform -chdir=$(EXAMPLE) init -input=false
	terraform -chdir=$(EXAMPLE) apply -input=false -auto-approve
	@for url in $$(terraform -chdir=$(EXAMPLE) output -json urls | tr -d '[]"' | tr ',' ' '); do \
	  echo "$$url"; curl -fsSI "$$url" | head -1 || echo "  not answering yet"; \
	done

down:
	-terraform -chdir=$(EXAMPLE) destroy -input=false -auto-approve

reset: down
	find . -name .terraform -type d -prune -exec rm -rf {} +
	find . \( -name 'terraform.tfstate*' -o -name '.terraform.lock.hcl' -not -path './$(EXAMPLE)/*' \) -type f -delete
