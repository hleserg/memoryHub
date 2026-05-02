"""
Mock implementation of ReflectionModel for testing.

This provides deterministic, template-based responses instead of LLM generation.
Useful for testing reflection logic without external dependencies.
"""

from atman.core.models.experience import SessionExperience
from atman.core.models.identity import Identity
from atman.core.models.narrative import NarrativeDocument
from atman.core.models.reflection import JahodaCriterion, ReflectionLevel
from atman.core.ports.reflection import ReflectionModel


class MockReflectionModel(ReflectionModel):
    """
    Mock implementation of ReflectionModel.

    Generates deterministic, template-based outputs for testing.
    Does NOT use an actual LLM.
    """

    def generate_reframing_note(
        self,
        experience: SessionExperience,
        context: dict[str, str],
    ) -> str:
        """
        Generate a mock reframing note.

        Uses template-based generation with context.
        """
        patterns = context.get("patterns", "")

        if patterns:
            return (
                f"Looking back, I notice this experience fits a pattern: {patterns}. "
                "This helps me understand my tendencies better."
            )

        return "Reflecting on this experience, I see it differently now with more context."

    def detect_pattern(
        self,
        experiences: list[SessionExperience],
        context: dict[str, str],
    ) -> str:
        """
        Generate a mock pattern description.

        Analyzes experiences to find simple patterns.
        """
        if len(experiences) < 2:
            return ""

        emotional_valences = []
        for exp in experiences:
            if exp.key_moments:
                avg_valence = sum(m.how_i_felt.emotional_valence for m in exp.key_moments) / len(
                    exp.key_moments
                )
                emotional_valences.append(avg_valence)

        if not emotional_valences:
            return ""

        avg_valence = sum(emotional_valences) / len(emotional_valences)

        if avg_valence > 0.3:
            return "I tend to approach challenges with positive energy and curiosity"
        elif avg_valence < -0.3:
            return "I often feel uncertain or concerned when facing new situations"
        else:
            return "I experience mixed emotions across different situations"

    def propose_narrative_update(
        self,
        current_narrative: NarrativeDocument,
        recent_experiences: list[SessionExperience],
        reflection_level: ReflectionLevel,
    ) -> str:
        """
        Generate a mock narrative update proposal.

        Creates a simple summary based on experiences.
        """
        if not recent_experiences:
            return "No new experiences to incorporate."

        exp_count = len(recent_experiences)

        if reflection_level == ReflectionLevel.MICRO:
            if exp_count == 1:
                exp = recent_experiences[0]
                if exp.key_moments:
                    return (
                        f"Just finished a session where {exp.key_moments[0].what_happened}. "
                        f"{exp.key_moments[0].why_it_matters}"
                    )
            return f"Just finished a session with {exp_count} key experiences."

        elif reflection_level == ReflectionLevel.DAILY:
            return (
                f"Today I had {exp_count} meaningful experiences. "
                "I'm continuing to learn and adapt."
            )

        else:
            return (
                f"Over this period, I've had {exp_count} significant experiences. "
                "I'm developing a clearer sense of my patterns and tendencies."
            )

    def assess_health_criterion(
        self,
        identity: Identity,
        experiences: list[SessionExperience],
        criterion: JahodaCriterion,
    ) -> tuple[float, list[str], list[str]]:
        """
        Generate a mock health criterion assessment.

        Returns (score, evidence, concerns) based on simple heuristics.
        """
        if criterion == JahodaCriterion.POSITIVE_SELF_ATTITUDE:
            if identity.self_description:
                score = 0.6
                evidence = ["Has self-description", "Shows self-awareness"]
            else:
                score = 0.4
                evidence = ["Limited self-description"]
            concerns = ["Still developing self-understanding"]
            return (score, evidence, concerns)

        if criterion == JahodaCriterion.GROWTH_AND_ACTUALIZATION:
            if identity.goals:
                score = 0.7
                evidence = [f"Has {len(identity.goals)} goals"]
            else:
                score = 0.5
                evidence = ["No explicit goals set"]
            concerns = ["Could articulate growth direction more clearly"]
            return (score, evidence, concerns)

        if criterion == JahodaCriterion.INTEGRATION:
            if identity.principles and identity.habits:
                score = 0.6
                evidence = ["Has both principles and observed habits"]
            else:
                score = 0.4
                evidence = ["Limited integration of values and behavior"]
            concerns = ["Still learning to align actions with values"]
            return (score, evidence, concerns)

        if criterion == JahodaCriterion.AUTONOMY:
            conscious_principles = [p for p in identity.principles if p.chosen_consciously]
            if conscious_principles:
                score = 0.7
                evidence = [f"{len(conscious_principles)} consciously chosen principles"]
            else:
                score = 0.5
                evidence = ["Few consciously chosen principles"]
            concerns = ["Could develop more autonomous decision-making"]
            return (score, evidence, concerns)

        if criterion == JahodaCriterion.REALITY_PERCEPTION:
            if experiences:
                score = 0.6
                evidence = [f"Has {len(experiences)} recorded experiences"]
            else:
                score = 0.4
                evidence = ["Limited experience base"]
            concerns = ["Need more experience to assess reality perception"]
            return (score, evidence, concerns)

        if criterion == JahodaCriterion.ENVIRONMENTAL_MASTERY:
            helpful_habits = [h for h in identity.habits if h.helpfulness.value == "helpful"]
            if helpful_habits:
                score = 0.6
                evidence = [f"{len(helpful_habits)} helpful habits"]
            else:
                score = 0.5
                evidence = ["Limited helpful habits identified"]
            concerns = ["Could develop more effective coping strategies"]
            return (score, evidence, concerns)

        raise ValueError(f"Unsupported Jahoda criterion: {criterion!r}")
