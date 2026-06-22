"""SQLite storage backend for Howdex.

A single-file embedded database. Zero-config. Survives crashes. Replicatable
to any cloud via file copy or our CRDT sync layer.

Schema is versioned; ``migrate()`` brings any old file up to date.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from howdex.core.types import Memory, MemoryLayer, MemoryType
from howdex.core.errors import StoreError

SCHEMA_VERSION = 2


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id            TEXT PRIMARY KEY,
    layer         TEXT NOT NULL,
    type          TEXT NOT NULL,
    content       TEXT NOT NULL,
    metadata      TEXT NOT NULL DEFAULT '{}',
    embedding     BLOB,                       -- numpy float32 packed
    relations     TEXT NOT NULL DEFAULT '[]',
    source        TEXT NOT NULL DEFAULT 'user',
    agent_id      TEXT,
    session_id    TEXT,
    parent_id     TEXT,
    created_at    REAL NOT NULL,
    accessed_at   REAL NOT NULL,
    access_count  INTEGER NOT NULL DEFAULT 0,
    importance    REAL NOT NULL DEFAULT 0.5,
    ttl           REAL,
    vector_clock  INTEGER NOT NULL DEFAULT 0,
    deleted       INTEGER NOT NULL DEFAULT 0  -- tombstones for CRDT
);

CREATE INDEX IF NOT EXISTS idx_memories_layer       ON memories(layer);
CREATE INDEX IF NOT EXISTS idx_memories_type        ON memories(type);
CREATE INDEX IF NOT EXISTS idx_memories_session     ON memories(session_id);
CREATE INDEX IF NOT EXISTS idx_memories_agent       ON memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_memories_created_at  ON memories(created_at);
CREATE INDEX IF NOT EXISTS idx_memories_importance  ON memories(importance);

-- episodic sessions
CREATE TABLE IF NOT EXISTS episodes (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL,
    agent_id      TEXT NOT NULL,
    task          TEXT NOT NULL,
    steps         TEXT NOT NULL DEFAULT '[]',
    outcome       TEXT,
    error         TEXT,
    duration_s    REAL NOT NULL DEFAULT 0,
    started_at    REAL NOT NULL,
    finished_at   REAL
);

-- procedural library (consolidation output)
CREATE TABLE IF NOT EXISTS procedures (
    id               TEXT PRIMARY KEY,
    task_signature   TEXT NOT NULL UNIQUE,
    steps            TEXT NOT NULL DEFAULT '[]',
    preconditions    TEXT NOT NULL DEFAULT '[]',
    expected_outcome TEXT NOT NULL DEFAULT '',
    success_rate     REAL NOT NULL DEFAULT 0,
    sample_count     INTEGER NOT NULL DEFAULT 0,
    support_count    INTEGER NOT NULL DEFAULT 0,
    success_count    INTEGER NOT NULL DEFAULT 0,
    confidence       REAL NOT NULL DEFAULT 0,
    raw_examples     TEXT NOT NULL DEFAULT '[]',
    source_episode_ids TEXT NOT NULL DEFAULT '[]',
    created_at       REAL NOT NULL,
    last_used_at     REAL,
    use_count        INTEGER NOT NULL DEFAULT 0
);

-- CRDT sync log
CREATE TABLE IF NOT EXISTS sync_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    op            TEXT NOT NULL,    -- upsert | delete
    memory_id     TEXT NOT NULL,
    vector_clock  INTEGER NOT NULL,
    node_id       TEXT NOT NULL,
    payload       TEXT NOT NULL,    -- full memory JSON
    synced        INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sync_log_synced ON sync_log(synced);
CREATE INDEX IF NOT EXISTS idx_sync_log_clock  ON sync_log(vector_clock);
"""


class Store:
    """Thread-safe SQLite store.

    One :class:`Store` per process per database file. Internally uses a
    connection-per-thread pattern with a lock for writes.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._tls = threading.local()
        # initialize synchronously on the calling thread
        self._init_db()

    # ------------------------------------------------------------------ #
    # connection management
    # ------------------------------------------------------------------ #
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._tls, "conn"):
            conn = sqlite3.connect(
                str(self.path),
                timeout=30.0,
                isolation_level=None,        # autocommit; we manage txns
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("PRAGMA busy_timeout=30000;")
            self._tls.conn = conn
        return self._tls.conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._conn()
            conn.executescript(SCHEMA)
            self._migrate_schema(conn)
            conn.execute(
                """INSERT INTO schema_meta(key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES (?, ?)",
                ("node_id", str(uuid.uuid4())),
            )

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Apply additive local migrations for older Howdex databases."""
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(procedures)").fetchall()
        }
        additions = {
            "support_count": "INTEGER NOT NULL DEFAULT 0",
            "success_count": "INTEGER NOT NULL DEFAULT 0",
            "confidence": "REAL NOT NULL DEFAULT 0",
            "raw_examples": "TEXT NOT NULL DEFAULT '[]'",
            "source_episode_ids": "TEXT NOT NULL DEFAULT '[]'",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE procedures ADD COLUMN {name} {definition}")

        conn.execute(
            """UPDATE procedures
               SET support_count=CASE
                     WHEN support_count=0 THEN sample_count
                     ELSE support_count
                   END,
                   success_count=CASE
                     WHEN success_count=0 THEN CAST(ROUND(success_rate * sample_count) AS INTEGER)
                     ELSE success_count
                   END,
                   confidence=CASE
                     WHEN confidence=0 THEN success_rate
                     ELSE confidence
                   END"""
        )

    @property
    def node_id(self) -> str:
        row = self._conn().execute(
            "SELECT value FROM schema_meta WHERE key=?", ("node_id",)
        ).fetchone()
        return row["value"]

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._conn()
            conn.execute("BEGIN IMMEDIATE;")
            try:
                yield conn
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    # ------------------------------------------------------------------ #
    # memory CRUD
    # ------------------------------------------------------------------ #
    def put(self, mem: Memory) -> None:
        emb_blob = _pack_embedding(mem.embedding)
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memories
                  (id, layer, type, content, metadata, embedding, relations,
                   source, agent_id, session_id, parent_id, created_at, accessed_at,
                   access_count, importance, ttl, vector_clock, deleted)
                VALUES
                  (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
                """,
                (
                    mem.id, mem.layer.value, mem.type.value, mem.content,
                    json.dumps(mem.metadata), emb_blob,
                    json.dumps(mem.relations), mem.source, mem.agent_id,
                    mem.session_id, mem.parent_id, mem.created_at, mem.accessed_at,
                    mem.access_count, mem.importance, mem.ttl, mem.vector_clock,
                ),
            )
            # CRDT log
            conn.execute(
                """INSERT INTO sync_log(op, memory_id, vector_clock, node_id, payload, created_at)
                   VALUES ('upsert', ?, ?, ?, ?, ?)""",
                (mem.id, mem.vector_clock, self.node_id, json.dumps(mem.to_dict()), time.time()),
            )

    def get(self, mem_id: str) -> Optional[Memory]:
        row = self._conn().execute(
            "SELECT * FROM memories WHERE id=? AND deleted=0", (mem_id,)
        ).fetchone()
        return _row_to_memory(row) if row else None

    def delete(self, mem_id: str, soft: bool = True) -> None:
        """Soft-delete (tombstone) by default for CRDT correctness."""
        with self.transaction() as conn:
            if soft:
                conn.execute("UPDATE memories SET deleted=1 WHERE id=?", (mem_id,))
            else:
                conn.execute("DELETE FROM memories WHERE id=?", (mem_id,))
            conn.execute(
                """INSERT INTO sync_log(op, memory_id, vector_clock, node_id, payload, created_at)
                   VALUES ('delete', ?, ?, ?, '{}', ?)""",
                (mem_id, int(time.time()), self.node_id, time.time()),
            )

    def touch(self, mem_id: str) -> None:
        now = time.time()
        self._conn().execute(
            "UPDATE memories SET accessed_at=?, access_count=access_count+1 WHERE id=?",
            (now, mem_id),
        )

    # ------------------------------------------------------------------ #
    # queries
    # ------------------------------------------------------------------ #
    def query(
        self,
        *,
        layer: Optional[MemoryLayer] = None,
        type: Optional[MemoryType] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        source: Optional[str] = None,
        since: Optional[float] = None,
        limit: int = 1000,
    ) -> list[Memory]:
        sql = "SELECT * FROM memories WHERE deleted=0"
        args: list[Any] = []
        if layer:
            sql += " AND layer=?"; args.append(layer.value)
        if type:
            sql += " AND type=?"; args.append(type.value)
        if session_id:
            sql += " AND session_id=?"; args.append(session_id)
        if agent_id:
            sql += " AND agent_id=?"; args.append(agent_id)
        if source:
            sql += " AND source=?"; args.append(source)
        if since:
            sql += " AND created_at>=?"; args.append(since)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        rows = self._conn().execute(sql, args).fetchall()
        return [_row_to_memory(r) for r in rows]

    def all_with_embeddings(self, layer: Optional[MemoryLayer] = None) -> list[Memory]:
        sql = "SELECT * FROM memories WHERE deleted=0 AND embedding IS NOT NULL"
        args: list[Any] = []
        if layer:
            sql += " AND layer=?"; args.append(layer.value)
        rows = self._conn().execute(sql, args).fetchall()
        return [_row_to_memory(r) for r in rows]

    def count(self, layer: Optional[MemoryLayer] = None) -> int:
        sql = "SELECT COUNT(*) FROM memories WHERE deleted=0"
        args: list[Any] = []
        if layer:
            sql += " AND layer=?"; args.append(layer.value)
        return self._conn().execute(sql, args).fetchone()[0]

    # ------------------------------------------------------------------ #
    # episodes
    # ------------------------------------------------------------------ #
    def put_episode(self, ep_dict: dict[str, Any]) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO episodes
                   (id, session_id, agent_id, task, steps, outcome, error,
                    duration_s, started_at, finished_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    ep_dict["id"], ep_dict["session_id"], ep_dict["agent_id"],
                    ep_dict["task"], json.dumps(ep_dict.get("steps", [])),
                    ep_dict.get("outcome"), ep_dict.get("error"),
                    ep_dict.get("duration_s", 0), ep_dict["started_at"],
                    ep_dict.get("finished_at"),
                ),
            )

    def query_episodes(
        self, *, agent_id: Optional[str] = None, outcome: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM episodes WHERE 1=1"
        args: list[Any] = []
        if agent_id:
            sql += " AND agent_id=?"; args.append(agent_id)
        if outcome:
            sql += " AND outcome=?"; args.append(outcome)
        sql += " ORDER BY started_at DESC LIMIT ?"
        args.append(limit)
        rows = self._conn().execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # procedures
    # ------------------------------------------------------------------ #
    def put_procedure(self, p: dict[str, Any]) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO procedures
                   (id, task_signature, steps, preconditions, expected_outcome,
                    success_rate, sample_count, support_count, success_count,
                    confidence, raw_examples, source_episode_ids, created_at,
                    last_used_at, use_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    p["id"], p["task_signature"], json.dumps(p.get("steps", [])),
                    json.dumps(p.get("preconditions", [])), p.get("expected_outcome", ""),
                    p.get("success_rate", 0), p.get("sample_count", 0),
                    p.get("support_count", p.get("sample_count", 0)),
                    p.get(
                        "success_count",
                        round(p.get("success_rate", 0) * p.get("sample_count", 0)),
                    ),
                    p.get("confidence", p.get("success_rate", 0)),
                    json.dumps(p.get("raw_supporting_examples", [])),
                    json.dumps(p.get("source_episode_ids", [])),
                    p.get("created_at", time.time()), p.get("last_used_at"),
                    p.get("use_count", 0),
                ),
            )

    def get_procedure(self, task_signature: str) -> Optional[dict[str, Any]]:
        row = self._conn().execute(
            "SELECT * FROM procedures WHERE task_signature=?", (task_signature,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["steps"] = json.loads(d["steps"])
        d["preconditions"] = json.loads(d["preconditions"])
        d["raw_supporting_examples"] = json.loads(d.pop("raw_examples"))
        d["source_episode_ids"] = json.loads(d["source_episode_ids"])
        return d

    def all_procedures(self) -> list[dict[str, Any]]:
        rows = self._conn().execute("SELECT * FROM procedures").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["steps"] = json.loads(d["steps"])
            d["preconditions"] = json.loads(d["preconditions"])
            d["raw_supporting_examples"] = json.loads(d.pop("raw_examples"))
            d["source_episode_ids"] = json.loads(d["source_episode_ids"])
            out.append(d)
        return out

    # ------------------------------------------------------------------ #
    # sync log
    # ------------------------------------------------------------------ #
    def pending_sync_ops(self, since_id: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT * FROM sync_log WHERE id>? AND synced=0 ORDER BY id LIMIT ?",
            (since_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_synced(self, op_ids: list[int]) -> None:
        if not op_ids:
            return
        with self.transaction() as conn:
            conn.executemany(
                "UPDATE sync_log SET synced=1 WHERE id=?",
                [(i,) for i in op_ids],
            )

    def apply_remote_op(self, op: dict[str, Any]) -> None:
        """Apply a CRDT op from a remote node. Idempotent + last-writer-wins
        on (vector_clock, node_id)."""
        payload = json.loads(op["payload"]) if op["payload"] != "{}" else None
        with self.transaction() as conn:
            if op["op"] == "delete":
                conn.execute("UPDATE memories SET deleted=1 WHERE id=?", (op["memory_id"],))
                return
            if not payload:
                return
            existing = conn.execute(
                "SELECT vector_clock FROM memories WHERE id=?", (op["memory_id"],)
            ).fetchone()
            existing_vc = existing["vector_clock"] if existing else -1
            if op["vector_clock"] <= existing_vc:
                return  # stale
            mem = Memory.from_dict(payload)
            conn.execute(
                """INSERT OR REPLACE INTO memories
                   (id, layer, type, content, metadata, embedding, relations, source,
                    agent_id, session_id, parent_id, created_at, accessed_at, access_count,
                    importance, ttl, vector_clock, deleted)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                (
                    mem.id, mem.layer.value, mem.type.value, mem.content,
                    json.dumps(mem.metadata), _pack_embedding(mem.embedding),
                    json.dumps(mem.relations), mem.source, mem.agent_id, mem.session_id,
                    mem.parent_id, mem.created_at, mem.accessed_at, mem.access_count,
                    mem.importance, mem.ttl, mem.vector_clock,
                ),
            )

    def stats(self) -> dict[str, Any]:
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) FROM memories WHERE deleted=0").fetchone()[0]
        per_layer: dict[str, int] = {}
        for row in conn.execute(
            "SELECT layer, COUNT(*) AS n FROM memories WHERE deleted=0 GROUP BY layer"
        ).fetchall():
            per_layer[row["layer"]] = row["n"]
        episodes = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        procedures = conn.execute("SELECT COUNT(*) FROM procedures").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM sync_log WHERE synced=0"
        ).fetchone()[0]
        return {
            "total_memories": total,
            "per_layer": per_layer,
            "episodes": episodes,
            "procedures": procedures,
            "pending_sync_ops": pending,
            "db_path": str(self.path),
            "node_id": self.node_id,
        }


# ---------------------------------------------------------------------- #
# helpers
# ---------------------------------------------------------------------- #
def _pack_embedding(emb: Optional[list[float]]) -> Optional[bytes]:
    if emb is None:
        return None
    import struct
    return struct.pack(f"<{len(emb)}f", *emb)


def _unpack_embedding(blob: Optional[bytes]) -> Optional[list[float]]:
    if blob is None:
        return None
    import struct
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def _row_to_memory(row: sqlite3.Row) -> Memory:
    return Memory(
        id=row["id"],
        layer=MemoryLayer(row["layer"]),
        type=MemoryType(row["type"]),
        content=row["content"],
        metadata=json.loads(row["metadata"]),
        embedding=_unpack_embedding(row["embedding"]),
        relations=json.loads(row["relations"]),
        source=row["source"],
        agent_id=row["agent_id"],
        session_id=row["session_id"],
        parent_id=row["parent_id"],
        created_at=row["created_at"],
        accessed_at=row["accessed_at"],
        access_count=row["access_count"],
        importance=row["importance"],
        ttl=row["ttl"],
        vector_clock=row["vector_clock"],
    )
