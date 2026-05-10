"""
Helper utilities for persisting reflection outputs to ReflectionStore.

These functions bridge between:
- OllamaReflectionModel generated outputs (ReframingNoteOutput, NarrativeUpdateOutput, etc.)
- ReflectionStore persistence (ReflectionRecord)
"""

from datetime import datetime
from uuid import UUID

from atman.adapters.storage.postgres_reflection_models import ReflectionRecord
from atman.core.models.identity import Identity
from atman.core.models.reflection import (
    HealthAssessment,
    ReflectionLevel,
)
from atman.core.ports.reflection_store import ReflectionStore


def persist_micro_reflection(
    store: ReflectionStore,
    agent_id: UUID,
    session_id: UUID,
    content: str,
    *,
    summary: str | None = None,
    experience_refs: list[UUID] | None = None,
    reframing_note_ids: list[UUID] | None = None,
    model_provider: str | None = "ollama",
    model_name: str | None = None,
    created_at: datetime | None = None,
) -> ReflectionRecord:
    """
    Persist a micro-level reflection to storage.

    Args:
        store: ReflectionStore instance
        agent_id: Agent UUID
        session_id: Session UUID (populated for micro reflections)
        content: Generated reflection text
        summary: Optional short summary
        experience_refs: List of experience UUIDs analyzed
        reframing_note_ids: List of reframing note UUIDs created
        model_provider: LLM provider (default: 'ollama')
        model_name: Specific model used
        created_at: Timestamp (defaults to current time)

    Returns:
        Stored ReflectionRecord with assigned ID
    """
    record_params = {
        "agent_id": agent_id,
        "level": ReflectionLevel.MICRO,
        "session_id": session_id,
        "content": content,
        "summary": summary,
        "experience_refs": experience_refs or [],
        "reframing_note_ids": reframing_note_ids or [],
        "model_provider": model_provider,
        "model_name": model_name,
    }
    if created_at is not None:
        record_params["created_at"] = created_at

    record = ReflectionRecord(**record_params)
    return store.add(record)


def persist_daily_reflection(
    store: ReflectionStore,
    agent_id: UUID,
    period_start: datetime,
    period_end: datetime,
    content: str,
    *,
    summary: str | None = None,
    experience_refs: list[UUID] | None = None,
    reframing_note_ids: list[UUID] | None = None,
    model_provider: str | None = "ollama",
    model_name: str | None = None,
) -> ReflectionRecord:
    """
    Persist a daily reflection to storage.

    Args:
        store: ReflectionStore instance
        agent_id: Agent UUID
        period_start: Start of analyzed period
        period_end: End of analyzed period
        content: Generated reflection text
        summary: Optional short summary
        experience_refs: List of experience UUIDs analyzed
        reframing_note_ids: List of reframing note UUIDs created
        model_provider: LLM provider (default: 'ollama')
        model_name: Specific model used

    Returns:
        Stored ReflectionRecord with assigned ID
    """
    record = ReflectionRecord(
        agent_id=agent_id,
        level=ReflectionLevel.DAILY,
        period_start=period_start,
        period_end=period_end,
        content=content,
        summary=summary,
        experience_refs=experience_refs or [],
        reframing_note_ids=reframing_note_ids or [],
        model_provider=model_provider,
        model_name=model_name,
    )
    return store.add(record)


def persist_deep_reflection(
    store: ReflectionStore,
    agent_id: UUID,
    period_start: datetime,
    period_end: datetime,
    content: str,
    *,
    summary: str | None = None,
    experience_refs: list[UUID] | None = None,
    reframing_note_ids: list[UUID] | None = None,
    health_assessment: HealthAssessment | None = None,
    identity: Identity | None = None,
    model_provider: str | None = "ollama",
    model_name: str | None = None,
) -> ReflectionRecord:
    """
    Persist a deep reflection to storage.

    Deep reflections may include health assessment results and identity updates.
    These are stored in metadata field for now.

    Args:
        store: ReflectionStore instance
        agent_id: Agent UUID
        period_start: Start of analyzed period
        period_end: End of analyzed period
        content: Generated reflection text
        summary: Optional short summary
        experience_refs: List of experience UUIDs analyzed
        reframing_note_ids: List of reframing note UUIDs created
        health_assessment: Optional health assessment result
        identity: Optional identity snapshot
        model_provider: LLM provider (default: 'ollama')
        model_name: Specific model used

    Returns:
        Stored ReflectionRecord with assigned ID
    """
    metadata = {}
    if health_assessment:
        metadata["health_assessment_id"] = str(health_assessment.id)
        metadata["overall_health_score"] = health_assessment.overall_score
    if identity:
        metadata["identity_id"] = str(identity.id)
        metadata["emotional_baseline"] = identity.emotional_baseline

    record = ReflectionRecord(
        agent_id=agent_id,
        level=ReflectionLevel.DEEP,
        period_start=period_start,
        period_end=period_end,
        content=content,
        summary=summary,
        experience_refs=experience_refs or [],
        reframing_note_ids=reframing_note_ids or [],
        model_provider=model_provider,
        model_name=model_name,
        metadata=metadata,
    )
    return store.add(record)
