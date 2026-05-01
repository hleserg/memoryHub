.PHONY: lint format typecheck security test test-fast audit check all

lint:
	ruff check src/ tests/

format:
	ruff format --check src/ tests/

typecheck:
	pyright src/ tests/

security:
	bandit -c pyproject.toml -r src/atman/ -q

test:
	pytest tests/ -v --cov=atman --cov-fail-under=90 --cov-report=term-missing

test-fast:
	pytest tests/ -n auto -q

audit:
	pip-audit

check: lint format typecheck security test
	@echo ""
	@echo "All checks passed."

all: check audit
