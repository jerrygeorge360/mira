.PHONY: help install run api slack worker provider-check test test-slack lint format type security check fix precommit clean ablation benchmark benchmark-cost benchmark-subset

PYTHON ?= python3
SOURCES := core ui slack evaluation scripts api
LONGMEMEVAL_DATASET ?= data/benchmarks/longmemeval.json

help:
	@printf '%s\n' \
		'Available targets:' \
		'  help       Show this help message' \
		'  install    Install development and production requirements' \
		'  run        Run the UI entry point' \
		'  api        Run the MIRA FastAPI server' \
		'  slack      Run the Slack bot entry point' \
		'  worker     Run the slow-path background memory worker' \
		'  provider-check  Smoke-check configured chat and embedding providers' \
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
		'  benchmark-cost     Estimate benchmark cost without paid calls' \
		'  benchmark          Run official-capable benchmark with budget cap' \
		'  benchmark-subset   Run budget-limited benchmark subset' \
		'  clean      Remove generated caches and reports'

install:
	$(PYTHON) -m pip install -r requirements-dev.txt
	$(PYTHON) -m pip install -r requirements.txt

run:
	$(PYTHON) -m ui.app

api:
	uvicorn api.main:app --reload --host 0.0.0.0 --port $${PORT:-8000}

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

worker:
	$(PYTHON) -m scripts.run_worker --batch-size $${BATCH_SIZE:-20} --poll-interval $${POLL_INTERVAL:-2}

provider-check:
	$(PYTHON) -m scripts.check_provider --require-live-embeddings

benchmark-cost:
	$(PYTHON) -m scripts.run_benchmark \
		--suite longmemeval \
		--dataset $(LONGMEMEVAL_DATASET) \
		--official \
		--dry-run-cost \
		--budget-usd $${BUDGET_USD:-15}

benchmark:
	$(PYTHON) -m scripts.run_benchmark \
		--suite longmemeval \
		--dataset $(LONGMEMEVAL_DATASET) \
		--official \
		--live \
		--judge hybrid \
		--budget-usd $${BUDGET_USD:-15} \
		--model $${MODEL:-qwen-plus} \
		--judge-model $${JUDGE_MODEL:-qwen-plus} \
		--out evaluation/results/benchmarks

benchmark-subset:
	$(PYTHON) -m scripts.run_benchmark \
		--suite longmemeval \
		--dataset $(LONGMEMEVAL_DATASET) \
		--official \
		--live \
		--judge hybrid \
		--limit $${LIMIT:-100} \
		--budget-usd $${BUDGET_USD:-15} \
		--model $${MODEL:-qwen-plus} \
		--judge-model $${JUDGE_MODEL:-qwen-plus} \
		--out evaluation/results/benchmarks

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
