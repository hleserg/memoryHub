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
	@python3 -c "\
	import importlib.metadata as md; f=open('/tmp/_atman_reqs.txt','w');\
	[f.write(n.split('>=')[0].split('==')[0].split('<')[0].strip()+'=='+md.version(n.split('>=')[0].split('==')[0].split('<')[0].strip())+'\n') for r in (md.distribution('atman').requires or []) if 'extra' not in r for n in [r.split(';')[0].strip()]];\
	f.close()"
	pip-audit -r /tmp/_atman_reqs.txt
	@rm -f /tmp/_atman_reqs.txt

check: lint format typecheck security test
	@echo ""
	@echo "All checks passed."

all: check audit
