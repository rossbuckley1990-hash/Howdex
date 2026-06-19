"""CRDT-style sync for Howdex.

Two modes:

* **Local file sync** — replicate the SQLite file to another path (e.g. a
  Dropbox folder, a USB stick). Uses the sync_log to avoid copying the
  whole DB.
* **HTTP peer sync** — POST pending ops to a peer Howdex node, GET theirs.

The CRDT property comes from:

  1. Every memory carries a ``(vector_clock, node_id)`` pair.
  2. Deletes are tombstones (``deleted=1``), not physical deletes.
  3. Conflict resolution is last-writer-wins on ``vector_clock``, ties
     broken by ``node_id`` lexicographically. Deterministic, no merges lost.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any, Optional

from howdex.core.errors import SyncError
from howdex.storage import Store


def export_ops(store: Store, since_id: int = 0) -> list[dict[str, Any]]:
    """Return all unsynced ops since ``since_id``."""
    return store.pending_sync_ops(since_id=since_id)


def import_ops(store: Store, ops: list[dict[str, Any]]) -> int:
    """Apply a batch of remote ops. Returns number applied."""
    applied = 0
    for op in ops:
        try:
            store.apply_remote_op(op)
            applied += 1
        except Exception as e:  # noqa: BLE001
            raise SyncError(f"failed to apply op {op.get('id')}: {e}") from e
    return applied


def sync_with_peer(store: Store, peer_url: str) -> dict[str, int]:
    """Two-way sync with an HTTP peer.

    ``peer_url`` should be the base URL of a Howdex MCP/sync server, e.g.
    ``http://localhost:7331``. Endpoints used:

      POST /sync/push   — send our pending ops, receive their applied count
      GET  /sync/pull   — receive their pending ops

    Returns ``{"pushed": n, "pulled": n}``.
    """
    if not peer_url.startswith(("http://", "https://")):
        raise SyncError("peer_url must start with http:// or https://")

    # push
    ops = export_ops(store)
    pushed = 0
    if ops:
        try:
            req = urllib.request.Request(
                f"{peer_url.rstrip('/')}/sync/push",
                data=json.dumps({"ops": ops}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                pushed = json.loads(resp.read()).get("applied", 0)
            store.mark_synced([op["id"] for op in ops])
        except urllib.error.URLError as e:
            raise SyncError(f"push failed: {e}") from e

    # pull
    try:
        req = urllib.request.Request(
            f"{peer_url.rstrip('/')}/sync/pull",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        pulled = import_ops(store, data.get("ops", []))
    except urllib.error.URLError as e:
        raise SyncError(f"pull failed: {e}") from e

    return {"pushed": pushed, "pulled": pulled}


def sync_to_file(store: Store, target_path: str) -> int:
    """Export pending ops to a JSON file (sneakernet / air-gapped sync)."""
    import os
    ops = export_ops(store)
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    with open(target_path, "w") as f:
        json.dump({"node_id": store.node_id, "ops": ops}, f, indent=2)
    store.mark_synced([op["id"] for op in ops])
    return len(ops)


def sync_from_file(store: Store, source_path: str) -> int:
    """Import ops from a JSON file produced by :func:`sync_to_file`."""
    with open(source_path) as f:
        data = json.load(f)
    return import_ops(store, data.get("ops", []))
