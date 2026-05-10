"""
SessionWorkingMemory - in-session cache for surfaced content.

Prevents repeated searches by caching already-surfaced facts and experiences.
Acts as a short-term working memory during active sessions.

The cache is backed by :class:`collections.OrderedDict`, which gives O(1)
LRU bookkeeping: ``move_to_end`` promotes accessed items in constant time
and ``popitem(last=False)`` evicts the oldest entry without a separate
parallel list of access order.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from atman.core.models import FactRecord, SessionExperience


@dataclass
class CachedItem:
    """An item cached in working memory."""

    item_id: UUID
    item_type: str  # "fact" or "experience"
    content: str
    surfaced_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    access_count: int = 1


class SessionWorkingMemory:
    """
    In-session working memory cache.

    Tracks facts and experiences that have already been surfaced during
    the current session to prevent redundant searches and provide context
    about what the agent is already aware of.
    """

    def __init__(self, max_size: int = 100) -> None:
        """
        Initialize working memory.

        Args:
            max_size: Maximum number of items to cache (LRU eviction)
        """
        self.max_size = max_size
        # ``OrderedDict`` lets us treat insertion order as access order:
        # ``move_to_end`` on read marks an item as MRU and
        # ``popitem(last=False)`` evicts the LRU entry. Both ops are O(1),
        # whereas a parallel ``list[UUID]`` required O(n) ``remove`` /
        # ``pop(0)`` calls.
        self._cache: OrderedDict[UUID, CachedItem] = OrderedDict()

    def has(self, item_id: UUID) -> bool:
        """Check if an item is already in working memory."""
        return item_id in self._cache

    def get(self, item_id: UUID) -> CachedItem | None:
        """Get item from working memory if present."""
        item = self._cache.get(item_id)
        if item is not None:
            item.access_count += 1
            # Mark as most recently used (move to end of OrderedDict).
            self._cache.move_to_end(item_id)
        return item

    def add_fact(self, fact: FactRecord) -> None:
        """Add a fact to working memory."""
        if fact.id in self._cache:
            return

        self._evict_if_needed()

        cached = CachedItem(
            item_id=fact.id,
            item_type="fact",
            content=fact.content[:200],  # Truncate for memory efficiency
        )
        self._cache[fact.id] = cached

    def add_experience(self, experience: SessionExperience) -> None:
        """Add an experience to working memory."""
        if experience.id in self._cache:
            return

        self._evict_if_needed()

        # Summarize key moments
        summary = " | ".join(km.what_happened[:100] for km in experience.key_moments[:2])

        cached = CachedItem(
            item_id=experience.id,
            item_type="experience",
            content=summary,
        )
        self._cache[experience.id] = cached

    def add_facts_batch(self, facts: list[FactRecord]) -> list[FactRecord]:
        """
        Add multiple facts, returning only those not already cached.

        This is useful for filtering search results to only new items.
        """
        new_facts = []
        for fact in facts:
            if not self.has(fact.id):
                self.add_fact(fact)
                new_facts.append(fact)
        return new_facts

    def list_cached(self, item_type: str | None = None) -> list[CachedItem]:
        """
        List cached items, optionally filtered by type.

        Returns items in LRU order (least recently accessed first).
        """
        return [
            item
            for item in self._cache.values()
            if item_type is None or item.item_type == item_type
        ]

    def clear(self) -> None:
        """Clear all items from working memory."""
        self._cache.clear()

    def size(self) -> int:
        """Return number of items in cache."""
        return len(self._cache)

    def _evict_if_needed(self) -> None:
        """Evict oldest item if cache is at capacity (O(1))."""
        if len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)
