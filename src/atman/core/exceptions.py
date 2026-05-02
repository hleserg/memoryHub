"""Domain-level exceptions for core services."""


class NarrativePersistenceConflictError(Exception):
    """
    Raised when a narrative write loses optimistic concurrency.

    The caller read a document snapshot, but another writer committed first
    (different ``updated_at`` on the persisted narrative).
    """
