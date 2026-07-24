.PHONY: setup build up down logs chat help evidence test test-acceptance \
	accept-notification-services accept-notification-stack \
	accept-developer-workspace accept-patch-approval accept-developer-contract \
	accept-repository-workspaces accept-developer-tools accept-external-documentation \
	accept-developer-workflow accept-draft-pr-workflow accept-publication-path \
	accept-telegram-workflows accept-repository-cleanup accept-runtime-hardening accept-documentation check-repository-hygiene normalize-repository-hygiene prepare-runtime-layout wait smoke-real clean-data \
	secret-set secret-set-openrouter secret-set-github secrets-list storage \
	clean-artifacts-dry-run clean-artifacts clean-all

setup:
	./scripts/prepare-runtime-layout

prepare-runtime-layout:
	./scripts/prepare-runtime-layout

build:
	docker compose -f docker-compose.yml -f docker-compose.local.yml build

up:
	./scripts/prepare-runtime-layout
	docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build model-gateway calendar-task-mcp harness
	@echo "Waiting for harness..."
	@for i in $$(seq 1 30); do \
		if curl -fsS http://127.0.0.1:8787/health >/dev/null 2>&1; then \
			echo "Harness is ready."; \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "Harness did not become ready in time."; \
	docker compose -f docker-compose.yml -f docker-compose.local.yml logs harness; \
	exit 1

down:
	docker compose -f docker-compose.yml -f docker-compose.local.yml down

logs:
	docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f

chat:
	./scripts/safeplane chat "$(MESSAGE)"


help:
	./scripts/safeplane help

evidence:
	./scripts/safeplane evidence $${RUN_ID:-latest}

test:
	pytest

test-acceptance:
	pytest tests/acceptance

check-repository-hygiene:
	tests/scripts/check-repository-hygiene

normalize-repository-hygiene:
	./scripts/normalize-repository-hygiene

accept-notification-services:
	tests/scripts/accept-notification-services

accept-notification-stack:
	tests/scripts/accept-notification-stack

accept-developer-workspace:
	tests/scripts/accept-developer-workspace

accept-patch-approval:
	tests/scripts/accept-patch-approval

accept-developer-contract:
	tests/scripts/accept-developer-contract

accept-repository-workspaces:
	tests/scripts/accept-repository-workspaces

accept-developer-tools:
	tests/scripts/accept-developer-tools

accept-external-documentation:
	tests/scripts/accept-external-documentation

accept-developer-workflow:
	tests/scripts/accept-developer-workflow

accept-draft-pr-workflow:
	tests/scripts/accept-draft-pr-workflow

accept-publication-path:
	tests/scripts/accept-publication-path

accept-telegram-workflows:
	tests/scripts/accept-telegram-workflows

accept-repository-cleanup:
	tests/scripts/accept-repository-cleanup

accept-runtime-hardening:
	tests/scripts/accept-runtime-hardening

accept-documentation:
	tests/scripts/accept-documentation

wait:
	@echo "Waiting for harness..."
	@for i in $$(seq 1 30); do \
		if curl -fsS http://127.0.0.1:8787/health >/dev/null 2>&1; then \
			echo "Harness is ready."; \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "Harness did not become ready in time."; \
	docker compose -f docker-compose.yml -f docker-compose.local.yml logs harness; \
	exit 1

secret-set:
	@if [ -z "$(NAME)" ]; then \
		echo "Usage: make secret-set NAME=<secret_name>"; \
		exit 1; \
	fi
	./scripts/safeplane-secret set "$(NAME)"

secret-set-openrouter:
	$(MAKE) secret-set NAME=openrouter_api_key

secret-set-github:
	$(MAKE) secret-set NAME=github_token

secrets-list:
	./scripts/safeplane-secret list

smoke-real:
	./scripts/prepare-runtime-layout
	@OPENROUTER_FILE="$${SAFEPLANE_OPENROUTER_API_KEY_FILE:-$${SAFEPLANE_SECRET_ROOT:-$$HOME/.config/safeplane/secrets}/openrouter_api_key}"; \
	if [ ! -s "$$OPENROUTER_FILE" ]; then \
		echo "Missing OpenRouter secret file."; \
		echo "Run: make secret-set-openrouter"; \
		exit 1; \
	fi
	docker compose -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.real.yml up -d --build --force-recreate model-gateway calendar-task-mcp harness
	$(MAKE) wait
	SAFEPLANE_HARNESS_URL=http://127.0.0.1:8787 ./scripts/safeplane chat "$(MESSAGE)"

storage:
	./scripts/safeplane maintenance storage

clean-artifacts-dry-run:
	./scripts/safeplane maintenance clean --dry-run --older-than 30d

clean-artifacts:
	./scripts/safeplane maintenance clean --older-than 30d

clean-all:
	./scripts/safeplane maintenance clean-all

clean-data:
	rm -rf $${SAFEPLANE_HOME:-$$HOME/.safeplane}/sessions
	rm -rf $${SAFEPLANE_HOME:-$$HOME/.safeplane}/traces


secret-set-telegram:
	./scripts/safeplane-secret set telegram_bot_token

telegram-up:
	./scripts/prepare-runtime-layout
	docker compose -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.telegram.yml up -d --build telegram-connector

telegram-down:
	docker compose -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.telegram.yml stop telegram-connector

telegram-logs:
	docker compose -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.telegram.yml logs -f telegram-connector


secret-set-telegram-users:
	./scripts/safeplane-secret set telegram_allowed_user_ids


telegram-real-up:
	./scripts/prepare-runtime-layout
	docker compose -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.real.yml -f docker-compose.telegram.yml up -d --build model-gateway calendar-task-mcp harness telegram-connector

telegram-real-logs:
	docker compose -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.real.yml -f docker-compose.telegram.yml logs -f telegram-connector model-gateway harness

telegram-real-down:
	docker compose -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.real.yml -f docker-compose.telegram.yml stop telegram-connector


mcp-up:
	./scripts/prepare-runtime-layout
	docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build calendar-task-mcp harness

mcp-logs:
	docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f calendar-task-mcp harness

.PHONY: vps-preflight vps-config vps-start vps-stop vps-restart vps-status vps-logs vps-backup

vps-preflight:
	./scripts/safeplane-vps preflight

vps-config:
	./scripts/safeplane-vps config

vps-start:
	./scripts/safeplane-vps start

vps-stop:
	./scripts/safeplane-vps stop

vps-restart:
	./scripts/safeplane-vps restart

vps-status:
	./scripts/safeplane-vps status

vps-logs:
	./scripts/safeplane-vps logs --tail 200

vps-backup:
	./scripts/safeplane-vps backup
