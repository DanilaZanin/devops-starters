# Self-contained: everything this module needs is in this directory.
# Requires: docker, kind, kubectl, helm, kubeconform.
SHELL := /bin/bash
.DEFAULT_GOAL := help

KIND_CLUSTER ?= gitops-argocd
# Pinned to the default node image of kind v0.33.0. Set it empty to use your kind version's default,
# e.g. make test KIND_NODE_IMAGE=kindest/node:v1.36.4
KIND_NODE_IMAGE ?= kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
# Kubernetes version the manifests are validated against (kubeconform).
KUBERNETES_VERSION ?= 1.37.0
CRD_SCHEMAS ?= https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json

# A private kubeconfig so nothing here touches ~/.kube/config or your current context.
export KUBECONFIG := $(CURDIR)/.kube/config

CHART := charts/demo-app
# The chart's image, read from values.yaml. If it is already in your local docker, it is
# copied into the kind node so the test does not depend on a Docker Hub pull (rate limits).
IMAGE_REF := $(shell awk '/^  repository:/{r=$$2} /^  tag:/{gsub(/"/,"",$$2); t=$$2} END{print r":"t}' $(CHART)/values.yaml)
ENVS := staging production

.PHONY: help check-prereqs lint cluster-up cluster-down trap test up down reset

help:
	@echo "make check-prereqs  verify the tools are installed and docker is reachable"
	@echo "make lint           helm lint, kubeconform (strict, with Argo CRD schemas), repoURL check"
	@echo "make test           lint + trap on a throwaway kind cluster (deleted afterwards)"
	@echo "make up             kind cluster with the staging release installed, kept for poking"
	@echo "make down           delete the kind cluster"
	@echo "make reset          down + remove the private kubeconfig"

check-prereqs:
	@fail=0; \
	for tool in docker kind kubectl helm kubeconform; do \
	  if ! command -v $$tool >/dev/null 2>&1; then echo "missing: $$tool"; fail=1; fi; \
	done; \
	if command -v docker >/dev/null 2>&1 && ! docker info >/dev/null 2>&1; then \
	  echo "docker is installed but the daemon is not reachable (start Docker Desktop / colima)"; fail=1; \
	fi; \
	if [ $$fail -ne 0 ]; then exit 1; fi; \
	echo "prerequisites ok"

lint:
	@set -eo pipefail; \
	for e in $(ENVS); do \
	  echo ">> helm lint ($$e)"; \
	  helm lint --strict $(CHART) -f environments/$$e/values.yaml; \
	  echo ">> kubeconform: rendered chart ($$e, ingress on)"; \
	  helm template demo $(CHART) -f environments/$$e/values.yaml --set ingress.enabled=true \
	    | kubeconform -strict -summary -kubernetes-version $(KUBERNETES_VERSION) -; \
	done; \
	echo ">> the pod template must carry checksum/config"; \
	helm template demo $(CHART) | grep -q 'checksum/config' || { echo "checksum/config is missing from the Deployment"; exit 1; }; \
	echo ">> kubeconform: ArgoCD manifests (with CRD schemas)"; \
	kubeconform -strict -summary -kubernetes-version $(KUBERNETES_VERSION) \
	  -schema-location default -schema-location '$(CRD_SCHEMAS)' apps bootstrap; \
	echo ">> one repoURL for every Application"; \
	n=$$(grep -rhE '^[[:space:]]*repoURL:' apps bootstrap | sort -u | wc -l | tr -d ' '); \
	if [ "$$n" != 1 ]; then echo "expected one distinct repoURL, found $$n (use scripts/set-repo-url.sh)"; exit 1; fi

cluster-up:
	@mkdir -p .kube
	@if kind get clusters 2>/dev/null | grep -qx '$(KIND_CLUSTER)'; then \
	  echo "kind cluster $(KIND_CLUSTER) already exists"; \
	  kind export kubeconfig --name $(KIND_CLUSTER) --kubeconfig $(KUBECONFIG); \
	else \
	  kind create cluster --name $(KIND_CLUSTER) --kubeconfig $(KUBECONFIG) --wait 120s \
	    $(if $(KIND_NODE_IMAGE),--image $(KIND_NODE_IMAGE),); \
	fi
	@if docker image inspect $(IMAGE_REF) >/dev/null 2>&1; then \
	  echo "preloading $(IMAGE_REF) into the kind node"; \
	  arch=$$(docker image inspect --format '{{.Architecture}}' $(IMAGE_REF)); \
	  docker save --platform linux/$$arch $(IMAGE_REF) \
	    | docker exec --privileged -i $(KIND_CLUSTER)-control-plane ctr --namespace=k8s.io images import --digests --snapshotter=overlayfs - >/dev/null \
	    || echo "preload skipped (kubelet will pull the image)"; \
	fi

cluster-down:
	-kind delete cluster --name $(KIND_CLUSTER) --kubeconfig $(KUBECONFIG)

# The trap: a broken chart (no checksum/config) must leave the pod stale after
# `helm upgrade`, the shipped chart must recreate it. See traps/configmap-rollout.sh.
trap: cluster-up
	./traps/configmap-rollout.sh

test: check-prereqs lint
	@rc=0; $(MAKE) --no-print-directory trap || rc=$$?; \
	$(MAKE) --no-print-directory cluster-down; \
	exit $$rc

up: check-prereqs cluster-up
	helm upgrade --install demo $(CHART) -f environments/staging/values.yaml \
	  -n demo-app-staging --create-namespace --wait --timeout 180s
	kubectl -n demo-app-staging get pods
	@echo "kubeconfig: export KUBECONFIG=$(KUBECONFIG)"

down: cluster-down

reset: down
	rm -rf .kube
