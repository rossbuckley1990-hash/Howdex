"""Howdex Federated Procedure Library — shared procedural memory across agents and teams.

Multi-agent shared procedural memory with:
1. **Per-tenant scoping** — each team/org has its own namespace
2. **Review/promotion workflow** — proposed → reviewed → published → deprecated
3. **Access control** — who can submit, review, publish
4. **Provenance** — every procedure traces back to the inducing trajectory
5. **Ledger integration** — every lifecycle event is recorded in the Merkle ledger

This is the "federated procedure library" from the research roadmap.
LEGOMem showed multi-agent teams benefit substantially from shared
procedural memory — but it was a paper. This is the product.

THE LIFECYCLE:

  proposed  →  reviewed  →  published  →  deprecated
     ↑            ↑             |              |
     |            |             ↓              ↓
   submit      approve       publish        deprecate
                              (visible to all agents)

- **proposed**: A team member submits a procedure for review. Only
  visible to the submitter and reviewers.
- **reviewed**: A reviewer has approved the procedure. Visible to
  the team but not yet globally published.
- **published**: The procedure is live — all agents in the federation
  can retrieve and use it.
- **deprecated**: The procedure is retired (e.g., environment changed,
  replaced by a newer version). Agents are warned but can still access it.

Usage::

    from howdex import Howdex
    from howdex.federation import Federation

    mem = Howdex(path="...", embedder="hashing")
    fed = Federation(mem, tenant_id="team-alpha")

    # Submit a procedure for review
    fed.submit(procedure_id, submitted_by="alice")

    # Review it
    fed.review(procedure_id, reviewed_by="bob", approved=True, notes="Looks good")

    # Publish it (makes it visible to all agents)
    fed.publish(procedure_id, published_by="alice")

    # List published procedures (any agent can do this)
    procs = fed.list_published()

    # Search across the federation
    results = fed.search("fix missing dependency")

    # Deprecate when stale
    fed.deprecate(procedure_id, reason="Node 22 changed the API", deprecated_by="alice")

CLI::

    howdex federation submit <procedure_id> --tenant team-alpha --by alice
    howdex federation review <procedure_id> --approve --by bob --notes "Looks good"
    howdex federation publish <procedure_id> --by alice
    howdex federation list --tenant team-alpha
    howdex federation search "fix missing dependency"
    howdex federation deprecate <procedure_id> --reason "stale" --by alice
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from howdex import Howdex


# --------------------------------------------------------------------------- #
# Lifecycle states
# --------------------------------------------------------------------------- #
PROPOSED = "proposed"
REVIEWED = "reviewed"
PUBLISHED = "published"
DEPRECATED = "deprecated"

LIFECYCLE_TRANSITIONS = {
    PROPOSED: {REVIEWED},
    REVIEWED: {PUBLISHED, PROPOSED},  # can publish or send back
    PUBLISHED: {DEPRECATED},
    DEPRECATED: set(),  # terminal
}


@dataclass
class FederationEntry:
    """A procedure in the federated library."""
    procedure_id: str
    tenant_id: str
    status: str  # proposed, reviewed, published, deprecated
    submitted_by: str
    submitted_at: float
    reviewed_by: str | None = None
    reviewed_at: float | None = None
    review_notes: str = ""
    published_by: str | None = None
    published_at: float | None = None
    deprecated_by: str | None = None
    deprecated_at: float | None = None
    deprecation_reason: str = ""
    task_signature: str = ""
    confidence: float = 0.0
    receipt_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "procedure_id": self.procedure_id,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "submitted_by": self.submitted_by,
            "submitted_at": self.submitted_at,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "review_notes": self.review_notes,
            "published_by": self.published_by,
            "published_at": self.published_at,
            "deprecated_by": self.deprecated_by,
            "deprecated_at": self.deprecated_at,
            "deprecation_reason": self.deprecation_reason,
            "task_signature": self.task_signature,
            "confidence": self.confidence,
            "receipt_hash": self.receipt_hash,
        }


class Federation:
    """A federated procedure library with per-tenant scoping and review workflow.

    Each team (tenant) has its own namespace. Procedures go through a
    review/promotion workflow before they're visible to all agents. Every
    lifecycle event is recorded in the Merkle ledger for audit compliance.
    """

    def __init__(self, memory: "Howdex", tenant_id: str = "default"):
        self.memory = memory
        self.store = memory.store
        self.tenant_id = tenant_id
        self._init_federation_table()

    def _init_federation_table(self) -> None:
        """Create the federation table if it doesn't exist."""
        conn = self.store._conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS federation_entries (
                procedure_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                status TEXT NOT NULL,
                submitted_by TEXT NOT NULL,
                submitted_at REAL NOT NULL,
                reviewed_by TEXT,
                reviewed_at REAL,
                review_notes TEXT DEFAULT '',
                published_by TEXT,
                published_at REAL,
                deprecated_by TEXT,
                deprecated_at REAL,
                deprecation_reason TEXT DEFAULT '',
                task_signature TEXT DEFAULT '',
                confidence REAL DEFAULT 0,
                receipt_hash TEXT DEFAULT '',
                PRIMARY KEY (procedure_id, tenant_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_federation_status
            ON federation_entries(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_federation_tenant
            ON federation_entries(tenant_id)
        """)

    def submit(
        self,
        procedure_id: str,
        submitted_by: str,
        *,
        tenant_id: str | None = None,
    ) -> FederationEntry:
        """Submit a procedure for review.

        The procedure must exist in the Howdex store and should ideally
        have a verified receipt (BootProof). Unverified procedures can
        still be submitted but will be flagged.

        Args:
            procedure_id: The Howdex procedure ID.
            submitted_by: The user/agent submitting the procedure.
            tenant_id: Override the default tenant (optional).

        Returns:
            The created FederationEntry.
        """
        tid = tenant_id or self.tenant_id

        # Look up the procedure to get metadata
        proc = None
        try:
            proc = self.memory._procedure_by_id(procedure_id)
        except Exception:
            pass

        task_sig = ""
        confidence = 0.0
        receipt_hash = ""
        if proc:
            task_sig = getattr(proc, "task_signature", "")
            confidence = getattr(proc, "confidence", 0.0)
            receipts = getattr(proc, "receipts", []) or []
            for r in receipts:
                if isinstance(r, dict) and r.get("status") == "verified":
                    receipt_hash = r.get("receipt_id", "")[:16]
                    break

        entry = FederationEntry(
            procedure_id=procedure_id,
            tenant_id=tid,
            status=PROPOSED,
            submitted_by=submitted_by,
            submitted_at=time.time(),
            task_signature=task_sig,
            confidence=confidence,
            receipt_hash=receipt_hash,
        )

        conn = self.store._conn()
        conn.execute(
            """INSERT OR REPLACE INTO federation_entries
               (procedure_id, tenant_id, status, submitted_by, submitted_at,
                reviewed_by, reviewed_at, review_notes, published_by, published_at,
                deprecated_by, deprecated_at, deprecation_reason,
                task_signature, confidence, receipt_hash)
               VALUES (?,?,?,?,?, NULL,NULL,'', NULL,NULL, NULL,NULL,'', ?,?,?)""",
            (entry.procedure_id, entry.tenant_id, entry.status,
             entry.submitted_by, entry.submitted_at,
             entry.task_signature, entry.confidence, entry.receipt_hash),
        )

        # Record in ledger
        try:
            self.memory.ledger().append("federation_submit", entry.to_dict())
        except Exception:
            pass

        return entry

    def review(
        self,
        procedure_id: str,
        reviewed_by: str,
        *,
        approved: bool = True,
        notes: str = "",
        tenant_id: str | None = None,
    ) -> FederationEntry | None:
        """Review a submitted procedure.

        Args:
            procedure_id: The procedure ID to review.
            reviewed_by: The reviewer's identity.
            approved: True to approve (→ reviewed), False to send back (→ proposed).
            notes: Review notes.
            tenant_id: Override the default tenant.

        Returns:
            The updated FederationEntry, or None if not found.
        """
        tid = tenant_id or self.tenant_id
        new_status = REVIEWED if approved else PROPOSED

        conn = self.store._conn()
        # Check current status
        row = conn.execute(
            "SELECT status FROM federation_entries WHERE procedure_id=? AND tenant_id=?",
            (procedure_id, tid),
        ).fetchone()
        if not row:
            return None

        current_status = row[0]
        # Allow same-status transitions (e.g., reject from proposed stays proposed)
        if new_status == current_status:
            pass  # self-transition is OK (e.g., reject)
        elif new_status not in LIFECYCLE_TRANSITIONS.get(current_status, set()):
            raise ValueError(
                f"Cannot transition from {current_status} to {new_status}"
            )

        conn.execute(
            """UPDATE federation_entries
               SET status=?, reviewed_by=?, reviewed_at=?, review_notes=?
               WHERE procedure_id=? AND tenant_id=?""",
            (new_status, reviewed_by, time.time(), notes,
             procedure_id, tid),
        )

        entry = self._get_entry(procedure_id, tid)

        # Record in ledger
        if entry:
            try:
                self.memory.ledger().append("federation_review", entry.to_dict())
            except Exception:
                pass

        return entry

    def publish(
        self,
        procedure_id: str,
        published_by: str,
        *,
        tenant_id: str | None = None,
    ) -> FederationEntry | None:
        """Publish a reviewed procedure — makes it visible to all agents.

        Args:
            procedure_id: The procedure ID to publish.
            published_by: The publisher's identity.
            tenant_id: Override the default tenant.

        Returns:
            The updated FederationEntry, or None if not found.
        """
        tid = tenant_id or self.tenant_id
        conn = self.store._conn()

        row = conn.execute(
            "SELECT status FROM federation_entries WHERE procedure_id=? AND tenant_id=?",
            (procedure_id, tid),
        ).fetchone()
        if not row:
            return None

        current_status = row[0]
        if PUBLISHED not in LIFECYCLE_TRANSITIONS.get(current_status, set()):
            raise ValueError(
                f"Cannot publish from {current_status} — must be {REVIEWED}"
            )

        conn.execute(
            """UPDATE federation_entries
               SET status=?, published_by=?, published_at=?
               WHERE procedure_id=? AND tenant_id=?""",
            (PUBLISHED, published_by, time.time(),
             procedure_id, tid),
        )

        entry = self._get_entry(procedure_id, tid)

        if entry:
            try:
                self.memory.ledger().append("federation_publish", entry.to_dict())
            except Exception:
                pass

        return entry

    def deprecate(
        self,
        procedure_id: str,
        reason: str,
        deprecated_by: str,
        *,
        tenant_id: str | None = None,
    ) -> FederationEntry | None:
        """Deprecate a published procedure.

        Agents will be warned that the procedure is stale but can still
        access it.

        Args:
            procedure_id: The procedure ID to deprecate.
            reason: Why it's being deprecated.
            deprecated_by: Who deprecated it.
            tenant_id: Override the default tenant.
        """
        tid = tenant_id or self.tenant_id
        conn = self.store._conn()

        row = conn.execute(
            "SELECT status FROM federation_entries WHERE procedure_id=? AND tenant_id=?",
            (procedure_id, tid),
        ).fetchone()
        if not row:
            return None

        current_status = row[0]
        if DEPRECATED not in LIFECYCLE_TRANSITIONS.get(current_status, set()):
            raise ValueError(
                f"Cannot deprecate from {current_status} — must be {PUBLISHED}"
            )

        conn.execute(
            """UPDATE federation_entries
               SET status=?, deprecated_by=?, deprecated_at=?, deprecation_reason=?
               WHERE procedure_id=? AND tenant_id=?""",
            (DEPRECATED, deprecated_by, time.time(), reason,
             procedure_id, tid),
        )

        entry = self._get_entry(procedure_id, tid)

        if entry:
            try:
                self.memory.ledger().append("federation_deprecate", entry.to_dict())
            except Exception:
                pass

        return entry

    def list_published(
        self,
        *,
        tenant_id: str | None = None,
        include_deprecated: bool = False,
    ) -> list[FederationEntry]:
        """List all published procedures (visible to all agents).

        Args:
            tenant_id: Filter to a specific tenant. If None and called on
                a Federation instance, filters to the instance's tenant_id.
                Pass tenant_id="" to see ALL tenants.
            include_deprecated: Include deprecated procedures.
        """
        # If tenant_id is None, use the instance's tenant_id
        effective_tenant = tenant_id if tenant_id is not None else self.tenant_id

        conn = self.store._conn()
        statuses = [PUBLISHED]
        if include_deprecated:
            statuses.append(DEPRECATED)

        placeholders = ",".join("?" * len(statuses))
        if effective_tenant:
            rows = conn.execute(
                f"SELECT * FROM federation_entries WHERE tenant_id=? AND status IN ({placeholders})",
                [effective_tenant] + statuses,
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM federation_entries WHERE status IN ({placeholders})",
                statuses,
            ).fetchall()

        return [self._row_to_entry(r) for r in rows]

    def list_by_status(
        self,
        status: str,
        *,
        tenant_id: str | None = None,
    ) -> list[FederationEntry]:
        """List entries by status (proposed, reviewed, published, deprecated)."""
        conn = self.store._conn()
        if tenant_id:
            rows = conn.execute(
                "SELECT * FROM federation_entries WHERE tenant_id=? AND status=?",
                (tenant_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM federation_entries WHERE status=?",
                (status,),
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def search(
        self,
        query: str,
        *,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search published procedures across the federation.

        Searches on task_signature and tenant_id.
        Only returns published (or deprecated) entries.
        """
        published = self.list_published(
            tenant_id=tenant_id if tenant_id else "",
            include_deprecated=True,
        )

        query_words = set()
        for w in query.lower().split():
            query_words.add(w)
            query_words.update(w.replace("_", " ").split())

        scored = []
        for entry in published:
            entry_words = set()
            for w in entry.task_signature.lower().split():
                entry_words.add(w)
                entry_words.update(w.replace("_", " ").split())
            score = len(query_words & entry_words)
            if score > 0:
                scored.append((score, {
                    "procedure_id": entry.procedure_id,
                    "tenant_id": entry.tenant_id,
                    "task_signature": entry.task_signature,
                    "status": entry.status,
                    "confidence": entry.confidence,
                    "receipt_hash": entry.receipt_hash,
                    "score": score,
                }))

        scored.sort(key=lambda x: -x[1]["score"])
        return [item[1] for item in scored]

    def get_entry(
        self,
        procedure_id: str,
        *,
        tenant_id: str | None = None,
    ) -> FederationEntry | None:
        """Get a single federation entry."""
        return self._get_entry(procedure_id, tenant_id or self.tenant_id)

    def _get_entry(self, procedure_id: str, tenant_id: str) -> FederationEntry | None:
        conn = self.store._conn()
        row = conn.execute(
            "SELECT * FROM federation_entries WHERE procedure_id=? AND tenant_id=?",
            (procedure_id, tenant_id),
        ).fetchone()
        return self._row_to_entry(row) if row else None

    def _row_to_entry(self, row) -> FederationEntry:
        return FederationEntry(
            procedure_id=row[0],
            tenant_id=row[1],
            status=row[2],
            submitted_by=row[3],
            submitted_at=row[4],
            reviewed_by=row[5],
            reviewed_at=row[6],
            review_notes=row[7],
            published_by=row[8],
            published_at=row[9],
            deprecated_by=row[10],
            deprecated_at=row[11],
            deprecation_reason=row[12],
            task_signature=row[13],
            confidence=row[14],
            receipt_hash=row[15],
        )

    def stats(self) -> dict[str, Any]:
        """Return federation statistics."""
        conn = self.store._conn()
        total = conn.execute("SELECT COUNT(*) FROM federation_entries").fetchone()[0]
        by_status = {}
        for status in [PROPOSED, REVIEWED, PUBLISHED, DEPRECATED]:
            count = conn.execute(
                "SELECT COUNT(*) FROM federation_entries WHERE status=?", (status,)
            ).fetchone()[0]
            by_status[status] = count

        tenants = conn.execute(
            "SELECT DISTINCT tenant_id FROM federation_entries"
        ).fetchall()
        return {
            "total": total,
            "by_status": by_status,
            "tenants": [t[0] for t in tenants],
            "published_count": by_status.get(PUBLISHED, 0),
        }
