DOMAIN := max_notify
COMPONENT_DIR := custom_components/$(DOMAIN)

.PHONY: help test test-matrix act-push act-release tag-release version extract-notes \
	1 2 3 4 5 6 7 8 9 10 12 16 32

help:
	@echo "Targets:"
	@echo "  make test                 — pytest в .venv (если есть)"
	@echo "  make test-matrix          — tests/test-matrix.sh (несколько HA venv)"
	@echo "  make act-push [N]         — локально: act push → ci.yml (нужен GITHUB_TOKEN / gh auth)"
	@echo "  make act-release [N]      — локально: act push → release.yml (нужен GITHUB_TOKEN)"
	@echo "  make version vX.Y.Z       — обновить version в manifest.json"
	@echo "  make extract-notes [vX.Y.Z] — вытащить секцию из CHANGELOG.md"
	@echo "  make tag-release          — аннотированный тег из manifest + push origin"

test:
	@if [ -x .venv/bin/python ]; then \
		.venv/bin/python -m pytest -q; \
	elif command -v pytest >/dev/null 2>&1; then \
		pytest -q; \
	else \
		echo "test: нет .venv/bin/python и pytest в PATH"; exit 1; \
	fi

test-matrix:
	@bash tests/test-matrix.sh

ACT_PLATFORM := -P ubuntu-latest=catthehacker/ubuntu:full-latest
ACT_CONCURRENT_JOBS ?= 2
ACT_ARTIFACT_PATH ?= $(CURDIR)/.artifacts
ACT_FLAGS = --pull=false --rebuild=false --artifact-server-path $(ACT_ARTIFACT_PATH) --concurrent-jobs

# Usage: make act-push [N]
# HACS action нужен GitHub API-токен: GITHUB_TOKEN=... или `gh auth login`.
act-push:
	@set -euo pipefail; \
	git rev-parse HEAD >/dev/null 2>&1 || { echo "act-push: нужен хотя бы один git commit"; exit 1; }; \
	token="$${GITHUB_TOKEN:-}"; \
	if [ -z "$$token" ] && command -v gh >/dev/null 2>&1; then token="$$(gh auth token 2>/dev/null || true)"; fi; \
	if [ -z "$$token" ]; then echo "act-push: задайте GITHUB_TOKEN или выполните gh auth login"; exit 1; fi; \
	mkdir -p "$(ACT_ARTIFACT_PATH)"; \
	chmod +x scripts/run-hassfest.sh; \
	jobs='$(word 2,$(MAKECMDGOALS))'; \
	jobs="$${jobs:-$(ACT_CONCURRENT_JOBS)}"; \
	case "$$jobs" in ''|*[!0-9]*|0*) echo "act-push: concurrent jobs must be a positive integer (got '$$jobs')"; exit 1;; esac; \
	act push $(ACT_PLATFORM) $(ACT_FLAGS) $$jobs -W .github/workflows/ci.yml \
		-s GITHUB_TOKEN=$$token

# Usage: make act-release [N]
# Событие тега = version из manifest.json (нужна секция # [vX.Y.Z] в CHANGELOG.md).
# Под act: HACS и публикация Release пропускаются (тега ещё нет на GitHub) —
# проверяются hassfest, extract notes и сборка zip.
act-release:
	@set -euo pipefail; \
	git rev-parse HEAD >/dev/null 2>&1 || { echo "act-release: нужен хотя бы один git commit"; exit 1; }; \
	token="$${GITHUB_TOKEN:-}"; \
	if [ -z "$$token" ] && command -v gh >/dev/null 2>&1; then token="$$(gh auth token 2>/dev/null || true)"; fi; \
	if [ -z "$$token" ]; then echo "act-release: задайте GITHUB_TOKEN или выполните gh auth login"; exit 1; fi; \
	mkdir -p "$(ACT_ARTIFACT_PATH)"; \
	chmod +x scripts/extract-release-notes.sh scripts/resolve-release-tag.sh scripts/run-hassfest.sh; \
	tag="v$$(python3 -c "import json; print(json.load(open('$(COMPONENT_DIR)/manifest.json'))['version'])")"; \
	bash scripts/extract-release-notes.sh --stdout "$$tag" >/dev/null; \
	printf '%s\n' "{\"ref\":\"refs/tags/$$tag\",\"ref_name\":\"$$tag\"}" > .github/act/tag-push.json; \
	jobs='$(word 2,$(MAKECMDGOALS))'; \
	jobs="$${jobs:-$(ACT_CONCURRENT_JOBS)}"; \
	case "$$jobs" in ''|*[!0-9]*|0*) echo "act-release: concurrent jobs must be a positive integer (got '$$jobs')"; exit 1;; esac; \
	act push $(ACT_PLATFORM) $(ACT_FLAGS) $$jobs -W .github/workflows/release.yml \
		-e .github/act/tag-push.json -s GITHUB_TOKEN=$$token

1 2 3 4 5 6 7 8 9 10 12 16 32:
	@:

tag-release:
	@chmod +x scripts/tag_release.sh scripts/extract-release-notes.sh scripts/resolve-release-tag.sh
	@scripts/tag_release.sh

# Usage: make version vX.Y.Z
ifneq (,$(filter version,$(MAKECMDGOALS)))
  VERSION_GOAL := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(VERSION_GOAL),)
    $(foreach v,$(VERSION_GOAL),$(eval $(v):;@:))
  endif
endif

version:
	@if [ -z "$(VERSION_GOAL)" ]; then \
		echo "Usage: make version vX.Y.Z"; \
		exit 1; \
	fi
	@chmod +x scripts/set_version.sh
	@scripts/set_version.sh $(VERSION_GOAL)

# Usage: make extract-notes  OR  make extract-notes v2.2.0
ifneq (,$(filter extract-notes,$(MAKECMDGOALS)))
  NOTES_GOAL := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(NOTES_GOAL),)
    $(foreach v,$(NOTES_GOAL),$(eval $(v):;@:))
  endif
endif

extract-notes:
	@chmod +x scripts/extract-release-notes.sh scripts/resolve-release-tag.sh
	@scripts/extract-release-notes.sh --stdout $(NOTES_GOAL)
