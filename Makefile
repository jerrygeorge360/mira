.PHONY: install run test lint format type security check fix precommit clean

PYTHON ?= python3
SOURCES := core ui slack evaluation scripts

install:
	$(PYTHON) -m pip install -r requirements-dev.txt
	$(PYTHON) -m pip install -r requirements.txt

run:
	$(PYTHON) -m ui.app

test:
	$(PYTHON) -m pytest --no-cov || [ $$? -eq 5 ]

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff format .

type:
	$(PYTHON) -m mypy $(SOURCES)

security:
	$(PYTHON) -m bandit -q -r $(SOURCES)

check: lint type security test

fix:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

precommit:
	$(PYTHON) -m pre_commit run --all-files

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
