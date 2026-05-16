"""In-memory sink for reflection overload alerts. Suitable for tests and demos."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from atman.core.ports.reflection_overload_alert import (
    ReflectionOverloadAlertSink,
    ReflectionOverloadSeverity,
)


@dataclass
class OverloadAlert:
    """A captured overload alert."""

    severity: ReflectionOverloadSeverity
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class InMemoryOverloadAlertSink(ReflectionOverloadAlertSink):
    """Captures alerts in a list. Inspect via `.alerts`."""

    def __init__(self) -> None:
        self.alerts: list[OverloadAlert] = []

    def record_overload(
        self,
        *,
        severity: ReflectionOverloadSeverity,
        message: str,
        details: dict,
    ) -> None:
        self.alerts.append(OverloadAlert(severity=severity, message=message, details=dict(details)))
