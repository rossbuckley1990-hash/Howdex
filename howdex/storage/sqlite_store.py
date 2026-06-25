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
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from howdex.core.errors import StoreError
from howdex.core.feedback import (
    procedure_feedback_confidence,
    procedure_success_rate,
)
from howdex.core.types import Memory, MemoryLayer, MemoryType

SCHEMA_VERSION = 6


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
    finished_at   REAL,
    step_count    INTEGER NOT NULL DEFAULT 0,
    source        TEXT NOT NULL DEFAULT 'agent',
    provenance    TEXT NOT NULL DEFAULT '{}',
    parent_session_id TEXT,
    is_segment    INTEGER NOT NULL DEFAULT 0
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
    failure_count    INTEGER NOT NULL DEFAULT 0,
    confidence       REAL NOT NULL DEFAULT 0,
    base_confidence  REAL NOT NULL DEFAULT 0,
    feedback_success_count INTEGER NOT NULL DEFAULT 0,
    feedback_failure_count INTEGER NOT NULL DEFAULT 0,
    suggestion_count INTEGER NOT NULL DEFAULT 0,
    unverified_use_count INTEGER NOT NULL DEFAULT 0,
    raw_examples     TEXT NOT NULL DEFAULT '[]',
    parameter_bindings TEXT NOT NULL DEFAULT '[]',
    source_episode_ids TEXT NOT NULL DEFAULT '[]',
    created_at       REAL NOT NULL,
    last_used_at     REAL,
    use_count        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS procedure_feedback (
    procedure_id     TEXT NOT NULL,
    reference_id     TEXT NOT NULL,
    state            TEXT NOT NULL,
    outcome          TEXT,
    suggested_at     REAL,
    used_at          REAL,
    observed_at      REAL,
    PRIMARY KEY (procedure_id, reference_id)
);

CREATE INDEX IF NOT EXISTS idx_procedure_feedback_procedure
    ON procedure_feedback(procedure_id);

CREATE TABLE IF NOT EXISTS procedure_receipts (
    procedure_id     TEXT NOT NULL,
    receipt_id       TEXT NOT NULL,
    payload          TEXT NOT NULL,
    created_at       REAL NOT NULL,
    PRIMARY KEY (procedure_id, receipt_id)
);

CREATE INDEX IF NOT EXISTS idx_procedure_receipts_procedure
    ON procedure_receipts(procedure_id);

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

    Call :meth:`close` when done to release the SQLite connection and
    WAL file handles. :class:`Howdex` calls this automatically from its
    own :meth:`Howdex.close`.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._tls = threading.local()
        # Track all connections opened across all threads so close() can
        # release them. Without this, long-running servers leak one
        # connection per worker thread until GC (non-deterministic).
        self._all_connections: list[sqlite3.Connection] = []
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
            with self._lock:
                self._all_connections.append(conn)
        return self._tls.conn

    def close(self) -> None:
        """Close all SQLite connections opened by this Store.

        Safe to call multiple times. After close(), the Store should not
        be used (opening a new connection will re-initialize the DB).
        """
        with self._lock:
            for conn in self._all_connections:
                try:
                    conn.close()
                except Exception:
                    pass
            self._all_connections.clear()
            # Clear thread-local so a subsequent _conn() call re-opens
            if hasattr(self._tls, "conn"):
                try:
                    del self._tls.conn
                except AttributeError:
                    pass

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

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
            "failure_count": "INTEGER NOT NULL DEFAULT 0",
            "confidence": "REAL NOT NULL DEFAULT 0",
            "base_confidence": "REAL NOT NULL DEFAULT 0",
            "feedback_success_count": "INTEGER NOT NULL DEFAULT 0",
            "feedback_failure_count": "INTEGER NOT NULL DEFAULT 0",
            "suggestion_count": "INTEGER NOT NULL DEFAULT 0",
            "unverified_use_count": "INTEGER NOT NULL DEFAULT 0",
            "raw_examples": "TEXT NOT NULL DEFAULT '[]'",
            "parameter_bindings": "TEXT NOT NULL DEFAULT '[]'",
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
                   END,
                   base_confidence=CASE
                     WHEN base_confidence=0 THEN
                       CASE
                         WHEN confidence=0 THEN success_rate
                         ELSE confidence
                       END
                     ELSE base_confidence
                   END"""
        )
        conn.execute(
            """UPDATE procedures
               SET failure_count=CASE
                     WHEN failure_count=0 AND support_count > success_count
                       THEN support_count - success_count
                     ELSE failure_count
                   END"""
        )

        episode_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(episodes)").fetchall()
        }
        episode_additions = {
            "step_count": "INTEGER NOT NULL DEFAULT 0",
            "source": "TEXT NOT NULL DEFAULT 'agent'",
            "provenance": "TEXT NOT NULL DEFAULT '{}'",
            "parent_session_id": "TEXT",
            "is_segment": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, definition in episode_additions.items():
            if name not in episode_columns:
                conn.execute(f"ALTER TABLE episodes ADD COLUMN {name} {definition}")

        rows = conn.execute(
            "SELECT id, steps FROM episodes WHERE step_count=0"
        ).fetchall()
        for row in rows:
            try:
                steps = json.loads(row["steps"])
            except (TypeError, json.JSONDecodeError):
                steps = []
            conn.execute(
                "UPDATE episodes SET step_count=? WHERE id=?",
                (len(steps) if isinstance(steps, list) else 0, row["id"]),
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

    def get(self, mem_id: str) -> Memory | None:
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
                # Use milliseconds (int(time.time() * 1000)) to match the
                # upsert path's vector_clock unit. Previously this used
                # seconds (int(time.time())), which made every delete's
                # clock ~1000× smaller than every upsert's at the same
                # instant — deletes could never propagate via CRDT sync.
                (mem_id, int(time.time() * 1000), self.node_id, time.time()),
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
        layer: MemoryLayer | None = None,
        type: MemoryType | None = None,
        session_id: str | None = None,
        agent_id: str | None = None,
        source: str | None = None,
        since: float | None = None,
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

    def all_with_embeddings(self, layer: MemoryLayer | None = None) -> list[Memory]:
        sql = "SELECT * FROM memories WHERE deleted=0 AND embedding IS NOT NULL"
        args: list[Any] = []
        if layer:
            sql += " AND layer=?"; args.append(layer.value)
        rows = self._conn().execute(sql, args).fetchall()
        return [_row_to_memory(r) for r in rows]

    def count(self, layer: MemoryLayer | None = None) -> int:
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
                    duration_s, started_at, finished_at, step_count, source,
                    provenance, parent_session_id, is_segment)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ep_dict["id"], ep_dict["session_id"], ep_dict["agent_id"],
                    ep_dict["task"], json.dumps(ep_dict.get("steps", [])),
                    ep_dict.get("outcome"), ep_dict.get("error"),
                    ep_dict.get("duration_s", 0), ep_dict["started_at"],
                    ep_dict.get("finished_at"),
                    ep_dict.get("step_count", len(ep_dict.get("steps", []))),
                    ep_dict.get("source", "agent"),
                    json.dumps(ep_dict.get("provenance", {})),
                    ep_dict.get("parent_session_id"),
                    int(bool(ep_dict.get("is_segment", False))),
                ),
            )

    def query_episodes(
        self, *, agent_id: str | None = None, outcome: str | None = None,
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
        episodes: list[dict[str, Any]] = []
        for row in rows:
            episode = dict(row)
            try:
                episode["provenance"] = json.loads(
                    episode.get("provenance") or "{}"
                )
            except json.JSONDecodeError:
                episode["provenance"] = {}
            episode["is_segment"] = bool(episode.get("is_segment"))
            episode["task_signature"] = episode["task"]
            episode["start_time"] = episode["started_at"]
            episode["end_time"] = episode["finished_at"]
            episode["error_summary"] = episode["error"]
            episodes.append(episode)
        return episodes

    # ------------------------------------------------------------------ #
    # procedures
    # ------------------------------------------------------------------ #
    def put_procedure(self, p: dict[str, Any]) -> None:
        sample_count = int(p.get("sample_count", 0))
        support_count = int(p.get("support_count", sample_count))
        success_count = int(
            p.get(
                "success_count",
                round(p.get("success_rate", 0) * sample_count),
            )
        )
        failure_count = int(p.get("failure_count", 0))
        if failure_count == 0 and support_count > success_count:
            failure_count = support_count - success_count
        confidence = float(p.get("confidence", p.get("success_rate", 0)))
        base_confidence = float(p.get("base_confidence", 0) or confidence)
        with self.transaction() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO procedures
                   (id, task_signature, steps, preconditions, expected_outcome,
                    success_rate, sample_count, support_count, success_count,
                    failure_count, confidence, base_confidence,
                    feedback_success_count, feedback_failure_count,
                    suggestion_count, unverified_use_count, raw_examples,
                    parameter_bindings, source_episode_ids, created_at,
                    last_used_at, use_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    p["id"], p["task_signature"], json.dumps(p.get("steps", [])),
                    json.dumps(p.get("preconditions", [])), p.get("expected_outcome", ""),
                    p.get("success_rate", 0), sample_count,
                    support_count, success_count, failure_count,
                    confidence, base_confidence,
                    p.get("feedback_success_count", 0),
                    p.get("feedback_failure_count", 0),
                    p.get("suggestion_count", 0),
                    p.get("unverified_use_count", 0),
                    json.dumps(p.get("raw_supporting_examples", [])),
                    json.dumps(p.get("parameter_bindings", [])),
                    json.dumps(p.get("source_episode_ids", [])),
                    p.get("created_at", time.time()), p.get("last_used_at"),
                    p.get("use_count", 0),
                ),
            )

    def get_procedure(self, task_signature: str) -> dict[str, Any] | None:
        row = self._conn().execute(
            "SELECT * FROM procedures WHERE task_signature=?", (task_signature,)
        ).fetchone()
        return self._procedure_row(row) if row else None

    def get_procedure_by_id(self, procedure_id: str) -> dict[str, Any] | None:
        row = self._conn().execute(
            "SELECT * FROM procedures WHERE id=?",
            (procedure_id,),
        ).fetchone()
        return self._procedure_row(row) if row else None

    def all_procedures(self) -> list[dict[str, Any]]:
        rows = self._conn().execute("SELECT * FROM procedures").fetchall()
        out = []
        for r in rows:
            out.append(self._procedure_row(r))
        return out

    def attach_receipt(
        self,
        procedure_id: str,
        receipt_id: str,
        payload: dict[str, Any],
    ) -> bool:
        """Attach one receipt idempotently to an existing procedure."""
        with self.transaction() as conn:
            self._require_procedure(conn, procedure_id)
            cursor = conn.execute(
                """INSERT OR IGNORE INTO procedure_receipts(
                     procedure_id, receipt_id, payload, created_at
                   ) VALUES (?, ?, ?, ?)""",
                (
                    procedure_id,
                    receipt_id,
                    json.dumps(payload, sort_keys=True),
                    time.time(),
                ),
            )
        return cursor.rowcount > 0

    def list_receipts(self, procedure_id: str) -> list[dict[str, Any]]:
        """Return attached receipt payloads in stable order."""
        rows = self._conn().execute(
            """SELECT payload FROM procedure_receipts
               WHERE procedure_id=?
               ORDER BY receipt_id""",
            (procedure_id,),
        ).fetchall()
        receipts = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                receipts.append(payload)
        return receipts

    def _procedure_row(self, row: sqlite3.Row) -> dict[str, Any]:
        procedure = _row_to_procedure(row)
        procedure["receipts"] = self.list_receipts(str(row["id"]))
        return procedure

    def mark_procedure_suggested(
        self,
        procedure_id: str,
        reference_id: str,
        *,
        now: float | None = None,
    ) -> bool:
        """Record one suggestion once without affecting use outcomes."""
        timestamp = time.time() if now is None else float(now)
        with self.transaction() as conn:
            self._require_procedure(conn, procedure_id)
            existing = conn.execute(
                """SELECT state FROM procedure_feedback
                   WHERE procedure_id=? AND reference_id=?""",
                (procedure_id, reference_id),
            ).fetchone()
            if existing is not None:
                return False
            conn.execute(
                """INSERT INTO procedure_feedback(
                     procedure_id, reference_id, state, suggested_at
                   ) VALUES (?, ?, 'suggested', ?)""",
                (procedure_id, reference_id, timestamp),
            )
            conn.execute(
                """UPDATE procedures
                   SET suggestion_count=suggestion_count+1
                   WHERE id=?""",
                (procedure_id,),
            )
        return True

    def mark_procedure_used(
        self,
        procedure_id: str,
        reference_id: str,
        *,
        now: float | None = None,
    ) -> bool:
        """Record an unverified use once."""
        timestamp = time.time() if now is None else float(now)
        with self.transaction() as conn:
            self._require_procedure(conn, procedure_id)
            existing = conn.execute(
                """SELECT state FROM procedure_feedback
                   WHERE procedure_id=? AND reference_id=?""",
                (procedure_id, reference_id),
            ).fetchone()
            if existing is not None and existing["state"] != "suggested":
                return False
            if existing is None:
                conn.execute(
                    """INSERT INTO procedure_feedback(
                         procedure_id, reference_id, state, used_at
                       ) VALUES (?, ?, 'used', ?)""",
                    (procedure_id, reference_id, timestamp),
                )
            else:
                conn.execute(
                    """UPDATE procedure_feedback
                       SET state='used', used_at=?
                       WHERE procedure_id=? AND reference_id=?""",
                    (timestamp, procedure_id, reference_id),
                )
            conn.execute(
                """UPDATE procedures
                   SET use_count=use_count+1,
                       unverified_use_count=unverified_use_count+1,
                       last_used_at=?
                   WHERE id=?""",
                (timestamp, procedure_id),
            )
        return True

    def record_procedure_outcome(
        self,
        procedure_id: str,
        episode_id: str,
        outcome: str,
        *,
        now: float | None = None,
    ) -> bool:
        """Record one verified success/failure and update aggregate stats."""
        normalized_outcome = str(outcome or "").strip().lower()
        if normalized_outcome not in {"success", "failure"}:
            raise ValueError("procedure outcome must be 'success' or 'failure'")
        timestamp = time.time() if now is None else float(now)

        with self.transaction() as conn:
            procedure_row = self._require_procedure(conn, procedure_id)
            feedback_row = conn.execute(
                """SELECT state, outcome FROM procedure_feedback
                   WHERE procedure_id=? AND reference_id=?""",
                (procedure_id, episode_id),
            ).fetchone()
            if feedback_row is not None and feedback_row["outcome"] is not None:
                if feedback_row["outcome"] != normalized_outcome:
                    raise StoreError(
                        "procedure outcome already recorded with a different value"
                    )
                return False

            was_pending = (
                feedback_row is not None and feedback_row["state"] == "used"
            )
            was_used = feedback_row is not None and feedback_row["state"] in {
                "used",
                "success",
                "failure",
            }
            if feedback_row is None:
                conn.execute(
                    """INSERT INTO procedure_feedback(
                         procedure_id, reference_id, state, outcome,
                         used_at, observed_at
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        procedure_id,
                        episode_id,
                        normalized_outcome,
                        normalized_outcome,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                conn.execute(
                    """UPDATE procedure_feedback
                       SET state=?, outcome=?, used_at=COALESCE(used_at, ?),
                           observed_at=?
                       WHERE procedure_id=? AND reference_id=?""",
                    (
                        normalized_outcome,
                        normalized_outcome,
                        timestamp,
                        timestamp,
                        procedure_id,
                        episode_id,
                    ),
                )

            success_count = int(procedure_row["success_count"])
            failure_count = int(procedure_row["failure_count"])
            feedback_success_count = int(
                procedure_row["feedback_success_count"]
            )
            feedback_failure_count = int(
                procedure_row["feedback_failure_count"]
            )
            if normalized_outcome == "success":
                success_count += 1
                feedback_success_count += 1
            else:
                failure_count += 1
                feedback_failure_count += 1
            support_count = success_count + failure_count
            success_rate = procedure_success_rate(
                success_count,
                support_count,
            )
            confidence = procedure_feedback_confidence(
                base_confidence=float(procedure_row["base_confidence"]),
                success_count=success_count,
                support_count=support_count,
            )
            source_episode_ids = _json_list(
                procedure_row["source_episode_ids"]
            )
            source_episode_ids = sorted(
                {*map(str, source_episode_ids), str(episode_id)}
            )
            conn.execute(
                """UPDATE procedures
                   SET support_count=?, success_count=?, failure_count=?,
                       feedback_success_count=?, feedback_failure_count=?,
                       success_rate=?, confidence=?,
                       source_episode_ids=?,
                       use_count=use_count+?,
                       unverified_use_count=MAX(
                         0, unverified_use_count-?
                       ),
                       last_used_at=?
                   WHERE id=?""",
                (
                    support_count,
                    success_count,
                    failure_count,
                    feedback_success_count,
                    feedback_failure_count,
                    success_rate,
                    confidence,
                    json.dumps(source_episode_ids),
                    0 if was_used else 1,
                    1 if was_pending else 0,
                    timestamp,
                    procedure_id,
                ),
            )
        return True

    def pending_procedure_uses(self, reference_id: str) -> list[str]:
        """Return procedures awaiting an outcome for one session reference."""
        rows = self._conn().execute(
            """SELECT procedure_id FROM procedure_feedback
               WHERE reference_id=? AND state='used'
               ORDER BY procedure_id""",
            (reference_id,),
        ).fetchall()
        return [str(row["procedure_id"]) for row in rows]

    @staticmethod
    def _require_procedure(
        conn: sqlite3.Connection,
        procedure_id: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM procedures WHERE id=?",
            (procedure_id,),
        ).fetchone()
        if row is None:
            raise StoreError(f"no procedure with id={procedure_id}")
        return row

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
        on (vector_clock, node_id).

        Delete ops are clock-checked: a stale delete (vector_clock lower
        than the memory's current clock) is rejected, preventing an old
        delete from tombstoning a newer upsert. This is the CRDT
        correctness fix for the data-loss bug found in the senior
        inspection.
        """
        payload = json.loads(op["payload"]) if op["payload"] != "{}" else None
        with self.transaction() as conn:
            if op["op"] == "delete":
                # Clock check: reject stale deletes that would tombstone a
                # newer memory. Previously this was unconditional, which
                # meant a slow node's old delete could erase a newer write.
                existing = conn.execute(
                    "SELECT vector_clock, deleted FROM memories WHERE id=?",
                    (op["memory_id"],),
                ).fetchone()
                if existing is not None:
                    existing_vc = existing["vector_clock"]
                    existing_deleted = existing["deleted"]
                    op_vc = int(op.get("vector_clock", 0))
                    if op_vc < existing_vc:
                        # Stale delete — the memory has a newer clock.
                        # Reject to preserve the newer write.
                        return
                    if existing_deleted and op_vc <= existing_vc:
                        # Already deleted at an equal-or-higher clock.
                        # Idempotent no-op.
                        return
                conn.execute(
                    "UPDATE memories SET deleted=1 WHERE id=?",
                    (op["memory_id"],),
                )
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
def _pack_embedding(emb: list[float] | None) -> bytes | None:
    if emb is None:
        return None
    import struct
    return struct.pack(f"<{len(emb)}f", *emb)


def _unpack_embedding(blob: bytes | None) -> list[float] | None:
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


def _row_to_procedure(row: sqlite3.Row) -> dict[str, Any]:
    procedure = dict(row)
    procedure["steps"] = _json_list(procedure["steps"])
    procedure["preconditions"] = _json_list(procedure["preconditions"])
    procedure["raw_supporting_examples"] = _json_list(
        procedure.pop("raw_examples")
    )
    procedure["parameter_bindings"] = _json_list(
        procedure["parameter_bindings"]
    )
    procedure["source_episode_ids"] = _json_list(
        procedure["source_episode_ids"]
    )
    return procedure


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return decoded if isinstance(decoded, list) else []
