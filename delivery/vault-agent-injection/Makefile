# Self-contained: everything this module needs is in this directory.
# Requires: docker, kind, kubectl, helm.
SHELL := /bin/bash
.DEFAULT_GOAL := help

KIND_CLUSTER ?= vault-agent-injection
# Pinned to the default node image of kind v0.33.0. Set it empty to use your kind version's default.
KIND_NODE_IMAGE ?= kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
# Images copied from your local docker into the kind node when present, so the test does not depend on
# Docker Hub rate limits. (The chart pulls hashicorp/vault 2.0.4 and vault-k8s 1.7.6 itself; docker save cannot export those multi-arch images here.)
PRELOAD_IMAGES ?= python:3.14.7-alpine

# A private kubeconfig so nothing here touches ~/.kube/config or your current context.
export KUBECONFIG := $(CURDIR)/.kube/config

.PHONY: help check-prereqs env cluster-up cluster-down test up down reset

help:
	@echo "make check-prereqs  verify the tools are installed and docker is reachable"
	@echo "make test           kind + Vault + injector: broken policy must fail, fixed must work"
	@echo "make up             same setup, cluster kept for poking (app deployed with the fixed policy)"
	@echo "make down           delete the kind cluster"
	@echo "make reset          down + remove .kube and .env"

check-prereqs:
	@fail=0; \
	for tool in docker kind kubectl helm; do \
	  if ! command -v $$tool >/dev/null 2>&1; then echo "missing: $$tool"; fail=1; fi; \
	done; \
	if command -v docker >/dev/null 2>&1 && ! docker info >/dev/null 2>&1; then \
	  echo "docker is installed but the daemon is not reachable (start Docker Desktop / colima)"; fail=1; \
	fi; \
	if [ $$fail -ne 0 ]; then exit 1; fi; \
	echo "prerequisites ok"

env: .env

.env:
	cp .env.example .env

cluster-up:
	@mkdir -p .kube
	@if kind get clusters 2>/dev/null | grep -qx '$(KIND_CLUSTER)'; then \
	  echo "kind cluster $(KIND_CLUSTER) already exists"; \
	  kind export kubeconfig --name $(KIND_CLUSTER) --kubeconfig $(KUBECONFIG); \
	else \
	  kind create cluster --name $(KIND_CLUSTER) --kubeconfig $(KUBECONFIG) --wait 120s \
	    $(if $(KIND_NODE_IMAGE),--image $(KIND_NODE_IMAGE),); \
	fi
	@for img in $(PRELOAD_IMAGES); do \
	  if docker image inspect $$img >/dev/null 2>&1; then \
	    echo "preloading $$img into the kind node"; \
	    arch=$$(docker image inspect --format '{{.Architecture}}' $$img); \
	    docker save --platform linux/$$arch $$img \
	      | docker exec --privileged -i $(KIND_CLUSTER)-control-plane ctr --namespace=k8s.io images import --digests --snapshotter=overlayfs - >/dev/null \
	      || echo "preload skipped for $$img (kubelet will pull it)"; \
	  fi; \
	done

cluster-down:
	-kind delete cluster --name $(KIND_CLUSTER) --kubeconfig $(KUBECONFIG)

# The e2e script contains the trap (broken policy fails) and the fix.
test: check-prereqs env
	@rc=0; $(MAKE) --no-print-directory cluster-up && ./scripts/e2e.sh || rc=$$?; \
	$(MAKE) --no-print-directory cluster-down; \
	exit $$rc

up: check-prereqs env cluster-up
	./scripts/e2e.sh
	@echo "kubeconfig: export KUBECONFIG=$(KUBECONFIG)"

down: cluster-down

reset: down
	rm -rf .kube .env
