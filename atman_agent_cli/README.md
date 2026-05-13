# Atman Agent CLI (`atman.agent_cli`)

Optional **local coding-agent TUI**: plan/review/repo automation sitting on top of Atman adapters when wired (see `memory.py`).

This subtree is **not** part of the default `atman` wheel — only [`src/atman`](../pyproject.toml) ships from Hatch. Consume sources from checkout:

```bash
pip install -e ".[agent-cli]"
export PYTHONPATH=atman_agent_cli/src:src
```

Core **`src/atman`** must **not** import `atman.agent_cli` ([import-linter](..%2f.importlinter) contract).

- **Operate:** [RUNBOOK.md](RUNBOOK.md)  
- **Preflight tooling:** [`scripts/agent_cli/`](../scripts/agent_cli/)  
- **Spec backlog:** [`AGENT_PLAN.md`](AGENT_PLAN.md), [`tasks/`](tasks/)

Launch (after deps + `PYTHONPATH`):

```bash
python -m atman.agent_cli.cli
```

For a disposable OpenAI-compatible endpoint while GGUF inference is unavailable, run [`scripts/agent_cli/mock_openai_llm.py`](../scripts/agent_cli/mock_openai_llm.py) and point `ATMAN_LLM_URL` at it.
