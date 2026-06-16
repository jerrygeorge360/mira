# MIRA developer commands.
#
# Targets operate inside a local virtualenv (.venv) so the toolchain is isolated
# from system Python. CI calls `make install` then `make check`.

VENV := .venv
BIN := $(VENV)/bin
PYTHON := python3

# Source directories type-checked and security-scanned (everything but tests).
SRC := core ui slack evaluation scripts

.PHONY: help install run test lint format type security check fix precommit clean

help: ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Create the virtualenv and install the dev toolchain.
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt
	$(BIN)/pip install -r requirements.txt

run: ## Run the MIRA UI app (stub).
	$(BIN)/python -m ui.app

test: ## Run the test suite with coverage.
	$(BIN)/pytest

lint: ## Lint and verify formatting (no changes written).
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format: ## Auto-format the codebase.
	$(BIN)/ruff format .

type: ## Run static type checking.
	$(BIN)/mypy $(SRC)

security: ## Run the security scanner.
	$(BIN)/bandit -q -r $(SRC)

check: lint type security test ## Run all checks (CI entry point).

fix: ## Auto-fix lint findings and format.
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .

precommit: ## Run all pre-commit hooks against every file.
	$(BIN)/pre-commit run --all-files

clean: ## Remove the virtualenv, caches, and build artefacts.
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
