# ==============================================================================
# NightShift - AI On-Call Engineer Monorepo Makefile
# Required targets: up, test, demo, reset (plus lint, help)
# ==============================================================================

.PHONY: help up test demo reset lint check-owners traffic

SHELL := /bin/bash
PYTHON ?= python

help:
	@echo "NightShift - Autonomous AI On-Call Engineer"
	@echo ""
	@echo "Available commands:"
	@echo "  make up          - Start target app, telemetry, and platform API services"
	@echo "  make test        - Run linters, contract tests, and unit test suite"
	@echo "  make traffic     - Run steady traffic generator (10 rps)"
	@echo "  make demo FAULT=<id> - Run end-to-end autonomous incident resolution demo"
	@echo "  make reset       - Teardown all containers, wipe test state, clean caches"
	@echo "  make lint        - Run static analysis and linting checks"
	@echo "  make check-owners- Verify directory ownership against CODEOWNERS"
	@echo ""

traffic:
	@echo "==> Running Traffic Generator at 10 rps..."
	$(PYTHON) run.py traffic --rate 10

up:
	@echo "==> Starting NightShift Target App & Infrastructure..."
	@if [ ! -f .env ]; then \
		echo "Creating .env from .env.example..."; \
		cp .env.example .env; \
	fi
	@if [ -f infra/docker-compose.yml ]; then \
		docker compose -f infra/docker-compose.yml up -d; \
	else \
		echo "Infrastructure docker-compose.yml will be brought up in A2. Environment ready."; \
	fi
	@echo "==> NightShift services up."

test: lint
	@echo "==> Running test suite..."
	$(PYTHON) -m unittest discover -s tests -p "test_*.py" -v

demo:
	@echo "==> Triggering demo incident loop..."
	@if [ -z "$(FAULT)" ]; then \
		echo "ERROR: Please specify a fault ID: make demo FAULT=<id>"; \
		exit 1; \
	fi
	@echo "==> Injecting fault: $(FAULT)"
	$(PYTHON) run.py demo --fault $(FAULT)

reset:
	@echo "==> Resetting NightShift environment..."
	@if [ -f infra/docker-compose.yml ]; then \
		docker compose -f infra/docker-compose.yml down -v --remove-orphans; \
	fi
	@$(PYTHON) run.py reset
	@echo "==> Environment reset complete."

lint:
	@echo "==> Running linters & static checks..."
	$(PYTHON) run.py lint

check-owners:
	@echo "==> Validating CODEOWNERS rules against repository structure..."
	$(PYTHON) run.py check-owners
