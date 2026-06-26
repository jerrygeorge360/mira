.PHONY: help install run slack test test-slack lint format type security check fix precommit clean ablation

PYTHON ?= python3
SOURCES := core ui slack evaluation scripts

help:
	@printf '%s\n' \
		'Available targets:' \
		'  help       Show this help message' \
		'  install    Install development and production requirements' \
		'  run        Run the UI entry point' \
		'  slack      Run the Slack bot entry point' \
		'  test       Run the test suite' \
		'  test-slack Run only the Slack bot tests' \
		'  lint       Run Ruff checks and formatting check' \
		'  format     Format the codebase with Ruff' \
		'  type       Run mypy over application sources' \
		'  security   Run Bandit over application sources' \
		'  check      Run lint, type, security, and tests' \
		'  fix        Apply Ruff fixes and formatting' \
		'  precommit  Run all pre-commit hooks' \
		'  ablation   Run the ablation study and write results' \
		'  clean      Remove generated caches and reports'

install:
	$(PYTHON) -m pip install -r requirements-dev.txt
	$(PYTHON) -m pip install -r requirements.txt

run:
	$(PYTHON) -m ui.app

slack:
	$(PYTHON) -m slack.bot

test:
	$(PYTHON) -m pytest --no-cov || [ $$? -eq 5 ]

test-slack:
	$(PYTHON) -m pytest tests/test_slack_bot.py --no-cov -v

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

ablation:
	$(PYTHON) -m scripts.run_ablation --stub --out evaluation/results

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
