"""Exception hierarchy for Howdex."""

from __future__ import annotations


class HowdexError(Exception):
    """Base class for all Howdex errors."""


class StoreError(HowdexError):
    """Storage-layer failure (SQLite, I/O, corruption)."""


class HowdexNotFoundError(HowdexError):
    """A requested memory or procedure does not exist."""


class ConsolidationError(HowdexError):
    """The learn / consolidation step failed."""


class SyncError(HowdexError):
    """Cloud or peer sync failed."""


class EmbeddingError(HowdexError):
    """Embedding backend failure (model missing, API error, etc.)."""
