"""
Port for affective processing of session events.

The Core ``SessionManager`` schedules affect analysis after every
``record_event`` so the agent can pick up emotional anomalies, divergence
between visible text and inner ``thinking``, and other behavioural
markers. The concrete implementation lives outside the core layer (today
``atman.affect.detector.AffectDetector``) and is injected through this
port so Core code never imports the implementation directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from atman.core.models.experience import KeyMoment


@runtime_checkable
class AffectPort(Protocol):
    """Async hook called after each ``SessionManager.record_event``.

    Implementations analyse the message (and optional ``thinking`` trace),
    may append a ``KeyMoment`` to the active session via the configured
    sink, and may keep their own rolling baseline for anomaly detection.

    The return value is opaque to ``SessionManager``: it is logged and
    discarded. Implementations that have nothing to report should return
    ``None``.
    """

    async def process(
        self,
        text: str,
        *,
        thinking: str | None = None,
        session_id: UUID | None = None,
    ) -> Any:
        """Analyse one message; optionally side-effect a KeyMoment append."""
        ...


class AppendKeyMomentFn(Protocol):
    """Callback an ``AffectPort`` uses to push a KeyMoment into a session."""

    def __call__(self, session_id: UUID, moment: KeyMoment) -> None: ...
