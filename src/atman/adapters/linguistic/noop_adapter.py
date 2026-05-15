"""NoOp LinguisticAnalyzer — returns empty analysis for all inputs."""

from typing_extensions import override

from atman.core.ports.linguistic import (
    AgentMessageAnalysis,
    KeyMomentAnalysis,
    LinguisticAnalyzer,
    UserMessageAnalysis,
)


class NoOpLinguisticAnalyzer(LinguisticAnalyzer):
    """LinguisticAnalyzer that returns empty results for every call.

    Used when LINGUISTIC_ENABLED=False or in environments where NLP
    dependencies are unavailable and silent pass-through behaviour is desired.
    """

    @override
    def analyze_user_message(self, text: str) -> UserMessageAnalysis:
        """Return an empty analysis preserving the original text."""
        return UserMessageAnalysis(text=text, entities=[], anchors=[])

    @override
    def analyze_agent_message(
        self,
        message: str,
        *,
        thinking: str | None = None,
    ) -> AgentMessageAnalysis:
        """Return an empty analysis with all default values."""
        return AgentMessageAnalysis()

    @override
    def analyze_key_moment(
        self,
        what_happened: str,
        why_it_matters: str,
    ) -> KeyMomentAnalysis:
        """Return an empty key-moment analysis with all default values."""
        return KeyMomentAnalysis()
