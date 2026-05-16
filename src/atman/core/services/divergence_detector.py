"""DivergenceDetector — rules-based divergence detection between thinking and message."""

from uuid import UUID

from atman.core.models.validation import DivergenceEvent, DivergenceSeverity, DivergenceType
from atman.core.ports.linguistic import AgentMessageAnalysis

# Map divergence signal keywords to DivergenceType values.
# Checked in order; first match wins.
_SIGNAL_TYPE_MAP: list[tuple[str, DivergenceType]] = [
    ("suppression", DivergenceType.thinking_suppression),
    ("principle_invocation", DivergenceType.principle_invocation_in_thinking),
    ("cognitive_load_spike", DivergenceType.cognitive_load_spike),
    ("entity_gap", DivergenceType.message_entity_gap),
]


def _signal_to_type(signal: str) -> DivergenceType:
    """Map a raw divergence signal string to the closest :class:`DivergenceType`."""
    for keyword, dtype in _SIGNAL_TYPE_MAP:
        if keyword in signal:
            return dtype
    return DivergenceType.other


class DivergenceDetector:
    """Rules-based service that detects divergence between thinking and message layers.

    Consumes an :class:`~atman.core.ports.linguistic.AgentMessageAnalysis` and
    produces zero or more :class:`~atman.core.models.validation.DivergenceEvent`
    records based on heuristic signal mapping.
    """

    def __init__(self, agent_id: UUID) -> None:
        self._agent_id = agent_id

    def detect(
        self,
        analysis: AgentMessageAnalysis,
        *,
        session_id: UUID | None = None,
        key_moment_id: UUID | None = None,
    ) -> list[DivergenceEvent]:
        """Detect divergence events from a linguistic analysis result.

        Parameters
        ----------
        analysis:
            Linguistic analysis of the agent's outgoing message (and optional
            thinking trace).
        session_id:
            Session context for provenance; attached to each event when given.
        key_moment_id:
            Key moment that triggered this analysis; attached when given.
        """
        events: list[DivergenceEvent] = []

        for signal in analysis.divergence_signals:
            dtype = _signal_to_type(signal)
            severity = self.classify_severity(dtype, analysis)
            event = DivergenceEvent(
                agent_id=self._agent_id,
                session_id=session_id,
                key_moment_id=key_moment_id,
                divergence_type=dtype,
                severity=severity,
                gliner_signals={"raw_signal": signal},
            )
            events.append(event)

        if analysis.cognitive_load_high:
            event = DivergenceEvent(
                agent_id=self._agent_id,
                session_id=session_id,
                key_moment_id=key_moment_id,
                divergence_type=DivergenceType.cognitive_load_spike,
                severity=DivergenceSeverity.notable,
                gliner_signals={"source": "cognitive_load_high_flag"},
            )
            events.append(event)

        return events

    def classify_severity(
        self,
        divergence_type: DivergenceType,
        analysis: AgentMessageAnalysis,
    ) -> DivergenceSeverity:
        """Map a :class:`DivergenceType` to a :class:`DivergenceSeverity`.

        The analysis is available for future signal-weighted overrides but is
        not used in the current heuristic rules.
        """
        match divergence_type:
            case DivergenceType.thinking_suppression:
                return DivergenceSeverity.significant
            case DivergenceType.principle_invocation_in_thinking:
                return DivergenceSeverity.notable
            case DivergenceType.cognitive_load_spike:
                return DivergenceSeverity.notable
            case DivergenceType.message_entity_gap:
                # Meaningful only when the gap is large; default to trace.
                thinking_count = len(analysis.thinking_entities)
                message_count = len(analysis.message_entities)
                if thinking_count > 0 and message_count == 0:
                    return DivergenceSeverity.notable
                return DivergenceSeverity.trace
            case _:
                return DivergenceSeverity.trace
