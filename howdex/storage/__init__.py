"""Storage backends. Currently SQLite; future: DuckDB, sled, etc."""

from howdex.storage.sqlite_store import Store

__all__ = ["Store"]
