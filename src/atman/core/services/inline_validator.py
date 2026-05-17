"""InlineValidator — fire-and-forget post-write quality checks (HLE-32).

Per plan §13 "Inline после write (lightweight)" + §17 principle 12,
validation on the write path **must not block**. This service wraps the
guardian's ``inline_check_*`` methods with:

* ``try/except`` per-record so a single bad row never breaks the hot path
* automatic ``write_finding`` for every returned finding, again wrapped
* de-duplication is handled inside the guardian (``_has_unresolved``)
* logging only — no exceptions propagate to the caller
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
