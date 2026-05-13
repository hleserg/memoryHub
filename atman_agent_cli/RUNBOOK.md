# Atman Agent CLI — Operator runbook

Agent CLI (“babysitting” coding agent UI) rides on the **canonical Atman repo** (`src/atman`) while living in the split subtree `atman_agent_cli/src/atman/agent_cli/`. Operational checks live under `scripts/agent_cli/` (bootstrap + preflight helpers).

---

## Environment variables

| Variable | Role |
|----------|------|
| `ATMAN_LLM_URL` | Base HTTP URL for an OpenAI-compatible server (many **llama.cpp** builds expose REST). Default `http://localhost:8080`. |
| `ATMAN_LLM_MODEL` | Model id sent with requests (CLI default `gemma4` if unset — align with whatever your server publishes). |
| `ATMAN_CONTEXT_LIMIT` | Tokens / context sizing guardrails (defaults in `AgentConfig`). |
| `COHERE_API_KEY` | Planner / rerank backends when wired to Cohere. |
| `GITHUB_TOKEN`, `ATMAN_GITHUB_REPO` | PR/babysit flows against GitHub. |
| Typical vendor keys (`ANTHROPIC_API_KEY`, etc.) follow normal SDK conventions wherever those code paths execute. |

Use `preflight.py` `--json` to snapshot optional Python modules that back search, scraping, embeddings, or messaging.

---

## Preparing a local llama.cpp–style server

Rough outline (adapt to how you invoke **llama.cpp** / forks):

1. Serve a quantized model with `--host`/`--port` reachable from dev machine.
2. Enable **OpenAI-compatible** HTTP if optional (often `/v1/models`, `/v1/chat/completions`).
3. Smoke from host:

   ```bash
   PYTHONPATH=atman_agent_cli/src:src python3 scripts/agent_cli/wait_for_llm.py --llm-url http://127.0.0.1:<port>
   ```

Tune `--timeout-sec` for cold model loads.

---

## Day‑0 checklist

1. **`PYTHONPATH`** (from repo root / CI):

   ```bash
   export PYTHONPATH=atman_agent_cli/src:src
   ```

2. **`pip install -e ".[agent-cli]"`** once `[agent-cli]` exists in root extras; interim `pip install -e ".[dev]"` plus per-feature libs.

3. **Preflight** (Python 3.12+, layout + imports):

   ```bash
   python3 scripts/agent_cli/preflight.py --repo .
   ```

   LLM reachability warns only — training/offline GPUs should not gate exit codes.

4. **Wait loop** once the inference process is spinning up:

   ```bash
   python3 scripts/agent_cli/wait_for_llm.py --llm-url "${ATMAN_LLM_URL}"
   ```

5. **Launch Textual UI** (`python -m …` documented when console script merges; meanwhile run module after bootstrap — see scripts README):

   Prefer the Makefile targets `agent-preflight`, `agent-wait-llm`, `agent-smoke` during bring-up where available.

---

## When a custom model arrives

| Knob | What to change |
|------|----------------|
| **`ATMAN_LLM_MODEL`** | Must match advertised id (`/v1/models` payloads). |
| **Context sizing** (`ATMAN_CONTEXT_LIMIT`, planner token caps) | Shrink aggressively for small GPUs; widen only when logs show healthy headroom. |
| **`llm_temperature` / max tokens (`AgentConfig`)** | Low temperature for refactor-heavy tasks; raise cautiously when exploration helps. |

Re-run **`wait_for_llm.py`** after server restarts — models may load asynchronously.

---

## Mock LLM stub (`mock_openai_llm.py`)

For UI / plumbing checks without GGUF inference:

```bash
python3 scripts/agent_cli/mock_openai_llm.py --bind 127.0.0.1 --port 18080
export ATMAN_LLM_URL=http://127.0.0.1:18080
```

The stub answers `/v1/models` and streams `/v1/chat/completions` SSE compatible with `_llamacpp_stream`. Optionally `--stub-file replies.txt`.

---

## Separation from core `atman`

- **Psychology layer** APIs, ports, adapters, and evaluation harnesses stay under **`src/atman`**.
- **Agent CLI UX** (`atman/agent_cli/*`) orchestrates repos, watchers, babysit workflows, embeddings, Telegram hooks, etc. — optional, higher-layer surface.
- **Import guardrails**: `.importlinter` contract `no-core-to-optional-agent-cli` forbids enumerated `src/atman/*` namespaces from importing **`atman.agent_cli`**.
- Scripts under `scripts/agent_cli/` purposely **avoid pytest** — they bootstrap split trees for humans and notebooks.
