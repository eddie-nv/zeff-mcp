.PHONY: help install test lint format typecheck migrate downgrade revision seed eval db-up db-down db-logs clean

PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
PYTEST ?= .venv/bin/pytest
RUFF ?= .venv/bin/ruff
MYPY ?= .venv/bin/mypy
ALEMBIC ?= .venv/bin/alembic

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

install: ## Create venv and install package + dev deps
	python3 -m venv .venv
	$(PIP) install -U pip
	$(PIP) install -e ".[dev]"

test: ## Run pytest (requires `make db-up`)
	$(PYTEST)

lint: ## Ruff lint check
	$(RUFF) check src tests

format: ## Ruff format
	$(RUFF) format src tests

typecheck: ## mypy strict
	$(MYPY) src

migrate: ## Apply alembic migrations to DATABASE_URL
	$(ALEMBIC) upgrade head

downgrade: ## Roll back one migration
	$(ALEMBIC) downgrade -1

revision: ## Create a new alembic revision: `make revision m="add x table"`
	$(ALEMBIC) revision -m "$(m)"

seed: ## Run all seeds in order (canonical, USDA, composites, facets)
	$(PY) -m zeff.seeds.canonical
	$(PY) -m zeff.seeds.usda_sr
	$(PY) -m zeff.seeds.composites
	$(PY) -m zeff.seeds.facets

seed-canonical: ## Seed only the canonical category tree
	$(PY) -m zeff.seeds.canonical

seed-usda: ## Seed only the USDA SR Legacy primitives
	$(PY) -m zeff.seeds.usda_sr

seed-composites: ## Seed the hand-curated composites
	$(PY) -m zeff.seeds.composites

seed-facets: ## Compute and upsert facets for every primitive
	$(PY) -m zeff.seeds.facets

eval: ## Run all eval runners (M2+)
	$(PY) -m evals.runners.run_search_eval --no-seed
	$(PY) -m evals.runners.run_taxonomy_eval

db-up: ## Start local Postgres
	docker compose up -d

db-down: ## Stop local Postgres (keeps data)
	docker compose down

db-logs: ## Tail local Postgres logs
	docker compose logs -f db

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
