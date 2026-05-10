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
    """
    # Load current identity
    identity = deps.state_store.load_identity(deps.agent_id)

    if not identity:
        return _build_bootstrap_instructions(deps.agent_id)

    # Load current narrative
    narrative = deps.state_store.load_narrative(deps.agent_id)

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

    # Principles
    if identity.principles:
        parts.append("\n## Guiding Principles\n")
        conscious_principles = [p for p in identity.principles if p.chosen_consciously][:5]
        for principle in conscious_principles:
            parts.append(f"- {principle.statement}\n")

    # Goals
    if identity.goals:
        parts.append("\n## Current Goals\n")
        active_goals = [g for g in identity.goals if g.active][:3]
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

    # Behavioral guidelines
    parts.append("\n## Behavioral Guidelines\n")
    parts.append("- Record key moments during the session using record_key_moment tool\n")
    parts.append("- Be honest about what I don't know or can't do\n")
    parts.append("- Reflect on experiences to deepen self-understanding\n")

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
