"""Affect Detector — behavioural text metrics and key_moment write gateway."""

from typing import Any

from atman.affect.models import (
    AffectMetrics,
    AffectRecord,
    AgentMemoryReport,
    TriggerReason,
)

__all__ = [
    "AffectDetector",
    "AffectDetectorConfig",
    "AffectMetrics",
    "AffectRecord",
    "AgentMemoryReport",
    "TriggerReason",
]


def __getattr__(name: str) -> Any:
    if name == "AffectDetector":
        from atman.affect.detector import AffectDetector

        return AffectDetector
    if name == "AffectDetectorConfig":
        from atman.affect.detector import AffectDetectorConfig

        return AffectDetectorConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
