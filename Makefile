.PHONY: lint format typecheck security typecheck-agent-cli test test-fast test-all test-integration audit check all sync-site-content docs-preview demo-experience demo-factual demo-identity demo-reflection demo-session demo-full-corpus demo-webui demo-experience-fast demo-factual-fast demo-identity-fast demo-reflection-fast demo-session-fast demo-full-corpus-fast demo-webui-fast demo-experience-paced demo-factual-paced demo-identity-paced demo-reflection-paced demo-session-paced demo-full-corpus-paced demo-webui-paced demo-eval-runner demo-eval-runner-fast eval-list eval-run webui demo-e2e-scenario playbook-extract playbook-check playbook-audit agent-preflight agent-wait-llm agent-smoke agent-mock-llm agent-cli-lint agent-check-prep

lint:
	ruff check src/ tests/ e2e/

format:
	ruff format --check src/ tests/ e2e/

typecheck:
	pyright src/ tests/ e2e/

security:
	bandit -c pyproject.toml -r src/atman/ -q

test:
	pytest tests/ -v --cov=atman --cov-fail-under=90 --cov-report=term-missing

test-fast:
	pytest tests/ -m "not slow" -v

test-all:
	pytest tests/ -v

test-integration:
	pytest tests/ -m "integration" -v

audit:
	@python3 -c "\
	import importlib.metadata as md; f=open('/tmp/_atman_reqs.txt','w');\
	[f.write(n.split('[')[0].split('>=')[0].split('==')[0].split('<')[0].strip()+'=='+md.version(n.split('[')[0].split('>=')[0].split('==')[0].split('<')[0].strip())+'\n') for r in (md.distribution('atman').requires or []) if 'extra' not in r for n in [r.split(';')[0].strip()]];\
	f.close()"
	pip-audit -r /tmp/_atman_reqs.txt
	@rm -f /tmp/_atman_reqs.txt

check: lint format typecheck security lint-boundary test
	@echo ""
	@echo "All checks passed."

all: check audit

# Copies canonical EN + RU sources into docs/content/ for GitHub Pages (document.html).
# English: README.md, MANIFEST.md, docs/architecture/SYSTEM.md — Russian: *-ru.md counterparts.
sync-site-content:
	mkdir -p docs/content
	cp README.md README-ru.md MANIFEST.md MANIFEST-ru.md docs/content/
	cp docs/architecture/SYSTEM.md docs/content/SYSTEM.md
	cp docs/architecture/SYSTEM-ru.md docs/content/SYSTEM-ru.md
	cp docs/research/agent-thinking-comparison.md docs/content/COMPARISON.md
	cp docs/research/agent-thinking-comparison-ru.md docs/content/COMPARISON-ru.md

docs-preview: sync-site-content
	@echo "Serving from docs/ — open http://127.0.0.1:8765/"
	cd docs && python3 -m http.server 8765

# Reproducible demos: default = short pauses between beats (ATMAN_DEMO_PACE=1).
# For instant output (CI, scripting): make demo-experience-fast / demo-factual-fast.

# Experience Store walkthrough (temp JSONL; see docs/features/experience-store/README.md).
demo-experience demo-experience-paced:
	ATMAN_DEMO_PACE=1 python3 src/demo_experience_store.py

demo-experience-fast:
	ATMAN_DEMO_PACE=off python3 src/demo_experience_store.py

# Factual Memory walkthrough (in-memory + /tmp JSONL; see docs/features/factual-memory/README.md).
demo-factual demo-factual-paced:
	ATMAN_DEMO_PACE=1 python3 src/demo.py

demo-factual-fast:
	ATMAN_DEMO_PACE=off python3 src/demo.py

# Identity Store walkthrough (see docs/features/identity-store/README.md).
demo-identity demo-identity-paced:
	ATMAN_DEMO_PACE=1 python3 src/demo_identity.py

demo-identity-fast:
	ATMAN_DEMO_PACE=off python3 src/demo_identity.py

# Reflection Engine walkthrough (fixtures-based; see docs/features/reflection-engine/README.md).
demo-reflection demo-reflection-paced:
	ATMAN_DEMO_PACE=1 python3 src/demo_reflection.py

demo-reflection-fast:
	ATMAN_DEMO_PACE=off python3 src/demo_reflection.py

# Session Manager walkthrough (in-memory; see docs/features/session-manager/README.md).
demo-session demo-session-paced:
	ATMAN_DEMO_PACE=1 python3 src/demo_session_manager.py

demo-session-fast:
	ATMAN_DEMO_PACE=off python3 src/demo_session_manager.py

# Full E2E corpus: all session JSON fixtures → session + micro + daily + deep (see docs/features/full-corpus-demo/README.md).
demo-full-corpus demo-full-corpus-paced:
	ATMAN_DEMO_PACE=1 PYTHONPATH=. python3 src/demo_full_corpus.py

demo-full-corpus-fast:
	ATMAN_DEMO_PACE=off PYTHONPATH=. python3 src/demo_full_corpus.py

# Web Dashboard console hint (see docs/features/web-dashboard/README.md).
demo-webui demo-webui-paced:
	ATMAN_DEMO_PACE=1 python3 src/demo_web_dashboard.py

demo-webui-fast:
	ATMAN_DEMO_PACE=off python3 src/demo_web_dashboard.py

# Eval Runner walkthrough (see docs/features/eval-runner/README.md).
demo-eval-runner:
	ATMAN_DEMO_PACE=1 python3 src/demo_eval_runner.py

demo-eval-runner-fast:
	ATMAN_DEMO_PACE=off python3 src/demo_eval_runner.py

# Eval Runner CLI (module-only, isolated from production entry points).
eval-list:
	python3 -m atman.eval.benchmark_runner list

eval-run:
	python3 -m atman.eval.benchmark_runner run noop

# Web dashboard — runs Streamlit web UI (see docs/features/web-dashboard/).
webui:
	python3 -m streamlit run src/atman/web_dashboard/app.py

# E2E demo scenario: generates docs/demo-data/*.json for atmanai.dev/demo.html.
# See e2e/scenarios/value_drift_under_pressure.py and docs/demo.html.
demo-e2e-scenario:
	PYTHONPATH=. python3 e2e/scenarios/value_drift_under_pressure.py

# PLAYBOOK marker extraction and validation.
# See docs/development/PLAYBOOK_MARKERS.md for syntax and setup.
playbook-extract:
	python3 scripts/extract_playbook.py --target ../agent-playbook/raw/extracted-from-atman.md

playbook-check:
	python3 scripts/extract_playbook.py --check

playbook-audit:
	python3 scripts/suggest_playbook.py

# ===== Eval / Production isolation =====
# (added by setup_prod_eval_boundary.sh — see docs/architecture/PROD_EVAL_BOUNDARY.md)

.PHONY: lint-boundary verify-prod-isolation eval-db-init eval-db-migrate eval-db-downgrade eval-db-test eval-up eval-down

lint-boundary:
	python3 -c "from importlinter.cli import lint_imports_command; lint_imports_command()"

verify-prod-isolation:
	bash scripts/infra/verify_prod_isolation.sh

eval-db-init:
	alembic -c eval/migrations/alembic.ini upgrade head

eval-db-migrate:
	alembic -c eval/migrations/alembic.ini revision -m "$(MSG)"

eval-db-downgrade:
	alembic -c eval/migrations/alembic.ini downgrade -1

eval-db-test:
	pytest tests/test_eval_storage_integration.py -v

COMPOSE_EVAL = docker compose -f docker-compose.yml -f docker-compose.eval.yml

eval-up:
	$(COMPOSE_EVAL) up -d

eval-down:
	$(COMPOSE_EVAL) down

# --- Agent CLI split-tree helpers (preflight / LLM readiness; scripts/agent_cli/README.md).
MOCK_LLM_PORT ?= 18080

agent-preflight:
	PYTHONPATH=atman_agent_cli/src:src python3 scripts/agent_cli/preflight.py

agent-wait-llm:
	PYTHONPATH=atman_agent_cli/src:src python3 scripts/agent_cli/wait_for_llm.py

agent-smoke:
	PYTHONPATH=atman_agent_cli/src:src python3 scripts/agent_cli/smoke_imports.py

agent-mock-llm:
	PYTHONPATH=atman_agent_cli/src:src python3 scripts/agent_cli/mock_openai_llm.py --bind 127.0.0.1 --port $(MOCK_LLM_PORT)

agent-cli-lint:
	ruff check scripts/agent_cli/

typecheck-agent-cli:
	pyright --project atman_agent_cli/pyrightconfig.json

agent-check-prep: agent-cli-lint typecheck-agent-cli agent-smoke agent-preflight
	@echo "Agent prep gates done (scripts + permissive pyright + smoke + preflight)."