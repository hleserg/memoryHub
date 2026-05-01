.PHONY: lint format typecheck security test test-fast audit check all sync-site-content docs-preview demo-experience demo-factual demo-experience-fast demo-factual-fast demo-experience-paced demo-factual-paced webui

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

# Copies canonical EN + RU sources into docs/content/ for GitHub Pages (document.html).
# English: README.md, MANIFEST.md, docs/architecture/SYSTEM.md — Russian: *-ru.md counterparts.
sync-site-content:
	mkdir -p docs/content
	cp README.md README-ru.md MANIFEST.md MANIFEST-ru.md docs/content/
	cp docs/architecture/SYSTEM.md docs/content/SYSTEM.md
	cp docs/architecture/SYSTEM-ru.md docs/content/SYSTEM-ru.md

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

# Web dashboard — runs Streamlit web UI (see docs/features/web-dashboard/).
webui:
	python3 -m streamlit run src/atman/web_dashboard/app.py
