# Self-contained: everything this module needs is in this directory.
# Requires: docker, ansible-core, ansible-lint, molecule with the docker driver.
SHELL := /bin/bash
.DEFAULT_GOAL := help

# Molecule's Python docker SDK does not read docker contexts (colima, Docker
# Desktop). Point it at the active context's socket unless DOCKER_HOST is set.
ifeq ($(origin DOCKER_HOST),undefined)
DOCKER_CONTEXT_HOST := $(shell docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null)
ifneq ($(DOCKER_CONTEXT_HOST),)
export DOCKER_HOST := $(DOCKER_CONTEXT_HOST)
endif
endif

export ANSIBLE_NOCOLOR := 1
export PY_COLORS := 0

TRAP_LOG := .trap-broken.log
COLLECTIONS_STAMP := .collections/.installed

.PHONY: help check-prereqs deps lint trap fixed test up down reset

help:
	@echo "make check-prereqs  verify the tools are installed and docker is reachable"
	@echo "make test           lint + trap (broken must fail) + fixed (must pass, idempotent)"
	@echo "make up             converge the fixed role on two Ubuntu containers and keep them"
	@echo "make down           destroy the containers"
	@echo "make reset          destroy containers and delete downloaded collections and logs"

check-prereqs:
	@fail=0; \
	for tool in docker ansible-galaxy ansible-lint molecule; do \
	  if ! command -v $$tool >/dev/null 2>&1; then echo "missing: $$tool"; fail=1; fi; \
	done; \
	if command -v docker >/dev/null 2>&1 && ! docker info >/dev/null 2>&1; then \
	  echo "docker is installed but the daemon is not reachable (start Docker Desktop / colima)"; fail=1; \
	fi; \
	if command -v molecule >/dev/null 2>&1 && ! molecule drivers 2>/dev/null | grep -qi docker; then \
	  echo "molecule has no docker driver: pip install 'molecule-plugins[docker]' docker"; fail=1; \
	fi; \
	if [ $$fail -ne 0 ]; then exit 1; fi; \
	echo "prerequisites ok"

deps: $(COLLECTIONS_STAMP)

$(COLLECTIONS_STAMP): requirements.yml molecule/requirements.yml
	ansible-galaxy collection install -r molecule/requirements.yml -p .collections
	@touch $@

lint: deps
	ANSIBLE_COLLECTIONS_PATH=$(CURDIR)/.collections ansible-lint

# The trap: editing sshd_config (traps/broken_ssh_hardening.yml) must FAIL the
# `sshd -T` check, and it must fail for that reason (marker), not because the
# container did not start.
trap: check-prereqs deps
	@echo ">> trap: broken hardening must fail the sshd -T check"
	@rc=0; molecule test -s broken >$(TRAP_LOG) 2>&1 || rc=$$?; \
	if [ $$rc -eq 0 ]; then \
	  cat $(TRAP_LOG); echo "TRAP NOT REPRODUCED: the broken scenario passed"; exit 1; \
	fi; \
	if ! grep -q SSHD_TRAP_TRIGGERED $(TRAP_LOG); then \
	  cat $(TRAP_LOG); echo "broken scenario failed, but not on the sshd -T assertion"; exit 1; \
	fi; \
	echo "OK: broken hardening failed the sshd -T check as expected"

fixed: check-prereqs deps
	@echo ">> fixed: role must pass, twice (idempotence), on Ubuntu 22.04 and 24.04"
	molecule test -s default

test: check-prereqs lint trap fixed

up: check-prereqs deps
	molecule converge -s default
	@echo "log in with: molecule login -s default -h ubuntu-2204"

down:
	-molecule destroy -s default
	-molecule destroy -s broken

reset: down
	rm -rf .collections $(TRAP_LOG)
