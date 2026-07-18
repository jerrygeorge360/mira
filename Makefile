.PHONY: help install run api slack mcp worker provider-check graph-inspect slow-path-status memory-search demo-cleanup local-eval test test-slack lint format type security check fix precommit clean ablation ablation-live benchmark benchmark-cost benchmark-subset frontend-install frontend-dev frontend-build

PYTHON ?= python3
SOURCES := core ui slack evaluation scripts api integrations
LONGMEMEVAL_DATASET ?= data/benchmarks/longmemeval.json

help:
	@printf '%s\n' \
		'Available targets:' \
		'  help       Show this help message' \
		'  install    Install development and production requirements' \
		'  run        Run the UI entry point' \
		'  api        Run the MIRA FastAPI server' \
		'  slack      Run the Slack bot entry point' \
		'  mcp        Run the standalone MCP memory service' \
		'  worker     Run the slow-path background memory worker' \
		'  provider-check  Smoke-check configured chat and embedding providers' \
		'  graph-inspect   Print a JSON snapshot of the memory graph' \
		'  slow-path-status Print slow-path queue and artifact health' \
		'  memory-search   Embed a query and search vector memory' \
		'  demo-cleanup    Delete expired disposable demo workspaces' \
		'  local-eval      Run the small local memory regression suite' \
		'  test       Run the test suite' \
		'  test-slack Run only the Slack bot tests' \
		'  lint       Run Ruff checks and formatting check' \
		'  format     Format the codebase with Ruff' \
		'  type       Run mypy over application sources' \
		'  security   Run Bandit over application sources' \
		'  check      Run lint, type, security, and tests' \
		'  fix        Apply Ruff fixes and formatting' \
		'  precommit  Run all pre-commit hooks' \
		'  ablation   Run the ablation study offline (stub) and write results' \
		'  ablation-live   Run the ablation study against the live provider (LLM_PROFILE)' \
		'  benchmark-cost     Estimate benchmark cost without paid calls' \
		'  benchmark          Run official-capable benchmark with budget cap' \
		'  benchmark-subset   Run budget-limited benchmark subset' \
		'  clean      Remove generated caches and reports'

install:
	$(PYTHON) -m pip install -r requirements-dev.txt
	$(PYTHON) -m pip install -r requirements.txt

run:
	PYTHONPATH=. $(PYTHON) -m streamlit run ui/app.py

api:
	uvicorn api.main:app --reload --host 0.0.0.0 --port $${PORT:-8000}

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

slack:
	$(PYTHON) -m slack.bot

mcp:
	uvicorn integrations.mcp.service:app --reload --host 0.0.0.0 --port $${MCP_PORT:-8090}

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

ablation-live:
	$(PYTHON) -m scripts.run_ablation --live --out $${OUT:-evaluation/results} $${CASES:+--cases $$CASES} $${COMPONENTS:+--components $$COMPONENTS} $${LIMIT:+--limit $$LIMIT} $${RUN_SLOW_PATH:+--run-slow-path} $${SLOW_PATH_BATCH_SIZE:+--slow-path-batch-size $$SLOW_PATH_BATCH_SIZE} $${DELAY_S:+--delay-s $$DELAY_S} $${SHARED_DB:+--shared-db} $${RESUME:+--resume} $${PARALLEL:+--parallel $$PARALLEL} $${NO_CACHE:+--no-cache}

worker:
	$(PYTHON) -m scripts.run_worker --batch-size $${BATCH_SIZE:-20} --poll-interval $${POLL_INTERVAL:-2}

provider-check:
	$(PYTHON) -m scripts.check_provider --require-live-embeddings

graph-inspect:
	$(PYTHON) -m scripts.inspect_graph --workspace-id "$${WORKSPACE_ID:?set WORKSPACE_ID}" --limit $${LIMIT:-50} $${ENTITY:+--entity "$$ENTITY"}

slow-path-status:
	$(PYTHON) -m scripts.slow_path_status --workspace-id "$${WORKSPACE_ID:?set WORKSPACE_ID}" --limit $${LIMIT:-10}

memory-search:
	$(PYTHON) -m scripts.search_memory "$${QUERY:?set QUERY='your search text'}" --workspace-id "$${WORKSPACE_ID:?set WORKSPACE_ID}" --limit $${LIMIT:-5} $${REBUILD:+--rebuild}

demo-cleanup:
	$(PYTHON) -m scripts.cleanup_demos

local-eval:
	$(PYTHON) -m scripts.run_local_eval --cases $${CASES:-evaluation/local/memory_cases.json}

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
		$${PARALLEL:+--parallel $$PARALLEL} $${RESUME:+--resume} $${CACHE:+--cache} \
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
		$${PARALLEL:+--parallel $$PARALLEL} $${RESUME:+--resume} $${CACHE:+--cache} \
		--out evaluation/results/benchmarks

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
