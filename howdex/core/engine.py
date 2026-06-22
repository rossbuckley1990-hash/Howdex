"""The Howdex engine — the single entry point for agents."""

from __future__ import annotations

import json

import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Optional, Union

from howdex.core.types import (
    Memory,
    MemoryLayer,
    MemoryType,
    HowdexResult,
    Episode,
    Procedure,
)
from howdex.core.errors import HowdexError, HowdexNotFoundError
from howdex.core.retrieval import tokenize, keyword_score, graph_neighbors
from howdex.core.safety import memory_safety_multiplier
from howdex.core.session import HowdexSession
from howdex.core.trust import TrustMetadata
from howdex.core.consolidation import consolidate
from howdex.core.tool_calls import canonicalize_tool_call, redact_secrets
from howdex.core.segmentation import (
    DEFAULT_IDLE_GAP_S,
    DEFAULT_MAX_SEGMENT_STEPS,
    segment_episode,
)
from howdex.core.semantic import derive_tool_semantics
from howdex.core.guidance import (
    ProcedureSuggestion,
    render_procedure_guidance,
    suggest_procedures,
)
from howdex.core.working import (
    DEFAULT_WORKING_MAX_CHARS,
    DEFAULT_WORKING_MAX_ITEMS,
    select_working_context,
)
from howdex.storage import Store
from howdex.vectors import VectorIndex, Embedder, auto_embedder


DEFAULT_HOME = Path(os.environ.get("HOWDEX_HOME", Path.home() / ".howdex"))
DEFAULT_DIM = 384



def _normalise_procedure_payload(payload):
    """Normalise procedure rows loaded from storage.

    Storage may return SQLite rows/dicts where steps and preconditions are JSON
    strings. Public Howdex APIs must always expose them as Python lists.
    """
    if payload is None:
        return None

    if isinstance(payload, dict):
        d = dict(payload)
    elif hasattr(payload, "__dict__"):
        d = dict(payload.__dict__)
    else:
        d = dict(payload)

    for key in (
        "steps",
        "preconditions",
        "raw_supporting_examples",
        "source_episode_ids",
    ):
        value = d.get(key)

        if isinstance(value, str):
            try:
                d[key] = json.loads(value)
            except json.JSONDecodeError:
                d[key] = []

        elif value is None:
            d[key] = []

    return d


class Howdex:
    """Procedural memory for autonomous agents.

    Zero-config:

        >>> from howdex import Howdex
        >>> mem = Howdex()              # creates ~/.howdex/howdex.db

    With options:

        >>> mem = Howdex(
        ...     path="./myagent.db",
        ...     embedder="st",          # sentence-transformers
        ...     agent_id="bot-42",
        ... )

    The four memory layers:

      * **working**    — short-lived per-task context (auto-expires)
      * **semantic**   — facts, preferences, entities (the knowledge base)
      * **episodic**   — session logs, outcomes, error traces
      * **procedural** — learned workflows (output of ``learn()``)
    """

    def __init__(
        self,
        *,
        path: Optional[Union[str, Path]] = None,
        embedder: Union[str, Embedder, None] = None,
        agent_id: Optional[str] = None,
        embed_dim: int = DEFAULT_DIM,
    ):
        self.path = Path(path) if path else DEFAULT_HOME / "howdex.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.agent_id = agent_id

        # embedder
        if isinstance(embedder, Embedder):
            self.embedder = embedder
        else:
            self.embedder = auto_embedder(preferred=embedder, dim=embed_dim)
        self.embed_dim = self.embedder.dim

        # storage
        self.store = Store(self.path)

        # vector index (rebuilt from store)
        self.index = VectorIndex(dim=self.embed_dim, metric="cosine")
        self._rebuild_index()

        # session bookkeeping
        self._current_session: Optional[Episode] = None

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    def _rebuild_index(self) -> None:
        for mem in self.store.all_with_embeddings():
            if mem.embedding:
                self.index.add(mem.id, mem.embedding)

    def close(self) -> None:
        """Persist any in-flight state. Safe to call multiple times."""
        if self._current_session and not self._current_session.finished_at:
            self.end_session(outcome="partial")

    def __enter__(self) -> "Howdex":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        stats = self.stats()
        return (
            f"<Howdex path={self.path!s} "
            f"memories={stats['total_memories']} "
            f"backend={self.embedder.name}>"
        )

    # ------------------------------------------------------------------ #
    # core: remember
    # ------------------------------------------------------------------ #
    def remember(
        self,
        content: str,
        *,
        layer: Union[str, MemoryLayer] = MemoryLayer.SEMANTIC,
        type: Union[str, MemoryType] = MemoryType.FACT,
        metadata: Optional[dict[str, Any]] = None,
        importance: float = 0.5,
        ttl: Optional[float] = None,
        relations: Optional[list[dict[str, str]]] = None,
        source: str = "user",
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        embed: bool = True,
        confidence: Optional[float] = None,
        provenance: Optional[dict[str, Any]] = None,
    ) -> Memory:
        """Store a memory.

        Returns the created :class:`Memory` (with generated ``id``).

        Examples
        --------
        >>> mem.remember("User prefers dark mode", layer="semantic",
        ...              type="preference", importance=0.9)
        >>> mem.remember("step 1 done", layer="working", ttl=300)
        """
        if isinstance(layer, str):
            layer = MemoryLayer(layer)
        if isinstance(type, str):
            type = MemoryType(type)

        # working memory default TTL: 5 min
        if ttl is None and layer == MemoryLayer.WORKING:
            ttl = 300.0

        memory_metadata = dict(metadata or {})
        if layer == MemoryLayer.SEMANTIC:
            from howdex.core.conflicts import semantic_conflict_metadata

            memory_metadata.setdefault("semantic_origin", "explicit")
            if confidence is not None:
                memory_metadata["confidence"] = round(
                    max(0.0, min(1.0, float(confidence))),
                    4,
                )
            if provenance is not None:
                memory_metadata["provenance"] = redact_secrets(provenance)[0]
            conflict_metadata = semantic_conflict_metadata(
                content,
                self.store.query(layer=MemoryLayer.SEMANTIC, limit=10_000),
            )
            memory_metadata.update(conflict_metadata)

        embedding = self.embedder.embed(content) if embed else None

        m = Memory(
            layer=layer,
            type=type,
            content=content,
            metadata=memory_metadata,
            embedding=embedding,
            relations=relations or [],
            source=source,
            agent_id=agent_id or self.agent_id,
            session_id=session_id or (self._current_session.session_id if self._current_session else None),
            importance=importance,
            ttl=ttl,
            vector_clock=int(time.time() * 1000),
        )
        self.store.put(m)
        if embedding:
            self.index.add(m.id, embedding)
        return m

    def get_working_context(
        self,
        session_id: Optional[str] = None,
        *,
        max_items: Optional[int] = DEFAULT_WORKING_MAX_ITEMS,
        max_chars: Optional[int] = DEFAULT_WORKING_MAX_CHARS,
        token_budget: Optional[int] = None,
        include_provenance: bool = True,
    ) -> str:
        """Return deterministic, prompt-ready working memory for one session.

        ``token_budget`` uses a conservative four-characters-per-token
        approximation and is combined with ``max_chars`` using the smaller
        limit. Stored memories are not deleted when they are evicted from this
        context window.
        """
        resolved_session_id = session_id or (
            self._current_session.session_id
            if self._current_session
            else None
        )
        if not resolved_session_id:
            return ""
        memories = self.store.query(
            layer=MemoryLayer.WORKING,
            session_id=resolved_session_id,
            limit=10_000,
        )
        _, context = select_working_context(
            memories,
            max_items=max_items,
            max_chars=max_chars,
            token_budget=token_budget,
            include_provenance=include_provenance,
        )
        return context

    # ------------------------------------------------------------------ #
    # core: recall
    # ------------------------------------------------------------------ #
    def recall(
        self,
        query: str,
        *,
        layer: Optional[Union[str, MemoryLayer]] = None,
        top_k: int = 5,
        min_score: float = 0.1,
        hybrid: bool = True,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        include_expired: bool = False,
    ) -> list[HowdexResult]:
        """Retrieve the most relevant memories for ``query``.

        Uses **hybrid retrieval** by default:

          * **vector** — cosine similarity over embeddings
          * **keyword** — TF overlap on tokens
          * **graph**   — 1-hop BFS over memory.relations

        Scores are normalized to [0, 1] and combined as a weighted sum:
        ``0.6 * vector + 0.3 * keyword + 0.1 * graph``.

        Returns at most ``top_k`` :class:`HowdexResult` objects sorted desc.

        Examples
        --------
        >>> results = mem.recall("UI preferences", top_k=3)
        >>> for r in results:
        ...     print(r.score, r.memory.content)
        """
        if layer and isinstance(layer, str):
            layer = MemoryLayer(layer)

        if layer == MemoryLayer.PROCEDURAL:
            return self._recall_procedures(
                query,
                top_k=top_k,
                min_score=min_score,
            )

        now = time.time()
        candidates: dict[str, dict[str, Any]] = {}

        # vector search
        q_vec = self.embedder.embed(query)
        vec_hits = self.index.search(q_vec, k=top_k * 3, min_score=0.0)
        for mem_id, score in vec_hits:
            candidates[mem_id] = {"vector": max(0.0, score)}

        # keyword search over all (or layer-filtered) memories
        if hybrid:
            q_tokens = tokenize(query)
            all_mems = self.store.query(layer=layer, limit=10_000)
            for m in all_mems:
                ks = keyword_score(q_tokens, m)
                if ks > 0:
                    candidates.setdefault(m.id, {})["keyword"] = ks
                    # keep the Memory object cached for graph search
                    candidates[m.id]["_mem"] = m

        # fetch full memory objects for vector hits that we didn't already load
        for mem_id in list(candidates.keys()):
            if "_mem" not in candidates[mem_id]:
                m = self.store.get(mem_id)
                if m is None:
                    candidates.pop(mem_id, None)
                    continue
                candidates[mem_id]["_mem"] = m

        # graph expansion (1-hop from vector + keyword hits)
        if hybrid and candidates:
            seed_ids = set(candidates.keys())
            # load all memories for graph traversal (cheap if few)
            all_mems = self.store.query(layer=layer, limit=10_000)
            neighbor_ids = graph_neighbors(all_mems, seed_ids, hops=1)
            for nid in neighbor_ids:
                if nid in candidates:
                    candidates[nid]["graph"] = candidates[nid].get("graph", 0) + 0.3
                else:
                    m = self.store.get(nid)
                    if m:
                        candidates[nid] = {"graph": 0.3, "_mem": m}

        # filter & score
        results: list[HowdexResult] = []
        for mem_id, parts in candidates.items():
            m: Memory = parts["_mem"]
            # filters
            if layer and m.layer != layer:
                continue
            if agent_id and m.agent_id != agent_id:
                continue
            if session_id and m.session_id != session_id:
                continue
            if not include_expired and m.is_expired(now):
                continue
            # weighted score
            v = parts.get("vector", 0.0)
            k = parts.get("keyword", 0.0)
            g = parts.get("graph", 0.0)
            score = 0.6 * v + 0.3 * k + 0.1 * g
            if score < min_score:
                continue
            matched_by = "hybrid" if hybrid else "vector"
            if v > 0 and k == 0 and g == 0:
                matched_by = "vector"
            elif v == 0 and k > 0 and g == 0:
                matched_by = "keyword"
            elif v == 0 and k == 0 and g > 0:
                matched_by = "graph"
            safe_score = score * memory_safety_multiplier(
                m.content,
                getattr(m, "metadata", {}) or {},
            )
            safe_score = min(1.0, max(0.0, safe_score))
            results.append(HowdexResult(memory=m, score=round(safe_score, 4), matched_by=matched_by))

        results.sort(key=lambda r: r.score, reverse=True)

        # touch (update access stats) for returned memories
        for r in results[:top_k]:
            self.store.touch(r.memory.id)

        return results[:top_k]

    def _recall_procedures(
        self,
        query: str,
        *,
        top_k: int,
        min_score: float,
        min_confidence: float = 0.6,
    ) -> list[HowdexResult]:
        """Conservatively retrieve a small number of credible procedures."""
        suggestions = self.suggest_procedure(
            query,
            top_k=top_k,
            min_confidence=min_confidence,
        )
        return [
            HowdexResult(
                memory=self.get_procedure(
                    suggestion.task_signature,
                    min_confidence=0.0,
                ).to_memory(),
                score=round(suggestion.score, 4),
                matched_by="procedure",
            )
            for suggestion in suggestions
            if suggestion.score >= min_score
        ]

    def search(
        self,
        query: str,
        *,
        layer: Optional[Union[str, MemoryLayer]] = None,
        top_k: int = 5,
        min_score: float = 0.1,
        hybrid: bool = True,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        include_expired: bool = False,
    ) -> list[HowdexResult]:
        """Search memories.

        This is the preferred retrieval name. ``recall()`` remains available as
        a compatibility alias and as a generic memory-retrieval verb.
        """
        return self.recall(
            query,
            layer=layer,
            top_k=top_k,
            min_score=min_score,
            hybrid=hybrid,
            agent_id=agent_id,
            session_id=session_id,
            include_expired=include_expired,
        )

    # ------------------------------------------------------------------ #
    # core: learn (consolidation)
    # ------------------------------------------------------------------ #
    def learn(self, *, min_samples: int = 3, dry_run: bool = False) -> list[Procedure]:
        """Consolidate episodic memories into procedural knowledge.

        Equivalent to ``howdex learn`` on the CLI. See
        :mod:`howdex.core.consolidation` for the algorithm.
        """
        return consolidate(self.store, min_samples=min_samples, dry_run=dry_run)

    # ------------------------------------------------------------------ #
    # forget
    # ------------------------------------------------------------------ #
    def forget(self, memory_id: str) -> None:
        """Delete a memory (soft — tombstoned for CRDT correctness)."""
        if not self.store.get(memory_id):
            raise HowdexNotFoundError(f"no memory with id={memory_id}")
        self.store.delete(memory_id)
        self.index.remove(memory_id)

    # ------------------------------------------------------------------ #
    # sessions (episodic memory helper)
    # ------------------------------------------------------------------ #
    def start_session(
        self,
        task: str,
        agent_id: Optional[str] = None,
        *,
        source: str = "agent",
        provenance: Optional[dict[str, Any]] = None,
    ) -> Episode:
        """Begin an episodic session. All ``remember()`` calls until
        :meth:`end_session` will be tagged with this session id.
        """
        if self._current_session and not self._current_session.finished_at:
            self.end_session(outcome="partial")
        import uuid
        self._current_session = Episode(
            session_id=str(uuid.uuid4()),
            agent_id=agent_id or self.agent_id or "default",
            task=task,
            source=source,
            provenance=dict(provenance or {}),
        )
        return self._current_session

    def log_step(self, action: str, observation: str, **extra: Any) -> None:
        """Record a prose step, or enrich structured fields when supplied."""
        if not self._current_session:
            raise HowdexError("no active session; call start_session() first")
        if extra.get("tool_name") and not extra.get("canonical_action"):
            structured = dict(extra)
            tool_name = str(structured.pop("tool_name"))
            arguments = structured.pop("tool_args", None)
            legacy_arguments = structured.pop("arguments", None)
            if arguments is None:
                arguments = legacy_arguments
            metadata = structured.pop("tool_metadata", None)
            legacy_metadata = structured.pop("metadata", None)
            if metadata is None:
                metadata = legacy_metadata
            self.log_tool_call(
                tool_name,
                arguments=arguments,
                observation=observation,
                metadata=metadata,
                **structured,
            )
            return
        self._current_session.add_step(action, observation, **extra)

    def log_tool_call(
        self,
        name: str,
        arguments: Optional[dict[str, Any]] = None,
        observation: str = "",
        metadata: Optional[dict[str, Any]] = None,
        derive_semantics: bool = True,
        **extra: Any,
    ) -> None:
        """Record a canonical, structured tool step in the current session."""
        canonical = canonicalize_tool_call(name, arguments, metadata)
        safe_metadata = redact_secrets(metadata or {})[0]
        fields = dict(extra)
        fields.update(
            {
                "tool_name": canonical.raw_name,
                "tool_args": canonical.raw_args,
                "tool_metadata": safe_metadata,
                "canonical_action": canonical.canonical_name,
                "target": canonical.target,
                "intent": canonical.intent,
                "side_effect_class": canonical.side_effect_class,
                "outcome": extra.get("outcome"),
                "error": extra.get("error"),
                "canonical_confidence": canonical.confidence,
                "canonical_evidence": canonical.evidence,
                "provenance": canonical.provenance,
                # Compatibility aliases for existing stored evidence/readers.
                "arguments": canonical.raw_args,
                "metadata": safe_metadata,
            }
        )
        self.log_step(canonical.raw_action, observation, **fields)
        if derive_semantics:
            self._remember_tool_semantics(
                canonical,
                outcome=extra.get("outcome"),
            )

    def _remember_tool_semantics(
        self,
        canonical,
        *,
        outcome: Optional[str] = None,
    ) -> list[Memory]:
        """Persist idempotent semantic entities derived from a typed call."""
        session_id = (
            self._current_session.session_id
            if self._current_session
            else None
        )
        stored: list[Memory] = []
        for record in derive_tool_semantics(
            canonical,
            outcome=outcome,
            session_id=session_id,
        ):
            existing = self.store.get(record.id)
            if existing is not None:
                stored.append(existing)
                continue
            content_embedding = self.embedder.embed(record.content)
            memory = Memory(
                id=record.id,
                layer=MemoryLayer.SEMANTIC,
                type=record.type,
                content=record.content,
                metadata={
                    **record.metadata,
                    "semantic_key": record.semantic_key,
                },
                embedding=content_embedding,
                relations=record.relations,
                source="structured_tool_call",
                agent_id=(
                    self._current_session.agent_id
                    if self._current_session
                    else self.agent_id
                ),
                session_id=session_id,
                importance=0.6,
                vector_clock=int(time.time() * 1000),
            )
            self.store.put(memory)
            self.index.add(memory.id, content_embedding)
            stored.append(memory)
        return stored

    def end_session(
        self,
        outcome: str = "success",
        error: Optional[str] = None,
        *,
        max_segment_steps: int = DEFAULT_MAX_SEGMENT_STEPS,
        idle_gap_s: float = DEFAULT_IDLE_GAP_S,
    ) -> Episode:
        """Close the current session and persist it as an episodic memory."""
        if not self._current_session:
            raise HowdexError("no active session")
        ep = self._current_session
        working_memories = self.store.query(
            layer=MemoryLayer.WORKING,
            session_id=ep.session_id,
            limit=10_000,
        )
        selected_working, working_context = select_working_context(
            working_memories,
            max_items=DEFAULT_WORKING_MAX_ITEMS,
            max_chars=DEFAULT_WORKING_MAX_CHARS,
        )
        ep.close(outcome, error)
        child_episodes = segment_episode(
            ep,
            max_steps=max_segment_steps,
            idle_gap_s=idle_gap_s,
        )
        if child_episodes:
            ep.provenance = {
                **ep.provenance,
                "segmented": True,
                "segment_ids": [
                    child.session_id for child in child_episodes
                ],
            }
        self.store.put_episode(ep.to_record())
        for child in child_episodes:
            self.store.put_episode(child.to_record())
        # also store as episodic memory (searchable)
        episodic_memory = ep.to_memory()
        self.remember(
            content=episodic_memory.content,
            layer=MemoryLayer.EPISODIC,
            type=MemoryType.SESSION if outcome == "success" else MemoryType.ERROR,
            metadata={
                **episodic_memory.metadata,
                "segment_ids": [
                    child.session_id for child in child_episodes
                ],
                "segment_count": len(child_episodes),
                "working_memory_ids": [
                    memory.id for memory in selected_working
                ],
                "working_memory_count": len(selected_working),
                "working_memory_context": working_context,
            },
            source=ep.source,
        )
        self._current_session = None
        return ep

    # ------------------------------------------------------------------ #
    # procedures
    # ------------------------------------------------------------------ #
    def get_procedure(
        self,
        task_signature: str,
        *,
        min_confidence: float = 0.6,
    ) -> Optional[Procedure]:
        """Retrieve a learned procedure only when it clears confidence guardrails."""
        key = " ".join(task_signature.lower().split())[:200]
        d = self.store.get_procedure(key)
        if not d:
            return None
        procedure = Procedure(**_normalise_procedure_payload(d))
        if procedure.confidence < min_confidence:
            return None
        return procedure


    def list_procedures(
        self,
        *,
        min_confidence: float = 0.6,
        limit: Optional[int] = None,
    ) -> list[Procedure]:
        procedures = [
            Procedure(**_normalise_procedure_payload(d))
            for d in self.store.all_procedures()
            if float(d.get("confidence", d.get("success_rate", 0.0)))
            >= min_confidence
        ]
        procedures.sort(
            key=lambda procedure: (
                procedure.confidence,
                procedure.support_count,
                procedure.success_rate,
                procedure.task_signature,
            ),
            reverse=True,
        )
        return procedures[:limit] if limit is not None else procedures

    def suggest_procedure(
        self,
        task: str,
        context: dict[str, Any] | str | None = None,
        top_k: int = 3,
        min_confidence: float = 0.0,
    ) -> list[ProcedureSuggestion]:
        """Suggest relevant learned procedures before an agent acts."""
        resolved_context = context
        if resolved_context is None and self._current_session is not None:
            resolved_context = self.get_working_context(
                self._current_session.session_id,
                include_provenance=False,
            )
        return suggest_procedures(
            self.list_procedures(min_confidence=0.0, limit=None),
            task,
            resolved_context,
            top_k=top_k,
            min_confidence=min_confidence,
        )

    def render_procedure_guidance(
        self,
        suggestions: ProcedureSuggestion | Iterable[ProcedureSuggestion],
        *,
        max_chars: int = 4_000,
    ) -> str:
        """Render compact procedure guidance for prompt injection."""
        return render_procedure_guidance(
            suggestions,
            max_chars=max_chars,
        )

    def export_procedures(
        self,
        output: Optional[Union[str, Path]] = None,
    ) -> dict[str, Any]:
        """Export learned procedures as portable Howdex JSON documents."""
        from howdex.portable import export_procedures

        return export_procedures(self.store, output)

    def import_procedures(self, source: Union[str, Path]) -> dict[str, int]:
        """Import portable procedure documents without duplicating tasks."""
        from howdex.portable import import_procedures

        return import_procedures(self.store, source)

    def init_codex(
        self,
        path: Optional[Union[str, Path]] = None,
    ) -> dict[str, Any]:
        """Create or reopen a local portable Howdex Codex registry."""
        from howdex.portable import init_codex

        return init_codex(path)

    def publish_codex(
        self,
        path: Optional[Union[str, Path]] = None,
    ) -> dict[str, Any]:
        """Publish learned procedures into a local Howdex Codex registry."""
        from howdex.portable import publish_codex

        return publish_codex(self.store, path)

    def pull_codex(self, path: Union[str, Path]) -> dict[str, int]:
        """Import procedures from another local Howdex Codex registry."""
        from howdex.portable import pull_codex

        return pull_codex(self.store, path)


    # ------------------------------------------------------------------ #
    # sync
    # ------------------------------------------------------------------ #
    def sync(self, peer: Optional[str] = None) -> dict[str, int]:
        """Sync with a peer.

        ``peer`` can be:

          * an HTTP URL (``http://other-host:7331``) — uses :func:`sync_with_peer`
          * a file path ending in ``.json`` — uses :func:`sync_to_file` /
            :func:`sync_from_file` (depending on existence)
          * ``None`` — uses the ``HOWDEX_SYNC_PEER`` env var
        """
        from howdex.sync import sync_with_peer, sync_to_file, sync_from_file
        peer = peer or os.environ.get("HOWDEX_SYNC_PEER")
        if not peer:
            raise HowdexError("no peer specified (set peer= or HOWDEX_SYNC_PEER env var)")
        if peer.startswith(("http://", "https://")):
            return sync_with_peer(self.store, peer)
        # file mode
        if os.path.exists(peer):
            n = sync_from_file(self.store, peer)
            return {"pulled": n, "pushed": 0}
        n = sync_to_file(self.store, peer)
        return {"pushed": n, "pulled": 0}

    # ------------------------------------------------------------------ #
    # housekeeping
    # ------------------------------------------------------------------ #
    def vacuum(self) -> int:
        """Remove expired working memories and tombstones older than 7 days.

        Returns the number of memories physically removed.
        """
        now = time.time()
        cutoff = now - 7 * 86400
        removed = 0
        with self.store.transaction() as conn:
            # expired working memory
            rows = conn.execute(
                "SELECT id FROM memories WHERE layer='working' AND ttl IS NOT NULL "
                "AND (created_at + ttl) < ?",
                (now,),
            ).fetchall()
            for r in rows:
                conn.execute("DELETE FROM memories WHERE id=?", (r["id"],))
                self.index.remove(r["id"])
                removed += 1
            # old tombstones
            rows = conn.execute(
                "SELECT id FROM memories WHERE deleted=1 AND accessed_at < ?",
                (cutoff,),
            ).fetchall()
            for r in rows:
                conn.execute("DELETE FROM memories WHERE id=?", (r["id"],))
                removed += 1
        return removed



    def remember_trusted(
        self,
        content: str,
        *,
        source: str = "agent",
        trust: str = "neutral",
        safety: str = "general",
        approval_required: bool = False,
        layer: str = "semantic",
        type: str = "fact",
        importance: float = 0.7,
        metadata: dict | None = None,
    ):
        """Remember content with first-class trust and safety metadata."""
        trust_metadata = TrustMetadata(
            source=source,
            trust=trust,
            safety=safety,
            approval_required=approval_required,
        ).to_metadata()

        merged = {}
        if metadata:
            merged.update(metadata)
        merged.update(trust_metadata)

        return self.remember(
            content,
            layer=layer,
            type=type,
            metadata=merged,
            importance=importance,
        )

    def session(self, task: str):
        """Create a context-managed Howdex session.

        Example:
            with mem.session("deploy api") as s:
                s.step("run_tests", "passed")
                s.success()
        """
        return HowdexSession(self, task)

    def procedure(self, task: str):
        """Alias for get_procedure() for a cleaner public API."""
        return self.get_procedure(task)

    def stats(self) -> dict[str, Any]:
        return self.store.stats()
