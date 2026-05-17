"""Logging-based sink for :class:`ReflectionOverloadAlertSink`.

In production deployments the agent's logging pipeline (structured JSON,
forwarded to a log aggregator) is the lightest-weight observability
channel. This sink routes overload alerts through the standard library
``logging`` module — WARNING level for ``WARNING`` alerts, CRITICAL level
for ``CRITICAL`` alerts — so they show up wherever the deploy already
ships agent logs.

The implementation never raises: per the :class:`ReflectionOverloadAlertSink`
contract, sink errors must not break the monitor.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from atman.core.ports.reflection_overload_alert import (
    ReflectionOverloadAlertSink,
    ReflectionOverloadSeverity,
)

_LOG = logging.getLogger("atman.reflection.overload")


class LoggingOverloadAlertSink(ReflectionOverloadAlertSink):
    """Routes overload alerts through ``logging`` at WARNING / CRITICAL level.

    The structured payload (``severity`` + ``details``) is passed as the
    ``extra`` dict so a JSON formatter can serialize it without losing the
    rule name and per-day counts that the monitor produces.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._log = logger or _LOG

    def record_overload(
        self,
        *,
        severity: ReflectionOverloadSeverity,
        message: str,
        details: dict,
    ) -> None:
        level = (
            logging.CRITICAL if severity is ReflectionOverloadSeverity.CRITICAL else logging.WARNING
        )
        extra: dict[str, Any] = {
            "severity": severity.value,
            "details": dict(details),
        }
        # Logging is best-effort — never let formatter / handler crashes
        # bubble back into the monitor's control flow.
        with contextlib.suppress(Exception):
            self._log.log(level, "reflection overload: %s", message, extra=extra)
