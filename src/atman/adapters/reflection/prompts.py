"""
Prompt templates for OllamaReflectionModel.

Each function builds a list of Ollama messages (system + user) for one
ReflectionModel method.  System prompts embed the JSON schema of the
expected output model so the LLM knows the exact structure to produce.
"""

import json
from typing import TypedDict

import pydantic

from atman.core.models.experience import SessionExperience
from atman.core.models.identity import Identity
from atman.core.models.narrative import NarrativeDocument
from atman.core.models.reflection import (
    HealthCriterionOutput,
    JahodaCriterion,
    NarrativeUpdateOutput,
    PatternDetectionOutput,
    ReflectionLevel,
    ReframingNoteOutput,
)


class OllamaMessage(TypedDict):
    """Type for Ollama API message."""

    role: str
    content: str


# ---------------------------------------------------------------------------
# Type alias used by callers
# ---------------------------------------------------------------------------
OllamaMessages = list[OllamaMessage]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _schema_block(model: type[pydantic.BaseModel]) -> str:
    """Return a compact JSON-schema string for *model*."""
    return json.dumps(model.model_json_schema(), indent=2)


def _experience_summary(exp: SessionExperience) -> str:
    """Compact textual summary of a single experience for prompt inclusion."""
    lines: list[str] = [f"Session {exp.session_id} ({exp.timestamp.isoformat()})"]
    for km in exp.key_moments:
        valence = km.how_i_felt.emotional_valence
        intensity = km.how_i_felt.emotional_intensity
        lines.append(
            f"  - {km.what_happened} "
            f"(valence={valence:+.2f}, intensity={intensity:.2f}, "
            f"depth={km.how_i_felt.depth.value})"
        )
        if km.values_touched:
            lines.append(f"    values touched: {', '.join(km.values_touched)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1. generate_reframing_note
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_REFRAMING = """\
You are the introspective layer of an AI agent performing micro-reflection.

Given an experience and optional context, produce a reframing note — a new
perspective or insight about the experience.

Respond ONLY with valid JSON matching this schema (no preamble, no markdown):
{schema}
"""


def build_reframing_messages(
    experience: SessionExperience,
    context: dict[str, str],
    output_model: type[ReframingNoteOutput] = ReframingNoteOutput,
) -> OllamaMessages:
    """Build Ollama messages for :meth:`generate_reframing_note`."""
    system = SYSTEM_PROMPT_REFRAMING.format(schema=_schema_block(output_model))

    user_parts = [
        "## Experience",
        _experience_summary(experience),
    ]
    if context:
        user_parts.append("\n## Context")
        for key, value in context.items():
            user_parts.append(f"- {key}: {value}")

    return [
        OllamaMessage(role="system", content=system),
        OllamaMessage(role="user", content="\n".join(user_parts)),
    ]


# ---------------------------------------------------------------------------
# 2. detect_pattern
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_PATTERN = """\
You are the analytical layer of an AI agent performing pattern detection.

Given a set of experiences and optional context, detect a recurring behavioral,
emotional, or cognitive pattern.  If no clear pattern exists, return an empty
description.

Respond ONLY with valid JSON matching this schema (no preamble, no markdown):
{schema}
"""


def build_pattern_messages(
    experiences: list[SessionExperience],
    context: dict[str, str],
    output_model: type[PatternDetectionOutput] = PatternDetectionOutput,
) -> OllamaMessages:
    """Build Ollama messages for :meth:`detect_pattern`."""
    system = SYSTEM_PROMPT_PATTERN.format(schema=_schema_block(output_model))

    user_parts = ["## Experiences"]
    for exp in experiences:
        user_parts.append(_experience_summary(exp))
        user_parts.append("")

    if context:
        user_parts.append("## Context")
        for key, value in context.items():
            user_parts.append(f"- {key}: {value}")

    return [
        OllamaMessage(role="system", content=system),
        OllamaMessage(role="user", content="\n".join(user_parts)),
    ]


# ---------------------------------------------------------------------------
# 3. propose_narrative_update
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_NARRATIVE = """\
You are the narrative layer of an AI agent updating its self-narrative.

Given the current narrative document and recent experiences, propose an update
to the narrative.  The body should be written in first person and reflect what
the agent has learned or experienced.

Reflection level: {level}

Respond ONLY with valid JSON matching this schema (no preamble, no markdown):
{schema}
"""


def build_narrative_messages(
    current_narrative: NarrativeDocument,
    recent_experiences: list[SessionExperience],
    reflection_level: ReflectionLevel,
    output_model: type[NarrativeUpdateOutput] = NarrativeUpdateOutput,
) -> OllamaMessages:
    """Build Ollama messages for :meth:`propose_narrative_update`."""
    system = SYSTEM_PROMPT_NARRATIVE.format(
        level=reflection_level.value,
        schema=_schema_block(output_model),
    )

    user_parts = [
        "## Current Narrative",
        f"Core layer: {current_narrative.core_layer.content}",
        f"Recent layer: {current_narrative.recent_layer.content}",
        "",
        "## Recent Experiences",
    ]
    for exp in recent_experiences:
        user_parts.append(_experience_summary(exp))
        user_parts.append("")

    return [
        OllamaMessage(role="system", content=system),
        OllamaMessage(role="user", content="\n".join(user_parts)),
    ]


# ---------------------------------------------------------------------------
# 4. assess_health_criterion
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_HEALTH = """\
You are the psychological health assessment layer of an AI agent.

Assess the agent on the Jahoda criterion: **{criterion}**.
Use the identity and recent experiences as evidence.

Respond ONLY with valid JSON matching this schema (no preamble, no markdown):
{schema}
"""


def build_health_messages(
    identity: Identity,
    experiences: list[SessionExperience],
    criterion: JahodaCriterion,
    output_model: type[HealthCriterionOutput] = HealthCriterionOutput,
) -> OllamaMessages:
    """Build Ollama messages for :meth:`assess_health_criterion`."""
    system = SYSTEM_PROMPT_HEALTH.format(
        criterion=criterion.value,
        schema=_schema_block(output_model),
    )

    user_parts = [
        "## Identity",
        f"Self-description: {identity.self_description}",
    ]
    if identity.core_values:
        user_parts.append("Core values: " + ", ".join(v.name for v in identity.core_values))
    if identity.principles:
        user_parts.append("Principles: " + ", ".join(p.statement for p in identity.principles))

    user_parts.append("")
    user_parts.append("## Recent Experiences")
    for exp in experiences:
        user_parts.append(_experience_summary(exp))
        user_parts.append("")

    return [
        OllamaMessage(role="system", content=system),
        OllamaMessage(role="user", content="\n".join(user_parts)),
    ]
