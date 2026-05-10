# Agent Adapter

**Status:** WIP — Foundation only (E26, sub-issues #398–#400)
**Purpose:** Pydantic AI–based wrapper that turns Atman's services into a runnable LLM agent.

[[ru](README-ru.md)] — *Russian version*

---

## Overview

The agent adapter (`src/atman/adapters/agent/`) is the planned LLM-facing
surface of Atman. When complete it will let an LLM run sessions through
`SessionManager`, build its system prompt from current `Identity` /
`NarrativeDocument` state, and call typed tools (record key moments, log
experiences, query memory, etc.) — with all execution mediated by the
existing core services and ports.

This work-package is delivered in stages. **This PR (#413) lands only the
foundation** — there is intentionally no end-to-end demo yet, because the
agent runner that wires `Agent(deps=AtmanDeps, instructions=…)` and
actually drives a session over an LLM provider is the subject of a
follow-up sub-issue. The pieces shipped here are unit-testable in
isolation and are exercised through `tests/test_agent_config.py`,
`tests/test_instructions.py`, and `tests/test_tools.py`.

The underlying services this adapter wraps are already covered by their
own runnable demos — see `make demo-session`, `make demo-identity`,
`make demo-reflection`, and `make demo-full-corpus`.

---

## What Lands in This PR

| Module | Public surface | Role |
|--------|----------------|------|
| `adapters/agent/config.py` | `ModelConfig`, `AgentConfig` | Pydantic-validated runtime config: model + provider, tool budget, narrative truncation budgets (E26-R1, E26-R2, E26-R4) |
| `adapters/agent/deps.py` | `AtmanDeps`, `AtmanDeps.from_config(...)` | Frozen-dataclass DI container holding `SessionManager` / `IdentityService` / `ExperienceService` / `MicroReflectionService` / `StateStore` plus the runtime `agent_id` and (optional) `session_id`. `from_config(...)` builds it from a validated `AgentConfig`. |
| `adapters/agent/instructions.py` | `build_instructions(deps)` | Loads current `Identity` + `NarrativeDocument` and renders the dynamic system prompt with per-section character budgets to stay under the model's context window. Falls back to a "bootstrap" prompt when no identity is stored yet. |
| `adapters/agent/tools.py` | `record_key_moment`, `log_experience` | Pydantic AI tool callbacks. `record_key_moment` is fully wired into `SessionManager.record_key_moment`; `log_experience` is a redirect stub pointing the LLM at the session-end flow until the direct-log path lands. |

Two generalizable patterns are documented inline as `PLAYBOOK` markers:

- `error-returning-tool-callbacks` (in `tools.py`) — tool callbacks return error strings instead of raising, so the LLM can self-correct.
- `dynamic-prompt-from-state-with-truncation` (in `instructions.py`) — render the system prompt from persistent state on every run, with per-section truncation budgets.

---

## Pending Work (Future Sub-Issues)

- **Agent runner.** Wire `pydantic_ai.Agent(model=…, deps_type=AtmanDeps, instructions=lambda ctx: build_instructions(ctx.deps), tools=[record_key_moment, log_experience, …])` into a CLI entry-point and `make demo-agent` target. The runner will start a session via `SessionManager`, attach `session_id` to a fresh `AtmanDeps`, run the agent, and finish the session.
- **Direct-log path for `log_experience`.** Today the tool returns a redirect message; once the runner is in place, it should call into `ExperienceService` directly for out-of-band experiences.
- **Tool-budget enforcement.** `AgentConfig.max_tool_calls` is validated and carried in `AtmanDeps` but not yet enforced — the runner sub-issue will gate tool dispatch on it (E26-R4 mitigation).
- **Identity / experience query tools.** `enable_experience_search` and `get_identity_snapshot`-style tools are planned but not part of this PR.
- **Live demo.** A `docs/features/agent-adapter/` walkthrough and `make demo-agent` target will be added together with the runner.

---

## Testing

```bash
# Unit tests for the foundation pieces:
pytest tests/test_agent_config.py tests/test_instructions.py tests/test_tools.py -v

# Full project quality gate:
make check
```

Coverage for the new modules: `adapters/agent/config.py` 100%, `adapters/agent/tools.py` 100%, `adapters/agent/instructions.py` ~96%, `adapters/agent/deps.py` ~77% (uncovered lines are the `TYPE_CHECKING` import block).
