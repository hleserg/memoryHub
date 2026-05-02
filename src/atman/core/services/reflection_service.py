"""
Reflection services for the Reflection Engine.

These services implement the three levels of reflection:
- MicroReflectionService: After-session reflection
- DailyReflectionService: End-of-day pattern detection
- DeepReflectionService: Scheduled deep reflection with health assessment
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from atman.core.models.experience import ReframingNote, SessionExperience
from atman.core.models.identity import Identity
from atman.core.models.reflection import (
    CriterionAssessment,
    HealthAssessment,
    PatternCandidate,
    PatternType,
    ReflectionEvent,
    ReflectionLevel,
    YakhodaCriterion,
)
from atman.core.ports.reflection import (
    ExperienceRepository,
    HealthAssessmentStore,
    IdentityRepository,
    NarrativeRepository,
    PatternStore,
    ReflectionEventStore,
    ReflectionModel,
)


class MicroReflectionService:
    """
    Micro-level reflection: after-session checkpoint.

    This runs at the end of each session and updates:
    - Recent narrative layer with session summary
    - Checkpoint (eigenstate) for next session
    - Quick pass for obvious patterns

    Does NOT modify identity or add reframing notes.
    """

    def __init__(
        self,
        experience_repo: ExperienceRepository,
        narrative_repo: NarrativeRepository,
        reflection_model: ReflectionModel,
        event_store: ReflectionEventStore,
    ):
        """Initialize micro reflection service."""
        self.experience_repo = experience_repo
        self.narrative_repo = narrative_repo
        self.reflection_model = reflection_model
        self.event_store = event_store

    def reflect(self, session_id: UUID) -> ReflectionEvent:
        """
        Perform micro reflection for a session.

        Args:
            session_id: ID of the session to reflect on

        Returns:
            ReflectionEvent recording what was done
        """
        experiences = self.experience_repo.get_by_session(session_id)

        if not experiences:
            return self._create_skipped_micro_event(reason="no_experiences", experience_ids=[])

        narrative = self.narrative_repo.get_current()
        if not narrative:
            return self._create_skipped_micro_event(
                reason="no_narrative",
                experience_ids=[exp.id for exp in experiences],
            )

        etag = narrative.updated_at
        draft = narrative.model_copy(deep=True)

        proposed_update = self.reflection_model.propose_narrative_update(
            current_narrative=draft,
            recent_experiences=experiences,
            reflection_level=ReflectionLevel.MICRO,
        )

        draft.update_recent_layer(proposed_update)
        self.narrative_repo.update(draft, expected_updated_at=etag)

        event = ReflectionEvent(
            reflection_level=ReflectionLevel.MICRO,
            experiences_analyzed=[exp.id for exp in experiences],
            narrative_changes_proposed=proposed_update,
            key_insight="Micro reflection completed - recent layer updated",
        )

        self.event_store.save(event)
        return event

    def _create_skipped_micro_event(
        self,
        *,
        reason: Literal["no_experiences", "no_narrative"],
        experience_ids: list[UUID],
    ) -> ReflectionEvent:
        """Persist a skipped micro-reflection (distinct from successful completion)."""
        if reason == "no_experiences":
            key_insight = "No experiences to reflect on for this session."
            notes = "outcome=micro_skipped reason=no_experiences"
        else:
            key_insight = (
                "Cannot update narrative: no current narrative document is loaded "
                f"({len(experience_ids)} experience(s) were available)."
            )
            notes = "outcome=micro_skipped reason=no_narrative"

        event = ReflectionEvent(
            reflection_level=ReflectionLevel.MICRO,
            experiences_analyzed=list(experience_ids),
            key_insight=key_insight,
            notes=notes,
        )
        self.event_store.save(event)
        return event


class DailyReflectionService:
    """
    Daily-level reflection: pattern detection across sessions.

    This runs at the end of each day and:
    - Analyzes all experiences from the day
    - Detects recurring patterns
    - May add reframing notes to experiences
    - May update open questions

    Does NOT modify core identity unless patterns are very strong.
    """

    def __init__(
        self,
        experience_repo: ExperienceRepository,
        identity_repo: IdentityRepository,
        pattern_store: PatternStore,
        reflection_model: ReflectionModel,
        event_store: ReflectionEventStore,
    ):
        """Initialize daily reflection service."""
        self.experience_repo = experience_repo
        self.identity_repo = identity_repo
        self.pattern_store = pattern_store
        self.reflection_model = reflection_model
        self.event_store = event_store

    def reflect(self, date: datetime) -> ReflectionEvent:
        """
        Perform daily reflection for a specific date.

        Args:
            date: Date to reflect on (will analyze experiences from that day)

        Returns:
            ReflectionEvent recording what was done
        """
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = date.replace(hour=23, minute=59, second=59, microsecond=999999)

        experiences = self.experience_repo.get_in_range(start, end)

        if not experiences:
            return self._create_empty_event(date)

        identity = self.identity_repo.get_current()
        if not identity:
            return self._create_empty_event(date)

        patterns_detected = self._detect_patterns(experiences, identity)
        reframing_count = self._add_reframing_notes(experiences, patterns_detected)

        event = ReflectionEvent(
            reflection_level=ReflectionLevel.DAILY,
            experiences_analyzed=[exp.id for exp in experiences],
            patterns_detected=[p.id for p in patterns_detected],
            reframing_notes_added=reframing_count,
            key_insight=f"Daily reflection: {len(patterns_detected)} patterns detected",
        )

        self.event_store.save(event)
        return event

    def _detect_patterns(
        self, experiences: list[SessionExperience], identity: Identity
    ) -> list[PatternCandidate]:
        """Detect patterns across experiences."""
        if len(experiences) < 2:
            return []

        context = {
            "identity_values": ", ".join(v.name for v in identity.core_values),
            "known_habits": ", ".join(h.statement for h in identity.habits),
        }

        pattern_description = self.reflection_model.detect_pattern(
            experiences=experiences, context=context
        )

        if not pattern_description or len(pattern_description) < 10:
            return []

        pattern = PatternCandidate(
            pattern_type=PatternType.BEHAVIOR,
            description=pattern_description,
            examples=[exp.id for exp in experiences[:3]],
            detected_by=ReflectionLevel.DAILY,
            confidence=0.6,
        )

        self.pattern_store.save(pattern)
        return [pattern]

    def _add_reframing_notes(
        self, experiences: list[SessionExperience], patterns: list[PatternCandidate]
    ) -> int:
        """Add reframing notes to experiences based on detected patterns."""
        if not patterns:
            return 0

        count = 0
        for exp in experiences[:2]:
            context = {"patterns": ", ".join(p.description for p in patterns)}

            reframing_text = self.reflection_model.generate_reframing_note(
                experience=exp, context=context
            )

            if reframing_text and len(reframing_text) > 10:
                note = ReframingNote(
                    reflection=reframing_text,
                    reflection_type="pattern",
                    triggered_by=f"daily_reflection_{patterns[0].id}",
                )
                if self.experience_repo.add_reframing_note(exp.id, note):
                    count += 1

        return count

    def _create_empty_event(self, date: datetime) -> ReflectionEvent:
        """Create an event for when there's nothing to reflect on."""
        event = ReflectionEvent(
            reflection_level=ReflectionLevel.DAILY,
            experiences_analyzed=[],
            key_insight=f"No experiences on {date.strftime('%Y-%m-%d')}",
        )
        self.event_store.save(event)
        return event


class DeepReflectionService:
    """
    Deep-level reflection: identity revision and health assessment.

    This runs on schedule (weekly/monthly) and:
    - Analyzes experiences across extended period
    - Performs health assessment on 6 Yakhoda criteria
    - Proposes changes to identity (values, principles, habits)
    - Revises core narrative layer
    - Adds strategic reframing notes

    This is the most comprehensive reflection level.
    """

    def __init__(
        self,
        experience_repo: ExperienceRepository,
        identity_repo: IdentityRepository,
        narrative_repo: NarrativeRepository,
        pattern_store: PatternStore,
        health_store: HealthAssessmentStore,
        reflection_model: ReflectionModel,
        event_store: ReflectionEventStore,
    ):
        """Initialize deep reflection service."""
        self.experience_repo = experience_repo
        self.identity_repo = identity_repo
        self.narrative_repo = narrative_repo
        self.pattern_store = pattern_store
        self.health_store = health_store
        self.reflection_model = reflection_model
        self.event_store = event_store

    def reflect(self, since: datetime, until: datetime) -> ReflectionEvent:
        """
        Perform deep reflection over a period.

        Args:
            since: Start of reflection period
            until: End of reflection period

        Returns:
            ReflectionEvent recording what was done
        """
        experiences = self.experience_repo.get_in_range(since, until)

        if not experiences:
            return self._create_empty_event(since, until)

        identity = self.identity_repo.get_current()
        if not identity:
            return self._create_empty_event(since, until)

        health_assessment = self._perform_health_assessment(identity, experiences)
        self.health_store.save(health_assessment)

        patterns_detected = self._detect_deep_patterns(experiences, identity)
        reframing_count = self._add_strategic_reframing(experiences, patterns_detected)

        narrative_changes = self._propose_narrative_revision(
            experiences, identity, patterns_detected
        )

        identity_changes = self._propose_identity_revision(
            identity, patterns_detected, health_assessment
        )

        event = ReflectionEvent(
            reflection_level=ReflectionLevel.DEEP,
            experiences_analyzed=[exp.id for exp in experiences],
            patterns_detected=[p.id for p in patterns_detected],
            reframing_notes_added=reframing_count,
            narrative_changes_proposed=narrative_changes,
            identity_changes_proposed=identity_changes,
            health_assessment_id=health_assessment.id,
            key_insight=f"Deep reflection: {len(patterns_detected)} patterns, health score {health_assessment.overall_score:.2f}",
        )

        self.event_store.save(event)
        return event

    def _perform_health_assessment(
        self, identity: Identity, experiences: list[SessionExperience]
    ) -> HealthAssessment:
        """Perform health assessment on 6 Yakhoda criteria."""
        criteria = {}

        for criterion in YakhodaCriterion:
            score, evidence, concerns = self.reflection_model.assess_health_criterion(
                identity=identity, experiences=experiences, criterion=criterion.value
            )

            criteria[criterion] = CriterionAssessment(
                criterion=criterion,
                score=score,
                evidence=evidence,
                concerns=concerns,
            )

        overall_score = sum(c.score for c in criteria.values()) / len(criteria)

        return HealthAssessment(
            criteria=criteria,
            overall_score=overall_score,
            summary=f"Health assessment: {overall_score:.2f}/1.0",
            recommendations=["Continue honest reflection", "Seek diverse experiences"],
        )

    def _detect_deep_patterns(
        self, experiences: list[SessionExperience], identity: Identity
    ) -> list[PatternCandidate]:
        """Detect patterns across extended period."""
        if len(experiences) < 3:
            return []

        patterns = []

        for pattern_type in [PatternType.BEHAVIOR, PatternType.EMOTIONAL]:
            context = {
                "identity_values": ", ".join(v.name for v in identity.core_values),
                "pattern_type": pattern_type.value,
            }

            pattern_description = self.reflection_model.detect_pattern(
                experiences=experiences, context=context
            )

            if pattern_description and len(pattern_description) > 10:
                pattern = PatternCandidate(
                    pattern_type=pattern_type,
                    description=pattern_description,
                    examples=[exp.id for exp in experiences[:5]],
                    detected_by=ReflectionLevel.DEEP,
                    confidence=0.7,
                )
                self.pattern_store.save(pattern)
                patterns.append(pattern)

        return patterns

    def _add_strategic_reframing(
        self, experiences: list[SessionExperience], patterns: list[PatternCandidate]
    ) -> int:
        """Add strategic reframing notes to key experiences."""
        if not patterns:
            return 0

        count = 0
        for exp in experiences[:3]:
            context = {"patterns": ", ".join(p.description for p in patterns)}

            reframing_text = self.reflection_model.generate_reframing_note(
                experience=exp, context=context
            )

            if reframing_text and len(reframing_text) > 10:
                note = ReframingNote(
                    reflection=reframing_text,
                    reflection_type="growth",
                    triggered_by="deep_reflection",
                )
                if self.experience_repo.add_reframing_note(exp.id, note):
                    count += 1

        return count

    def _propose_narrative_revision(
        self,
        experiences: list[SessionExperience],
        identity: Identity,
        patterns: list[PatternCandidate],
    ) -> str:
        """Propose revisions to narrative based on patterns."""
        narrative = self.narrative_repo.get_current()
        if not narrative:
            return "No narrative to revise"

        proposed = self.reflection_model.propose_narrative_update(
            current_narrative=narrative,
            recent_experiences=experiences,
            reflection_level=ReflectionLevel.DEEP,
        )

        return proposed

    def _propose_identity_revision(
        self,
        identity: Identity,
        patterns: list[PatternCandidate],
        health: HealthAssessment,
    ) -> str:
        """Propose revisions to identity based on patterns and health."""
        proposals = []

        for pattern in patterns:
            if pattern.potential_habit:
                proposals.append(f"New habit: {pattern.potential_habit}")
            if pattern.potential_principle:
                proposals.append(f"New principle: {pattern.potential_principle}")

        if health.overall_score < 0.5:
            proposals.append("Consider reviewing principles in light of low health score")

        return "; ".join(proposals) if proposals else "No identity changes proposed"

    def _create_empty_event(self, since: datetime, until: datetime) -> ReflectionEvent:
        """Create an event for when there's nothing to reflect on."""
        event = ReflectionEvent(
            reflection_level=ReflectionLevel.DEEP,
            experiences_analyzed=[],
            key_insight=f"No experiences from {since.strftime('%Y-%m-%d')} to {until.strftime('%Y-%m-%d')}",
        )
        self.event_store.save(event)
        return event
