"""
Port for `ReflectionOverloadMonitor` alerts.

When the monitor detects abnormal reflection frequency it emits alerts here.
This intentionally does **not** try to "fix" anything (e.g. lower the cadence
itself) — overload is treated as a visible signal that thresholds need
calibration. Implementations forward to whatever observability channel the
deployment uses.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum


class ReflectionOverloadSeverity(StrEnum):
    """Severity of an overload alert."""

    WARNING = "warning"
    CRITICAL = "critical"


class ReflectionOverloadAlertSink(ABC):
    """Receives alerts when reflection cadence exceeds calibrated thresholds."""

    @abstractmethod
    def record_overload(
        self,
        *,
        severity: ReflectionOverloadSeverity,
        message: str,
        details: dict,
    ) -> None:
        """Record an overload signal. Implementations must not raise."""
        ...
