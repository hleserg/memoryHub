"""
Prompt templates for OllamaReflectionModel.

Each function builds a list of Ollama messages (system + user) for one
ReflectionModel method.  System prompts embed the JSON schema of the
expected output model so the LLM knows the exact structure to produce.
"""

import json
from typing import TypedDict
from uuid import UUID

import pydantic

from atman.core.models.entity import Entity
from atman.core.models.experience import KeyMoment, SessionExperience
from atman.core.models.identity import Identity
from atman.core.models.narrative import NarrativeDocument
from atman.core.models.reflection import (
    EntityRelationFormulationOutput,
    HealthCriterionOutput,
    JahodaCriterion,
    MergeDecisionOutput,
    NarrativeUpdateOutput,
    PatternDetectionOutput,
    ReflectionLevel,
    ReframingNoteOutput,
    StanceFormulationOutput,
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


# HLE-46: cap moment content fed into reflection prompts so a few large
# sessions can't blow up the LLM context window. Three moments × 200 chars of
# free-text per session keeps each session block well under ~1 KB while still
# giving the model the actual story (not just counters).
_MAX_MOMENTS_PER_SESSION_IN_PROMPT = 3
_MAX_WHAT_HAPPENED_CHARS = 200
_MAX_WHY_IT_MATTERS_CHARS = 200


def _truncate(text: str, limit: int) -> str:
    """Trim *text* to *limit* characters, appending an ellipsis on truncation."""
    if len(text) <= limit:
        return text
    # Reserve 1 char for the ellipsis marker so total length stays at *limit*.
    return text[: max(0, limit - 1)] + "…"


def _moment_summary_for_experience(m: KeyMoment) -> str:
    """Render one KeyMoment compactly inside an experience block.

    Mirrors :func:`_moment_summary_for_stance` but truncates free-text fields
    to bound prompt size (see ``_MAX_*`` constants above).
    """
    what = _truncate(m.what_happened, _MAX_WHAT_HAPPENED_CHARS)
    why = _truncate(m.why_it_matters, _MAX_WHY_IT_MATTERS_CHARS)
    parts = [
        f"  - [{m.when.isoformat()}] {what}",
        f"      felt: valence={m.how_i_felt.emotional_valence:+.2f} "
        f"intensity={m.how_i_felt.emotional_intensity:.2f} depth={m.how_i_felt.depth.value}",
        f"      why_it_matters: {why}",
    ]
    if m.values_touched:
        parts.append(f"      values_touched: {', '.join(m.values_touched)}")
    return "\n".join(parts)


def _experience_summary(
    exp: SessionExperience,
    moments: list[KeyMoment] | None = None,
) -> str:
    """Compact textual summary of a single experience for prompt inclusion.

    When *moments* is provided, the top-N (by salience desc, capped at
    ``_MAX_MOMENTS_PER_SESSION_IN_PROMPT``) are rendered with their actual
    ``what_happened`` / ``why_it_matters`` / ``values_touched`` so the LLM
    can see the story behind the stats (HLE-46). Empty / missing moments
    fall back to the legacy counters-only summary.
    """
    lines: list[str] = [f"Session {exp.session_id} ({exp.timestamp.isoformat()})"]
    # Use metadata instead of iterating through key moments (which are now stored separately)
    lines.append(
        f"  - {len(exp.key_moment_ids)} key moments "
        f"(avg_intensity={exp.avg_emotional_intensity:.2f}, "
        f"profound={exp.has_profound_moment})"
    )
    if exp.fact_refs:
        lines.append(f"    facts accessed: {len(exp.fact_refs)} total")

    if moments:
        ranked = sorted(moments, key=lambda m: m.salience, reverse=True)
        top = ranked[:_MAX_MOMENTS_PER_SESSION_IN_PROMPT]
        if top:
            lines.append(f"  top {len(top)} of {len(moments)} moments by salience:")
            for m in top:
                lines.append(_moment_summary_for_experience(m))
    return "\n".join(lines)


def _moments_for(
    exp: SessionExperience,
    key_moments_by_session: dict[UUID, list[KeyMoment]] | None,
) -> list[KeyMoment] | None:
    """Look up KeyMoments for *exp* in the per-session mapping, if provided."""
    if key_moments_by_session is None:
        return None
    return key_moments_by_session.get(exp.session_id)


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
    *,
    key_moments_by_session: dict[UUID, list[KeyMoment]] | None = None,
) -> OllamaMessages:
    """Build Ollama messages for :meth:`generate_reframing_note`."""
    system = SYSTEM_PROMPT_REFRAMING.format(schema=_schema_block(output_model))

    user_parts = [
        "## Experience",
        _experience_summary(experience, _moments_for(experience, key_moments_by_session)),
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
    *,
    key_moments_by_session: dict[UUID, list[KeyMoment]] | None = None,
) -> OllamaMessages:
    """Build Ollama messages for :meth:`detect_pattern`."""
    system = SYSTEM_PROMPT_PATTERN.format(schema=_schema_block(output_model))

    user_parts = ["## Experiences"]
    for exp in experiences:
        user_parts.append(_experience_summary(exp, _moments_for(exp, key_moments_by_session)))
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
    *,
    key_moments_by_session: dict[UUID, list[KeyMoment]] | None = None,
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
        user_parts.append(_experience_summary(exp, _moments_for(exp, key_moments_by_session)))
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


# ---------------------------------------------------------------------------
# 5. formulate_entity_stance (R7 — REFLECTION_FUTURE.md §4.3, §9)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_STANCE = """\
You are the introspective layer of an AI agent putting into words how it
currently relates to a specific entity (a person, place, topic, etc).

You will be given:
  - the entity's canonical name and type;
  - a chronological list of KeyMoments where that entity was involved;
  - optional rolled-up structured_markers from those moments.

This is **interpretation**, not aggregation. Read the moments and describe,
in first person, the agent's current stance toward the entity: what it is,
what it feels like, what stays unresolved. Do **not** compute averages of
numeric fields and do **not** invent facts that aren't in the moments.

If the moments are too thin or contradictory to commit to a stance, return
an empty `stance_text` — the service will treat that as "decline" and try
again next cycle.

Estimate `valence_estimate` and `intensity_estimate` from the overall feel
of the moments (interpretation, not arithmetic). Set `confidence` to how
much you trust this formulation given the available evidence.

Respond ONLY with valid JSON matching this schema (no preamble, no markdown):
{schema}
"""


def _moment_summary_for_stance(m: KeyMoment) -> str:
    """Compact textual summary of one KeyMoment for the stance prompt."""
    parts = [
        f"  - [{m.when.isoformat()}] {m.what_happened}",
        f"      felt: valence={m.how_i_felt.emotional_valence:+.2f} "
        f"intensity={m.how_i_felt.emotional_intensity:.2f} depth={m.how_i_felt.depth.value}",
        f"      why_it_matters: {m.why_it_matters}",
    ]
    if m.values_touched:
        parts.append(f"      values_touched: {', '.join(m.values_touched)}")
    if m.structured_markers:
        marker_bits = ", ".join(f"{k}={v}" for k, v in m.structured_markers.items())
        parts.append(f"      markers: {marker_bits}")
    return "\n".join(parts)


def build_stance_formulation_messages(
    entity: Entity,
    moments: list[KeyMoment],
    structured_markers: dict[str, int] | None = None,
    output_model: type[StanceFormulationOutput] = StanceFormulationOutput,
) -> OllamaMessages:
    """Build Ollama messages for :meth:`formulate_entity_stance`."""
    system = SYSTEM_PROMPT_STANCE.format(schema=_schema_block(output_model))

    user_parts = [
        "## Entity",
        f"- canonical_name: {entity.canonical_name}",
        f"- type: {entity.entity_type.value}",
    ]
    if entity.description:
        user_parts.append(f"- description: {entity.description}")
    user_parts.append("")
    user_parts.append(f"## Moments ({len(moments)} involving this entity)")
    for m in moments:
        user_parts.append(_moment_summary_for_stance(m))
    if structured_markers:
        user_parts.append("")
        user_parts.append("## Rolled-up structured_markers")
        for key, count in sorted(structured_markers.items()):
            user_parts.append(f"- {key}: {count}")

    return [
        OllamaMessage(role="system", content=system),
        OllamaMessage(role="user", content="\n".join(user_parts)),
    ]


def build_health_messages(
    identity: Identity,
    experiences: list[SessionExperience],
    criterion: JahodaCriterion,
    output_model: type[HealthCriterionOutput] = HealthCriterionOutput,
    *,
    key_moments_by_session: dict[UUID, list[KeyMoment]] | None = None,
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
        user_parts.append(_experience_summary(exp, _moments_for(exp, key_moments_by_session)))
        user_parts.append("")

    return [
        OllamaMessage(role="system", content=system),
        OllamaMessage(role="user", content="\n".join(user_parts)),
    ]


# ---------------------------------------------------------------------------
# 5. formulate_entity_relation (R9 — REFLECTION_FUTURE.md §5.3)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_ENTITY_RELATION = """\
You are the introspective layer of an AI agent deciding whether two entities
that often appear together in the agent's KeyMoments are actually related in
some meaningful, typed way.

You will be given:
  - the two entities' canonical names and types;
  - a chronological list of shared KeyMoments where both are involved.

Rules:
  - Return an empty `relation_type` when the evidence is thin or contradictory.
    Better silence than an invented relation.
  - When you do commit, prefer canonical, lowercase, snake_case labels
    (e.g. `colleague_of`, `lives_in`, `co_authored`, `mentions`).
  - This is **deep reflection**, not real-time extraction; only commit when the
    pattern is clear across multiple moments, not a single mention.

Respond ONLY with valid JSON matching this schema (no preamble, no markdown):
{schema}
"""


def _moment_summary_for_relation(m: KeyMoment) -> str:
    """Compact textual summary of one KeyMoment for the relation prompt."""
    return f"  - [{m.when.isoformat()}] {m.what_happened}\n      why_it_matters: {m.why_it_matters}"


def build_entity_relation_messages(
    entity_a: Entity,
    entity_b: Entity,
    shared_moments: list[KeyMoment],
    output_model: type[EntityRelationFormulationOutput] = EntityRelationFormulationOutput,
) -> OllamaMessages:
    """Build Ollama messages for :meth:`formulate_entity_relation`."""
    system = SYSTEM_PROMPT_ENTITY_RELATION.format(schema=_schema_block(output_model))

    user_parts = [
        "## Entities",
        f"- A: '{entity_a.canonical_name}' ({entity_a.entity_type.value})",
        f"- B: '{entity_b.canonical_name}' ({entity_b.entity_type.value})",
        "",
        f"## Shared moments ({len(shared_moments)})",
    ]
    for m in shared_moments:
        user_parts.append(_moment_summary_for_relation(m))

    return [
        OllamaMessage(role="system", content=system),
        OllamaMessage(role="user", content="\n".join(user_parts)),
    ]


# ---------------------------------------------------------------------------
# 6. decide_entity_merge (R10 — REFLECTION_FUTURE.md §5.4)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_ENTITY_MERGE = """\
You are the introspective layer of an AI agent deciding whether two
near-duplicate entities flagged by the memory guardian are actually the
same subject.

You will be given:
  - the two entities' canonical names and types;
  - up to N recent KeyMoments for each (separately, so you can compare
    contexts).

Rules:
  - Default to **not** merging. Only confirm when the contexts clearly
    describe the same subject.
  - When confirming, pick the more canonical name for ``canonical_name``
    (the one that's least abbreviated, least context-specific).
  - Provide a short ``reason`` either way — it's written to the
    validation finding's resolution note.
  - Different `entity_type` between A and B is a strong "do not merge"
    signal; mention that in ``reason``.

Respond ONLY with valid JSON matching this schema (no preamble, no markdown):
{schema}
"""


def _moment_summary_for_merge(m: KeyMoment) -> str:
    """Compact textual summary of one KeyMoment for the merge prompt."""
    return f"    - [{m.when.isoformat()}] {m.what_happened}"


def build_entity_merge_messages(
    entity_a: Entity,
    entity_b: Entity,
    contexts_a: list[KeyMoment],
    contexts_b: list[KeyMoment],
    output_model: type[MergeDecisionOutput] = MergeDecisionOutput,
) -> OllamaMessages:
    """Build Ollama messages for :meth:`decide_entity_merge`."""
    system = SYSTEM_PROMPT_ENTITY_MERGE.format(schema=_schema_block(output_model))

    user_parts = [
        "## Entity A",
        f"- canonical_name: {entity_a.canonical_name}",
        f"- type: {entity_a.entity_type.value}",
        f"  ### A moments ({len(contexts_a)})",
    ]
    for m in contexts_a:
        user_parts.append(_moment_summary_for_merge(m))
    user_parts.append("")
    user_parts.append("## Entity B")
    user_parts.append(f"- canonical_name: {entity_b.canonical_name}")
    user_parts.append(f"- type: {entity_b.entity_type.value}")
    user_parts.append(f"  ### B moments ({len(contexts_b)})")
    for m in contexts_b:
        user_parts.append(_moment_summary_for_merge(m))

    return [
        OllamaMessage(role="system", content=system),
        OllamaMessage(role="user", content="\n".join(user_parts)),
    ]
