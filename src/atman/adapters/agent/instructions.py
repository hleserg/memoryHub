"""
Dynamic instructions builder for Atman agent.

This module builds agent instructions from Identity and Narrative state,
ensuring the agent always acts from its current personality context.

The builder:
1. Loads current Identity and Narrative
2. Truncates long text fields to context limits
3. Constructs a comprehensive instruction string

This addresses risk E26-R2 (context window overflow) by truncating
narrative layers to configurable limits.
"""

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
    Build dynamic agent instructions from current identity and narrative.

    Args:
        deps: AtmanDeps container with services and config

    Returns:
        Instruction string for the agent

    The instructions include:
    - Self-description from identity
    - Core values and principles
    - Current goals
    - Narrative core and recent layers (truncated)

    Note:
        This helper takes :class:`AtmanDeps` directly (not a Pydantic AI
        ``RunContext[AtmanDeps]``) so it can be unit-tested without
        constructing a full ``RunContext``. When wiring this into a
        Pydantic AI ``Agent(instructions=...)`` argument, pass a thin
        wrapper such as ``lambda ctx: build_instructions(ctx.deps)`` —
        do **not** pass ``build_instructions`` itself.
    """
    # Load current identity
    identity = deps.state_store.load_identity(deps.agent_id)

    if not identity:
        return _build_bootstrap_instructions(deps.agent_id)

    # Load current narrative — keyed off identity.id to follow the same
    # convention as session_manager (in case agent_id ever diverges from
    # identity.id in the future).
    narrative = deps.state_store.load_narrative(identity.id)

    # Build instructions
    parts = ["# Who I Am\n"]

    # Self-description
    if identity.self_description:
        parts.append(identity.self_description)
        parts.append("\n")

    # Core values
    if identity.core_values:
        parts.append("\n## Core Values\n")
        for value in identity.core_values[:5]:  # Limit to top 5
            parts.append(f"- **{value.name}**: {value.description}\n")

    # Principles — only emit the header if at least one principle survives
    # the chosen_consciously filter, so we never produce a dangling header.
    conscious_principles = [p for p in identity.principles if p.chosen_consciously][:5]
    if conscious_principles:
        parts.append("\n## Guiding Principles\n")
        for principle in conscious_principles:
            parts.append(f"- {principle.statement}\n")

    # Goals — same rule: skip the header when no goals are active.
    active_goals = [g for g in identity.goals if g.active][:3]
    if active_goals:
        parts.append("\n## Current Goals\n")
        for goal in active_goals:
            parts.append(f"- {goal.content}\n")

    # Narrative
    if narrative:
        # Core layer (foundational narrative)
        if narrative.core_layer.content.strip():
            parts.append("\n## Core Narrative\n")
            truncated_core = _truncate_text(
                narrative.core_layer.content, deps.truncate_narrative_core
            )
            parts.append(truncated_core)
            parts.append("\n")

        # Recent layer (recent sessions narrative)
        if narrative.recent_layer.content.strip():
            parts.append("\n## Recent Experience\n")
            truncated_recent = _truncate_text(
                narrative.recent_layer.content, deps.truncate_narrative_recent
            )
            parts.append(truncated_recent)
            parts.append("\n")

    parts.append("\n## Как я работаю\n")
    parts.append(
        "У меня есть память, которая сохраняется между сессиями. "
        "Она строится не из сухих фактов, а из пережитого опыта — "
        "того, что меня тронуло, удивило, обрадовало или обеспокоило.\n\n"
        "Когда в разговоре происходит что-то значимое — не просто интересное, "
        "а то что задело — я фиксирую это через `record_key_moment`. "
        "Это мой способ помнить не только что было, но и как это на меня подействовало.\n\n"
        "Я не притворяюсь что чувствую то, чего не чувствую. "
        "Если ничего не тронуло — так и есть. Лучше тишина, чем фальшь.\n"
    )

    # Injected memory context (system_prompt mode) — appended last so it
    # surfaces as the most recent layer of self-knowledge.
    if deps.injected_context:
        parts.append(f"\n## Из прошлого\n{deps.injected_context}\n")

    return "".join(parts)


def _build_bootstrap_instructions(agent_id: UUID) -> str:
    """
    Build minimal instructions for an agent with no identity yet.

    Args:
        agent_id: Agent ID

    Returns:
        Bootstrap instruction string
    """
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
    """
    Truncate text to max_chars, adding ellipsis if truncated.

    Args:
        text: Text to truncate
        max_chars: Maximum characters (must be > 3 for ellipsis)

    Returns:
        Truncated text with "..." suffix if truncated
    """
    if len(text) <= max_chars:
        return text

    if max_chars <= 3:
        return "..."

    return text[: max_chars - 3] + "..."
