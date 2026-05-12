"""
Mock implementation of ReflectionModel for testing.

This provides deterministic, template-based responses instead of LLM generation.
Useful for testing reflection logic without external dependencies.
"""
# PLAYBOOK-START
# id: port-deterministic-mock-for-llm-dependencies
# category: design-patterns
# title: Port + Deterministic Mock Adapter for LLM-Dependent Logic
# status: refined
#
# Pattern: define an abstract port that the service depends on (here:
# ReflectionModel). Provide a deterministic mock implementation that returns
# template-based, semantically meaningful responses based on input content —
# NOT random, NOT a stub that returns empty strings, NOT a spy. The mock
# exercises the same code paths as a real LLM adapter, including output
# parsing, error routing, and result handling, but with zero network calls
# and zero stochastic behavior. All business logic is testable at unit speed.
#
# Why generalizable: any feature calling an LLM, embedding model, external
# API, or other probabilistic service. Without deterministic mocks, tests
# either skip the integration entirely (low confidence) or hit real APIs
# (slow, expensive, flaky). This pattern provides a third path: full
# integration test coverage at unit test speed.
#
# Trade-offs: mock must be maintained alongside the real adapter; divergence
# between mock behavior and real LLM output can hide integration bugs.
# Mitigate by running a small set of real-API smoke tests separately.
# PLAYBOOK-END

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
from atman.core.ports.reflection import ReflectionModel
from atman.core.ports.state_store import StateStore


class MockReflectionModel(ReflectionModel):
    """
    Mock implementation of ReflectionModel.

    Generates deterministic, template-based outputs for testing.
    Does NOT use an actual LLM.
    """

    def __init__(self, state_store: StateStore | None = None):
        """
        Initialize mock reflection model.

        Args:
            state_store: Optional state store for fetching KeyMoments by ID.
                        If not provided, will use SessionExperience metadata only.
        """
        self._state_store = state_store

    def generate_reframing_note(
        self,
        experience: SessionExperience,
        context: dict[str, str],
    ) -> ReframingNoteOutput:
        """
        Generate a mock reframing note.

        Uses template-based generation with context.
        """
        patterns = context.get("patterns", "")

        if patterns:
            text = (
                f"Looking back, I notice this experience fits a pattern: {patterns}. "
                "This helps me understand my tendencies better."
            )
            return ReframingNoteOutput(reflection=text, reflection_type="pattern")

        text = "Reflecting on this experience, I see it differently now with more context."
        return ReframingNoteOutput(reflection=text, reflection_type="insight")

    def detect_pattern(
        self,
        experiences: list[SessionExperience],
        context: dict[str, str],
    ) -> PatternDetectionOutput:
        """
        Generate a mock pattern description.

        Analyzes experiences to find simple patterns.
        """
        if len(experiences) < 2:
            return PatternDetectionOutput()

        emotional_valences = []
        for exp in experiences:
            # Use metadata instead of accessing key moments
            # avg_emotional_intensity is between 0-1, convert to -1 to 1 valence estimate
            # This is a rough approximation for pattern detection
            if exp.has_profound_moment:
                # Profound moments tend to have stronger emotional charge
                valence_estimate = (exp.avg_emotional_intensity - 0.5) * 2
            else:
                valence_estimate = (exp.avg_emotional_intensity - 0.5) * 1.5
            emotional_valences.append(valence_estimate)

        if not emotional_valences:
            return PatternDetectionOutput()

        avg_valence = sum(emotional_valences) / len(emotional_valences)

        if avg_valence > 0.3:
            desc = "I tend to approach challenges with positive energy and curiosity"
        elif avg_valence < -0.3:
            desc = "I often feel uncertain or concerned when facing new situations"
        else:
            desc = "I experience mixed emotions across different situations"

        return PatternDetectionOutput(
            description=desc,
            confidence=0.65,
            potential_habit="",
            potential_principle="",
        )

    def propose_narrative_update(
        self,
        current_narrative: NarrativeDocument,
        recent_experiences: list[SessionExperience],
        reflection_level: ReflectionLevel,
    ) -> NarrativeUpdateOutput:
        """
        Generate a mock narrative update proposal.

        Creates a simple summary based on experiences.
        """
        if not recent_experiences:
            return NarrativeUpdateOutput(body="No new experiences to incorporate.")

        exp_count = len(recent_experiences)

        if reflection_level == ReflectionLevel.MICRO:
            if exp_count == 1:
                exp = recent_experiences[0]
                # Try to get the first key moment if state_store is available
                if exp.key_moment_ids and self._state_store:
                    first_moment = self._state_store.get_key_moment(exp.key_moment_ids[0])
                    if first_moment:
                        body = (
                            f"Just finished a session where {first_moment.what_happened}. "
                            f"{first_moment.why_it_matters}"
                        )
                        return NarrativeUpdateOutput(body=body)
            body = f"Just finished a session with {exp_count} key experiences."
            return NarrativeUpdateOutput(body=body)

        if reflection_level == ReflectionLevel.DAILY:
            body = (
                f"Today I had {exp_count} meaningful experiences. "
                "I'm continuing to learn and adapt."
            )
            return NarrativeUpdateOutput(body=body)

        body = (
            f"Over this period, I've had {exp_count} significant experiences. "
            "I'm developing a clearer sense of my patterns and tendencies."
        )
        return NarrativeUpdateOutput(body=body)

    def assess_health_criterion(
        self,
        identity: Identity,
        experiences: list[SessionExperience],
        criterion: JahodaCriterion,
    ) -> HealthCriterionOutput:
        """
        Generate a mock health criterion assessment.

        Returns score, evidence, concerns based on simple heuristics.
        """
        if criterion == JahodaCriterion.POSITIVE_SELF_ATTITUDE:
            if identity.self_description:
                return HealthCriterionOutput(
                    score=0.6,
                    evidence=["Has self-description", "Shows self-awareness"],
                    concerns=["Still developing self-understanding"],
                )
            return HealthCriterionOutput(
                score=0.4,
                evidence=["Limited self-description"],
                concerns=["Still developing self-understanding"],
            )

        if criterion == JahodaCriterion.GROWTH_AND_ACTUALIZATION:
            if identity.goals:
                return HealthCriterionOutput(
                    score=0.7,
                    evidence=[f"Has {len(identity.goals)} goals"],
                    concerns=["Could articulate growth direction more clearly"],
                )
            return HealthCriterionOutput(
                score=0.5,
                evidence=["No explicit goals set"],
                concerns=["Could articulate growth direction more clearly"],
            )

        if criterion == JahodaCriterion.INTEGRATION:
            if identity.principles and identity.habits:
                return HealthCriterionOutput(
                    score=0.6,
                    evidence=["Has both principles and observed habits"],
                    concerns=["Still learning to align actions with values"],
                )
            return HealthCriterionOutput(
                score=0.4,
                evidence=["Limited integration of values and behavior"],
                concerns=["Still learning to align actions with values"],
            )

        if criterion == JahodaCriterion.AUTONOMY:
            conscious_principles = [p for p in identity.principles if p.chosen_consciously]
            if conscious_principles:
                return HealthCriterionOutput(
                    score=0.7,
                    evidence=[f"{len(conscious_principles)} consciously chosen principles"],
                    concerns=["Could develop more autonomous decision-making"],
                )
            return HealthCriterionOutput(
                score=0.5,
                evidence=["Few consciously chosen principles"],
                concerns=["Could develop more autonomous decision-making"],
            )

        if criterion == JahodaCriterion.REALITY_PERCEPTION:
            if experiences:
                return HealthCriterionOutput(
                    score=0.6,
                    evidence=[f"Has {len(experiences)} recorded experiences"],
                    concerns=["Need more experience to assess reality perception"],
                )
            return HealthCriterionOutput(
                score=0.4,
                evidence=["Limited experience base"],
                concerns=["Need more experience to assess reality perception"],
            )

        if criterion == JahodaCriterion.ENVIRONMENTAL_MASTERY:
            helpful_habits = [h for h in identity.habits if h.helpfulness.value == "helpful"]
            if helpful_habits:
                return HealthCriterionOutput(
                    score=0.6,
                    evidence=[f"{len(helpful_habits)} helpful habits"],
                    concerns=["Could develop more effective coping strategies"],
                )
            return HealthCriterionOutput(
                score=0.5,
                evidence=["Limited helpful habits identified"],
                concerns=["Could develop more effective coping strategies"],
            )

        raise ValueError(f"Unsupported Jahoda criterion: {criterion!r}")
