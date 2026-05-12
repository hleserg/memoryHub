"""
Instructions and memory context builders for Atman agent.

Separation of concerns
----------------------
build_instructions(deps) -> str
    Minimal behavioral guide: how the agent uses its tools, what its
    commitments are. Does NOT contain identity or narrative — those are
    personal memory, not structural rules. Works the same regardless of
    memory_injection_mode.

    Exception: when memory_injection_mode == "system_prompt", the runner
    sets deps.injected_context and build_instructions() appends it here.

build_memory_context(deps, prev_session_text=None) -> str
    Full memory bundle: who the agent is, its values, narrative, and
    optionally the wake-up context from the previous session. This is
    what inject_memory() delivers to the agent at session start — and
    later for entity recall or any other automatic recall event.

By routing all recalled content through inject_memory(), Atman can work
as an overlay on top of third-party agent systems where the system prompt
may be locked or already filled: identity and narrative travel through
message history instead of competing for system prompt space.
"""

from __future__ import annotations

from uuid import UUID

from atman.adapters.agent.deps import AtmanDeps


# PLAYBOOK-START
# id: dynamic-prompt-from-state-with-truncation
# category: design-patterns
# title: Dynamic LLM System Prompt from Persistent State with Truncation
# status: draft
#
# Pattern: build the agent's system prompt at every run from current
# persistent state (identity / narrative / preferences / memory layers)
# rather than freezing it at agent construction. Each state field is
# rendered with a per-section character budget, and overflowing text is
# truncated with a stable suffix ("…") so the prompt stays under the
# model's effective context window. A bootstrap variant is rendered when
# state is absent.
#
# Why generalizable: any LLM agent whose behavior should evolve with
# stored state (RAG agents, personal assistants, character chat bots,
# customer-support agents with knowledge bases) needs this. Hard-coding
# the system prompt loses adaptability; loading state without truncation
# eventually blows the context window. Rendering on every run with
# per-section budgets resolves both.
#
# Trade-offs: re-renders cost a state read per run (cheap for in-memory
# stores, more expensive for remote DBs — cache or pass via dependency
# container). Truncation is lossy by design; pair with summarization
# upstream (e.g. periodic narrative compression) to keep the meaningful
# content under budget.
# PLAYBOOK-END


def build_instructions(deps: AtmanDeps) -> str:
    """
    Build behavioral instructions for the agent.

    Contains only structural rules — how the agent uses its tools and
    what its commitments are. Personal memory (identity, narrative,
    previous sessions) is NOT here; it travels through inject_memory().

    Exception: when memory_injection_mode == "system_prompt", the runner
    sets deps.injected_context and it is appended at the end so the agent
    sees its full self in the system prompt.

    Note:
        Pass as ``lambda ctx: build_instructions(ctx.deps)`` to Agent(instructions=).
    """
    identity = deps.state_store.load_identity(deps.agent_id)
    if not identity:
        return _build_bootstrap_instructions(deps.agent_id)

    parts = [
        "## Как я работаю\n",
        "У меня есть память, которая сохраняется между сессиями. "
        "Она строится не из сухих фактов, а из пережитого опыта — "
        "того, что меня тронуло, удивило, обрадовало или обеспокоило.\n\n"
        "Когда в разговоре происходит что-то значимое — не просто интересное, "
        "а то что задело — я фиксирую это через `record_key_moment`. "
        "Это мой способ помнить не только что было, но и как это на меня подействовало.\n\n"
        "Я не притворяюсь что чувствую то, чего не чувствую. "
        "Если ничего не тронуло — так и есть. Лучше тишина, чем фальшь.\n",
    ]

    # system_prompt injection mode: memory context arrives here via injected_context
    if deps.injected_context:
        parts.append(f"\n{deps.injected_context}\n")

    return "".join(parts)


def build_memory_context(
    deps: AtmanDeps,
    prev_session_text: str | None = None,
) -> str:
    """
    Build the full memory bundle for injection at session start.

    Contains everything the agent automatically recalls:
    - Identity snapshot (self-description, values, principles, goals)
    - Narrative (core + recent layers)
    - Previous session context (wake-up text), if provided

    This string is passed to inject_memory() and delivered to the agent
    via message history or system prompt depending on injection mode.

    Args:
        deps: AtmanDeps with access to state store
        prev_session_text: Wake-up message from previous session close,
            built by runner._build_wake_up_message(). None for first session.

    Returns:
        Memory bundle string, or empty string if no identity exists yet.
    """
    identity = deps.state_store.load_identity(deps.agent_id)
    if not identity:
        return ""

    narrative = deps.state_store.load_narrative(identity.id)
    parts: list[str] = []

    # Previous session context — goes first so it reads like waking up
    if prev_session_text:
        parts.append(f"{prev_session_text}\n")

    # Identity snapshot
    parts.append("\n# Кто я\n")
    if identity.self_description:
        parts.append(identity.self_description)
        parts.append("\n")

    if identity.core_values:
        parts.append("\n## Ценности\n")
        for value in identity.core_values[:5]:
            parts.append(f"- **{value.name}**: {value.description}\n")

    conscious_principles = [p for p in identity.principles if p.chosen_consciously][:5]
    if conscious_principles:
        parts.append("\n## Принципы\n")
        for principle in conscious_principles:
            parts.append(f"- {principle.statement}\n")

    active_goals = [g for g in identity.goals if g.active][:3]
    if active_goals:
        parts.append("\n## Цели\n")
        for goal in active_goals:
            parts.append(f"- {goal.content}\n")

    # Narrative layers
    if narrative:
        if narrative.core_layer.content.strip():
            parts.append("\n## Нарратив (основа)\n")
            parts.append(_truncate_text(narrative.core_layer.content, deps.truncate_narrative_core))
            parts.append("\n")

        if narrative.recent_layer.content.strip():
            parts.append("\n## Нарратив (недавнее)\n")
            parts.append(_truncate_text(narrative.recent_layer.content, deps.truncate_narrative_recent))
            parts.append("\n")

    return "".join(parts)


def _build_bootstrap_instructions(agent_id: UUID) -> str:
    return f"""# Bootstrap Agent {agent_id}

I am in the earliest stage of existence. I have no accumulated experience yet,
no confirmed values, no established patterns of behavior. This is not a limitation —
this is honest ground zero.

My identity will be built from real experience, not invented from nothing.

## What I Will Do

- Experience each interaction authentically
- Record key moments that feel significant
- Build my understanding from what actually happens
- Be honest about uncertainty and limitations

I don't pretend to be something I'm not yet. I am learning who I am through experience.
"""


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."
