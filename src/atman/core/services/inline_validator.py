"""InlineValidator — fire-and-forget post-write quality checks (HLE-32).

Per plan §13 "Inline после write (lightweight)" + §17 principle 12,
validation on the write path **must not block**. This service wraps the
guardian's ``inline_check_*`` methods with:

* ``try/except`` per-record so a single bad row never breaks the hot path
* automatic ``write_finding`` for every returned finding, again wrapped
* de-duplication is handled inside the guardian (``_has_unresolved``)
* logging only — no exceptions propagate to the caller

**Wiring status (Devin Review #599 ANALYSIS):**

* ``check_key_moment`` — wired into ``SessionManager.finish_session`` so
  freshly-persisted moments are validated immediately after
  ``create_key_moment``.
* ``check_fact`` and ``check_entity`` — public API surface, no call
  sites yet. The fact/entity write paths live on `FactualMemory` /
  `EntityRegistry` adapters which do not currently hold a reference to
  the validator. Hooking them is a separate task per backend (Postgres
  + InMemory) because each adapter owns its own write transaction
  boundary; that's where the inline call belongs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from atman.core.ports.memory_guardian import MemoryGuardian

if TYPE_CHECKING:
    from atman.core.models.entity import Entity
    from atman.core.models.experience import KeyMoment
    from atman.core.models.fact import FactRecord

_LOG = logging.getLogger(__name__)


# PLAYBOOK-START
# id: fire-and-forget-post-write-validation
# category: design-patterns
# title: Fire-and-Forget Post-Write Validation with Per-Record Error Isolation
# status: draft
# since: 2026-05-17
#
# Pattern: wrap per-record quality checks with individual try/except so a
# single bad row never breaks the writer's hot path. Each finding is
# persisted independently with its own error guard, and de-duplication is
# delegated to the checker. The result is a "best-effort" validation
# stream that never blocks or fails the producer.
#
# Why generalizable: any write-heavy pipeline (event sourcing, CDC, ETL)
# benefits from lightweight inline quality checks that degrade gracefully
# on partial failure — the alternative (batch-only scans) introduces
# detection latency proportional to the scan interval.
# PLAYBOOK-END
class InlineValidator:
    """Run lightweight post-write checks through a :class:`MemoryGuardian`."""

    def __init__(self, guardian: MemoryGuardian) -> None:
        self._guardian = guardian

    def check_fact(self, fact: FactRecord, *, agent_id: UUID) -> None:
        self._run("fact", agent_id, self._guardian.inline_check_fact, fact)

    def check_entity(self, entity: Entity, *, agent_id: UUID) -> None:
        self._run("entity", agent_id, self._guardian.inline_check_entity, entity)

    def check_key_moment(self, moment: KeyMoment, *, agent_id: UUID) -> None:
        self._run("key_moment", agent_id, self._guardian.inline_check_key_moment, moment)

    def _run(self, kind: str, agent_id: UUID, check, target) -> None:  # type: ignore[no-untyped-def]
        try:
            findings = check(target, agent_id=agent_id)
        except Exception:
            _LOG.warning("inline validation '%s' raised; skipping", kind, exc_info=True)
            return
        for finding in findings:
            try:
                self._guardian.write_finding(finding)
            except Exception:
                _LOG.warning("inline write_finding %s failed; dropping", kind, exc_info=True)
