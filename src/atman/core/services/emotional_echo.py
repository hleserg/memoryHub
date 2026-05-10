"""
EmotionalEcho - historical emotional context builder.

Provides historical emotional context from past experiences,
sorted by recency × intensity for emotional continuity.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from atman.core.models.experience import EmotionalDepth
from atman.core.ports.state_store import StateStore


@dataclass
class EchoItem:
    """A single emotional echo from a past experience."""

    experience_id: str
    timestamp: datetime
    emotional_valence: float
    emotional_intensity: float
    depth: EmotionalDepth
    what_happened: str
    recency_score: float  # Calculated: higher = more recent
    intensity_score: float  # Calculated: higher = more intense
    echo_score: float  # Combined recency × intensity


class EmotionalEcho:
    """
    Historical emotional context builder.

    Aggregates emotional context from past experiences to provide
    emotional continuity - like how a person carries emotional
    residue from recent significant events.
    """

    def __init__(
        self,
        state_store: StateStore,
        lookback_days: int = 7,
        max_echoes: int = 5,
        recency_halflife_hours: float = 24.0,
    ) -> None:
        """
        Initialize EmotionalEcho.

        Args:
            state_store: Storage for experiences
            lookback_days: How many days back to consider
            max_echoes: Maximum number of echoes to return
            recency_halflife_hours: Hours for recency score to halve
        """
        self.state_store = state_store
        self.lookback_days = lookback_days
        self.max_echoes = max_echoes
        self.recency_halflife = recency_halflife_hours

    def build_echo(
        self,
        exclude_session_id: str | None = None,
        current_time: datetime | None = None,
    ) -> list[EchoItem]:
        """
        Build emotional echo from recent experiences.

        Args:
            exclude_session_id: Optional session to exclude (current session)
            current_time: Reference time for recency calculation

        Returns:
            list[EchoItem]: Sorted echoes by recency × intensity
        """
        if current_time is None:
            current_time = datetime.now(UTC)

        # Query recent experiences using lookback window
        from datetime import timedelta

        since = current_time - timedelta(days=self.lookback_days)

        # Use list_recent_experiences to get recent experiences, then filter by date
        experience_records = self.state_store.list_recent_experiences(limit=100)
        experiences = [
            exp.experience for exp in experience_records if exp.experience.timestamp >= since
        ]

        # Filter and score
        echoes: list[EchoItem] = []
        for exp in experiences:
            if exclude_session_id and str(exp.session_id) == exclude_session_id:
                continue

            # Calculate recency score (exponential decay)
            hours_ago = (current_time - exp.timestamp).total_seconds() / 3600
            recency_score = 2 ** (-hours_ago / self.recency_halflife)

            # Process each key moment
            for moment in exp.key_moments:
                felt = moment.how_i_felt

                # Intensity weighting (profound > meaningful > surface)
                depth_multiplier = {
                    EmotionalDepth.SURFACE: 1.0,
                    EmotionalDepth.MEANINGFUL: 1.5,
                    EmotionalDepth.PROFOUND: 2.0,
                }.get(felt.depth, 1.0)

                intensity_score = felt.emotional_intensity * depth_multiplier
                echo_score = recency_score * intensity_score

                echo = EchoItem(
                    experience_id=str(exp.id),
                    timestamp=exp.timestamp,
                    emotional_valence=felt.emotional_valence,
                    emotional_intensity=felt.emotional_intensity,
                    depth=felt.depth,
                    what_happened=moment.what_happened,
                    recency_score=recency_score,
                    intensity_score=intensity_score,
                    echo_score=echo_score,
                )
                echoes.append(echo)

        # Sort by echo_score descending
        echoes.sort(key=lambda e: e.echo_score, reverse=True)

        return echoes[: self.max_echoes]

    def build_context_summary(
        self,
        exclude_session_id: str | None = None,
        current_time: datetime | None = None,
    ) -> str:
        """
        Build a text summary of emotional context.

        Args:
            exclude_session_id: Optional session to exclude
            current_time: Reference time

        Returns:
            str: Human-readable emotional context summary
        """
        echoes = self.build_echo(exclude_session_id, current_time)

        if not echoes:
            return "No recent emotional context."

        parts = ["Recent emotional context:"]
        for echo in echoes:
            tone = (
                "positive"
                if echo.emotional_valence > 0.2
                else "negative"
                if echo.emotional_valence < -0.2
                else "neutral"
            )
            parts.append(
                f"- {echo.what_happened[:80]}... "
                f"({tone}, intensity: {echo.emotional_intensity:.1f})"
            )

        return "\n".join(parts)

    def get_dominant_emotional_tone(
        self,
        exclude_session_id: str | None = None,
        current_time: datetime | None = None,
    ) -> float:
        """
        Get the dominant emotional tone from recent experiences.

        Returns weighted average valence based on echo scores.

        Args:
            exclude_session_id: Optional session to exclude
            current_time: Reference time

        Returns:
            float: Dominant emotional tone (-1.0 to 1.0)
        """
        echoes = self.build_echo(exclude_session_id, current_time)

        if not echoes:
            return 0.0

        total_weight = sum(e.echo_score for e in echoes)
        if total_weight == 0:
            return 0.0

        weighted_valence = sum(e.emotional_valence * e.echo_score for e in echoes)
        return weighted_valence / total_weight
