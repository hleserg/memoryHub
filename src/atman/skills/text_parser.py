"""InvocationTextParser — fallback skill detection for weak-tool-use models.

The skill loop's first-class entry point is the ``atman_skills_invoke`` tool.
Models that do not call tools reliably (small local models, some Ollama
deployments) will instead mention the skill by name in their free-text
response. This parser scans that text and creates ``executed_unknown``
invocation rows so micro reflection still sees the skill-loop activity and
``process_session_skills`` can update stats.

Design notes:

* ``parse`` performs no DB writes. It does read ``SKILL.md`` from disk to
  look up trigger keywords — this is amortised by a per-parser mtime-keyed
  manifest cache so steady-state calls touch the filesystem only when an
  on-disk manifest actually changes.
* ``parse_and_record`` is the side-effecting wrapper. It uses
  :meth:`SkillStore.create_invocation` and :meth:`SkillStore.write_agent_marker`
  with ``agent_marker='unclear'`` because we are not sure the model actually
  *used* the skill, only that it referenced it.
* Scoring is intentionally simple and explainable (no embedding): exact
  kebab-case name match outranks keyword overlap. Embedding-based matching
  is the retriever's job — this parser is a fallback for explicit mentions.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from uuid import UUID

from atman.skills.models import Skill, SkillStatus
from atman.skills.retriever import _keywords_from_skill
from atman.skills.store import SkillStore

_log = logging.getLogger(__name__)

DEFAULT_MIN_CONFIDENCE = 0.7

# Cap on the count of inferred invocations created per call so a model that
# spams skill names in a wall of text cannot flood the invocations table.
_MAX_INFERRED_PER_CALL = 5

# Score values are public so callers / tests can compare against named
# constants instead of magic floats.
SCORE_EXACT_NAME = 1.0
SCORE_NAME_VARIANT = 0.9  # e.g. underscore form of a kebab-case skill
SCORE_KEYWORD_MULTI = 0.9  # 2+ distinct keywords matched
SCORE_KEYWORD_SINGLE = 0.75  # 1 keyword matched


@dataclass(frozen=True)
class InferredInvocation:
    """One implicit skill mention extracted from agent response text.

    ``confidence`` is in ``[0, 1]``; ``matched_text`` is the substring of
    ``response_text`` that triggered the match (used both as evidence and
    for ``input_context_summary``).
    """

    skill_id: UUID
    skill_name: str
    confidence: float
    matched_text: str
    reason: str


class InvocationTextParser:
    """Detect implicit skill invocations in agent response text."""

    def __init__(
        self,
        store: SkillStore,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        max_per_call: int = _MAX_INFERRED_PER_CALL,
    ) -> None:
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError(f"min_confidence must be in [0, 1], got {min_confidence!r}")
        self._store = store
        self._min_confidence = min_confidence
        self._max_per_call = max_per_call
        # Manifest cache keyed by skill_id → (manifest_mtime_ns, keywords).
        # Each parse() call hits this cache instead of re-reading SKILL.md +
        # re-parsing YAML for every candidate. Entries invalidate when the
        # on-disk manifest's mtime changes (e.g. after a revise / install
        # rewrites the file).
        self._keyword_cache: dict[UUID, tuple[int, list[str]]] = {}

    # ── pure parsing ──────────────────────────────────────────────────────

    def parse(
        self,
        response_text: str,
        agent_id: UUID,
        session_id: UUID,
    ) -> list[InferredInvocation]:
        """Return inferred invocations above the configured threshold.

        Results are deduplicated by ``skill_id`` (one entry per skill,
        keeping the highest-confidence match) and sorted by confidence
        descending. The empty-input case returns ``[]`` without touching
        the store.
        """
        if not response_text or not response_text.strip():
            return []

        text_lower = response_text.lower()
        candidates = self._candidate_skills(agent_id)
        if not candidates:
            return []

        best_per_skill: dict[UUID, InferredInvocation] = {}
        for skill in candidates:
            inferred = self._score_skill(skill, response_text, text_lower)
            if inferred is None:
                continue
            if inferred.confidence < self._min_confidence:
                continue
            current = best_per_skill.get(skill.id)
            if current is None or inferred.confidence > current.confidence:
                best_per_skill[skill.id] = inferred

        results = sorted(best_per_skill.values(), key=lambda i: i.confidence, reverse=True)
        return results[: self._max_per_call]

    # ── side-effecting wrapper ────────────────────────────────────────────

    def parse_and_record(
        self,
        response_text: str,
        agent_id: UUID,
        session_id: UUID,
    ) -> list[UUID]:
        """Parse ``response_text`` and persist each inferred invocation.

        Returns the list of new invocation ids (empty when nothing was
        detected). Each invocation is created with
        ``input_context_summary='inferred_from_text: …'`` and an explicit
        ``agent_marker='unclear'`` so the final-status hierarchy in
        ``SkillManager._determine_final_status`` does not incorrectly
        promote it to ``helped``.

        Store errors on a single invocation are logged and skipped — one
        bad row must not abort the rest of the batch.
        """
        inferred = self.parse(response_text, agent_id, session_id)
        invocation_ids: list[UUID] = []
        for item in inferred:
            try:
                invocation_id = self._store.create_invocation(
                    skill_id=item.skill_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    input_context_summary=(f"inferred_from_text: {item.matched_text[:120]}"),
                )
                self._store.write_agent_marker(
                    invocation_id,
                    "unclear",
                    (
                        "auto-inferred from response text "
                        f"(confidence={item.confidence:.2f}): {item.reason}"
                    ),
                )
                invocation_ids.append(invocation_id)
            except Exception as exc:
                _log.warning(
                    "InvocationTextParser: failed to record inferred invocation for skill '%s': %s",
                    item.skill_name,
                    exc,
                )
                continue
        return invocation_ids

    # ── internals ─────────────────────────────────────────────────────────

    def _candidate_skills(self, agent_id: UUID) -> list[Skill]:
        """Active skills the agent can plausibly mention (pinned + on-demand)."""
        # ``list_by_status`` is the most portable union: every concrete
        # SkillStore supports it (InMemorySkillStore + PostgresSkillStore).
        return self._store.list_by_status(agent_id, SkillStatus.active)

    def _keywords_for(self, skill: Skill) -> list[str]:
        """Return trigger keywords for ``skill`` using the mtime-keyed cache.

        Falls back to reading SKILL.md directly when the file does not exist
        (e.g. in-memory tests that never wrote a manifest) — the result is
        cached with ``mtime = 0`` and any subsequent file appearance will
        invalidate the entry through the mtime mismatch.
        """
        try:
            mtime_ns = skill.manifest_path.stat().st_mtime_ns
        except OSError:
            mtime_ns = 0

        cached = self._keyword_cache.get(skill.id)
        if cached is not None and cached[0] == mtime_ns:
            return cached[1]

        raw = _keywords_from_skill(skill) if mtime_ns else []
        keywords = [k for k in raw if k and k.strip()]
        self._keyword_cache[skill.id] = (mtime_ns, keywords)
        return keywords

    def _score_skill(
        self,
        skill: Skill,
        response_text: str,
        text_lower: str,
    ) -> InferredInvocation | None:
        # 1) exact kebab-case name match — strongest signal
        name = skill.name
        name_lower = name.lower()
        if _word_boundary_search(text_lower, name_lower):
            snippet = _excerpt_around(response_text, name_lower)
            return InferredInvocation(
                skill_id=skill.id,
                skill_name=skill.name,
                confidence=SCORE_EXACT_NAME,
                matched_text=snippet,
                reason=f"exact skill name '{name}' appeared in response",
            )

        # 2) kebab → underscore / space variant
        for variant in {name_lower.replace("-", "_"), name_lower.replace("-", " ")}:
            if variant == name_lower:
                continue
            if _word_boundary_search(text_lower, variant):
                snippet = _excerpt_around(response_text, variant)
                return InferredInvocation(
                    skill_id=skill.id,
                    skill_name=skill.name,
                    confidence=SCORE_NAME_VARIANT,
                    matched_text=snippet,
                    reason=f"name variant '{variant}' appeared in response",
                )

        # 3) trigger-keyword overlap (manifest-driven)
        keywords = self._keywords_for(skill)
        matched_keywords = [k for k in keywords if k.lower() in text_lower]
        if not matched_keywords:
            return None

        first = matched_keywords[0]
        snippet = _excerpt_around(response_text, first.lower())
        if len(matched_keywords) >= 2:
            return InferredInvocation(
                skill_id=skill.id,
                skill_name=skill.name,
                confidence=SCORE_KEYWORD_MULTI,
                matched_text=snippet,
                reason=(
                    f"{len(matched_keywords)} trigger keywords matched: "
                    + ", ".join(repr(k) for k in matched_keywords[:3])
                ),
            )
        return InferredInvocation(
            skill_id=skill.id,
            skill_name=skill.name,
            confidence=SCORE_KEYWORD_SINGLE,
            matched_text=snippet,
            reason=f"trigger keyword {first!r} matched",
        )


# ── helpers ───────────────────────────────────────────────────────────────


def _word_boundary_search(haystack: str, needle: str) -> bool:
    """True when ``needle`` appears as a standalone token in ``haystack``.

    Used for skill-name matching where a substring match would over-fire
    (e.g. ``"map"`` matching ``"mapping"``). Falls back to plain ``in`` when
    the needle contains characters that don't fit ``\b`` boundaries.
    """
    if not needle:
        return False
    try:
        pattern = rf"(?<![\w-]){re.escape(needle)}(?![\w-])"
        return re.search(pattern, haystack) is not None
    except re.error:
        return needle in haystack


def _excerpt_around(text: str, needle_lower: str, window: int = 60) -> str:
    """Return a ``±window``-char snippet of ``text`` around ``needle_lower``."""
    idx = text.lower().find(needle_lower)
    if idx < 0:
        return text[:window]
    start = max(0, idx - window)
    end = min(len(text), idx + len(needle_lower) + window)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet
