"""The Howdex engine — the single entry point for agents."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

import howdex.telemetry as telemetry
from howdex.attestation import (
    ATTESTATION_INVALID,
    SignedReceiptAttestation,
    attestation_to_receipt,
    load_attestation_file,
    verify_attestation,
)
from howdex.core.consolidation import consolidate
from howdex.core.errors import HowdexError, HowdexNotFoundError
from howdex.core.guidance import (
    ProcedureSuggestion,
    render_agent_guidance,
    render_procedure_guidance,
    suggest_procedures,
)
from howdex.core.parallel import resolve_parallel_spans
from howdex.core.parameterize import redact_parameter_evidence
from howdex.core.receipts import (
    VerificationReceipt,
    parse_bootproof_attestation,
    procedure_trust_status,
    procedure_verification_status,
)
from howdex.core.retrieval import graph_neighbors, keyword_score, tokenize
from howdex.core.safety import memory_safety_multiplier
from howdex.core.segmentation import (
    DEFAULT_IDLE_GAP_S,
    DEFAULT_MAX_SEGMENT_STEPS,
    segment_episode,
)
from howdex.core.semantic import derive_tool_semantics
from howdex.core.session import HowdexSession
from howdex.core.tool_calls import canonicalize_tool_call, redact_secrets
from howdex.core.trust import TrustMetadata
from howdex.core.types import (
    Episode,
    HowdexResult,
    Memory,
    MemoryLayer,
    MemoryType,
    Procedure,
)
from howdex.core.working import (
    DEFAULT_WORKING_MAX_CHARS,
    DEFAULT_WORKING_MAX_ITEMS,
    select_working_context,
)
from howdex.ingest import (
    IngestionPipeline,
    IngestionRecord,
    Secret_Redactor,
    default_ingestion_pipeline,
)
from howdex.storage import Store
from howdex.vectors import Embedder, VectorIndex, auto_embedder

DEFAULT_HOME = Path(os.environ.get("HOWDEX_HOME", Path.home() / ".howdex"))
DEFAULT_DIM = 384
_MANDATORY_SECRET_REDACTOR = Secret_Redactor()

# Markers used by the session-integrity check (Observer Effect mitigation).
# When a step's observation contains a failure marker and end_session("success")
# is later called without an attached receipt, Howdex emits an
# "unverified_success" integrity warning so hallucinated successes are visible.
_FAILURE_MARKERS = (
    "error",
    "failed",
    "failure",
    "traceback",
    "exception",
    "fatal",
    "not found",
    "no such file",
    "no module named",
    "permission denied",
    "timed out",
    "segmentation fault",
)
_SUCCESS_MARKERS = (
    "success",
    "successful",
    "succeeded",
    "passed",
    "ok",
    "done",
    "complete",
    "exit=0",
    "exit code 0",
)

# Recognized test-runner command prefixes. For these, exit_code=0 is
# the canonical success signal — the textual summary line is sometimes
# suppressed (e.g. `pytest -q`) or localized, so we should not require
# a substring match on expected_signal.
_TEST_RUNNER_PATTERNS = (
    "pytest",
    "py.test",
    "python -m pytest",
    "python3 -m pytest",
    "jest",
    "npx jest",
    "yarn test",
    "npm test",
    "npm run test",
    "cargo test",
    "go test",
    "rspec",
    "bundle exec rspec",
    "mvn test",
    "mvn -q test",
    "gradle test",
    "./gradlew test",
    "dotnet test",
    "dotnet test",
)


def _is_test_runner_command(command: str) -> bool:
    """Return True if ``command`` invokes a recognized test runner.

    Matching is on the leading tokens of the command (after stripping
    common shell prefixes like ``source``, ``set``, env-var assignments,
    and ``bash -c`` wrappers) so that complex pipeline commands like
    ``source .venv/bin/activate && python -m pytest tests/ -q 2>&1 | tail -3``
    still match.
    """
    if not command:
        return False
    # Strip leading shell boilerplate: "source X && ", "set -o pipefail; ",
    # "VAR=val ", "bash -c '...'", etc. We're looking for the actual
    # command verb, which is the first token that isn't shell plumbing.
    text = str(command).strip()
    # Drop everything before "&&" if a test runner appears after it
    if "&&" in text:
        for segment in text.split("&&"):
            if _is_test_runner_command(segment.strip()):
                return True
    # Drop leading env-var assignments like "FOO=bar baz"
    while "=" in text.split(" ", 1)[0] and not text.startswith("python"):
        parts = text.split(" ", 1)
        if len(parts) < 2:
            break
        text = parts[1].strip()
    # Drop "source <path> && " prefix
    if text.startswith("source "):
        rest = text.split("&&", 1)
        if len(rest) == 2:
            text = rest[1].strip()
    # Drop "set -o pipefail; " and similar
    if text.startswith("set "):
        rest = text.split(";", 1)
        if len(rest) == 2:
            text = rest[1].strip()
    text = text.lstrip("(").strip()
    # Now check if any test-runner pattern is a prefix
    return any(text.startswith(p) for p in _TEST_RUNNER_PATTERNS)



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
        "parameter_bindings",
        "source_episode_ids",
        "receipts",
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


def _redact_uningested_text(content: Any, *, content_type: str) -> str:
    """Redact secrets even when advanced callers bypass other middleware."""
    baseline = str(redact_parameter_evidence(content) or "")
    return _MANDATORY_SECRET_REDACTOR.transform(
        IngestionRecord(
            source="howdex",
            content=baseline,
            content_type=content_type,
        )
    ).content


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
        path: str | Path | None = None,
        embedder: str | Embedder | None = None,
        agent_id: str | None = None,
        embed_dim: int = DEFAULT_DIM,
        ingestion_pipeline: IngestionPipeline | None = None,
        require_receipt_for_success: bool = False,
    ):
        self.path = Path(path) if path else DEFAULT_HOME / "howdex.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.agent_id = agent_id
        self.ingestion_pipeline = (
            ingestion_pipeline or default_ingestion_pipeline()
        )
        self.require_receipt_for_success = require_receipt_for_success

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
        self._current_session: Episode | None = None
        # Integrity warnings for the current session (Observer Effect mitigation).
        # Reset on each start_session(). Surfaced via integrity_warnings().
        self._session_integrity_warnings: list[dict[str, Any]] = []
        # require_receipt_for_success is already set above from the constructor
        # parameter; no need to re-initialize here.

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    def _rebuild_index(self) -> None:
        for mem in self.store.all_with_embeddings():
            if mem.embedding:
                self.index.add(mem.id, mem.embedding)

    def ledger(self) -> "MemoryLedger":
        """Return the Merkle audit ledger for this memory instance.

        The ledger is an append-only, SHA-256-chained audit trail that
        records every memory operation. It satisfies EU AI Act Article 12
        (logging), SOC 2 CC7.1 (monitoring), and CSA ATF requirements.

        The ledger is lazy-initialized on first call.
        """
        from howdex.ledger import MemoryLedger
        if not hasattr(self, "_ledger") or self._ledger is None:
            self._ledger = MemoryLedger(self)
        return self._ledger

    def close(self) -> None:
        """Persist any in-flight state and close the underlying Store.

        Safe to call multiple times. Closes the SQLite connection(s)
        opened by the Store, releasing file descriptors and WAL locks.
        Previously this only ended the active session, leaking the
        Store's connections until GC.
        """
        if self._current_session and not self._current_session.finished_at:
            try:
                self.end_session(outcome="partial")
            except Exception:
                pass
        # Close the Store's SQLite connections to prevent resource leaks.
        try:
            self.store.close()
        except Exception:
            pass

    def __enter__(self) -> Howdex:
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
        layer: str | MemoryLayer = MemoryLayer.SEMANTIC,
        type: str | MemoryType = MemoryType.FACT,
        metadata: dict[str, Any] | None = None,
        importance: float = 0.5,
        ttl: float | None = None,
        relations: list[dict[str, str]] | None = None,
        source: str = "user",
        agent_id: str | None = None,
        session_id: str | None = None,
        embed: bool = True,
        confidence: float | None = None,
        provenance: dict[str, Any] | None = None,
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
        session_id: str | None = None,
        *,
        max_items: int | None = DEFAULT_WORKING_MAX_ITEMS,
        max_chars: int | None = DEFAULT_WORKING_MAX_CHARS,
        token_budget: int | None = None,
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
        layer: str | MemoryLayer | None = None,
        top_k: int = 5,
        min_score: float = 0.1,
        hybrid: bool = True,
        agent_id: str | None = None,
        session_id: str | None = None,
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
        layer: str | MemoryLayer | None = None,
        top_k: int = 5,
        min_score: float = 0.1,
        hybrid: bool = True,
        agent_id: str | None = None,
        session_id: str | None = None,
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
    def learn(
        self,
        *,
        min_samples: int = 3,
        dry_run: bool = False,
        incremental: bool = False,
    ) -> list[Procedure]:
        """Consolidate episodic memories into procedural knowledge.

        Equivalent to ``howdex learn`` on the CLI. See
        :mod:`howdex.core.consolidation` for the algorithm.

        ``incremental`` (default False): when True, only processes episodes
        that haven't been consolidated yet. Uses a cursor in schema_meta.
        Subsequent calls with ``incremental=True`` skip already-processed
        episodes, reducing the O(N³) cost on repeated calls.

        When ``learn()`` returns an empty list, it means no procedures
        could be consolidated. Common reasons:
        - No successful episodes recorded (call ``start_session`` +
          ``log_tool_call`` + ``end_session("success")`` first)
        - Too few samples (set ``min_samples=1`` for testing)
        - Steps used prose ``log_step()`` instead of structured
          ``log_tool_call()`` — the canonicalizer needs structured
          tool calls to recognize actions
        - All episodes had ``outcome="failure"`` or ``outcome="partial"``
        """
        result = consolidate(
            self.store,
            min_samples=min_samples,
            dry_run=dry_run,
            incremental=incremental,
        )
        if not result and not dry_run:
            # Provide diagnostic feedback when learn() returns nothing
            episodes = self.store.query_episodes(limit=100)
            total = len(episodes)
            successes = sum(
                1 for ep in episodes
                if str(ep.get("outcome", "") if isinstance(ep, dict)
                      else getattr(ep, "outcome", "")).lower() == "success"
            )
            if total == 0:
                import warnings
                warnings.warn(
                    "Howdex.learn() returned 0 procedures: no episodes found. "
                    "Call start_session() → log_tool_call() → end_session('success') "
                    "before calling learn().",
                    stacklevel=2,
                )
            elif successes == 0:
                import warnings
                warnings.warn(
                    f"Howdex.learn() returned 0 procedures: found {total} episode(s) "
                    f"but 0 had outcome='success'. Procedures are only consolidated "
                    f"from successful sessions.",
                    stacklevel=2,
                )
            elif min_samples > successes:
                import warnings
                warnings.warn(
                    f"Howdex.learn() returned 0 procedures: found {successes} successful "
                    f"episode(s) but min_samples={min_samples}. Try learn(min_samples=1).",
                    stacklevel=2,
                )
        return result

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
        agent_id: str | None = None,
        *,
        source: str = "agent",
        provenance: dict[str, Any] | None = None,
    ) -> Episode:
        """Begin an episodic session. All ``remember()`` calls until
        :meth:`end_session` will be tagged with this session id.
        """
        if self._current_session and not self._current_session.finished_at:
            self.end_session(outcome="partial")
        # Reset integrity warnings for the new session.
        self._session_integrity_warnings = []
        import uuid
        self._current_session = Episode(
            session_id=str(uuid.uuid4()),
            agent_id=agent_id or self.agent_id or "default",
            task=task,
            source=source,
            provenance=dict(provenance or {}),
        )
        return self._current_session

    # ------------------------------------------------------------------ #
    # session integrity (Observer Effect mitigation)
    # ------------------------------------------------------------------ #
    def _record_integrity_warning(
        self,
        code: str,
        message: str,
    ) -> None:
        """Record a non-fatal integrity warning for the current session."""
        self._session_integrity_warnings.append(
            {"code": code, "message": message}
        )

    def _session_has_verified_receipt(self, session_id: str) -> bool:
        """Return True if any procedure linked to this session has a verified receipt.

        Used by the session-integrity check to distinguish a genuine success
        (the agent ran a verifier and attached a receipt) from a hallucinated
        one (the agent claimed success with no proof).
        """
        try:
            # Look up procedures whose source episodes include this session.
            # We check all procedures and look for one whose receipts include
            # a verified receipt whose source_episode_id matches.
            for proc_payload in self.store.all_procedures():
                proc = _normalise_procedure_payload(proc_payload)
                if proc is None:
                    continue
                source_episodes = (
                    proc.get("source_episode_ids") or []
                )
                if session_id not in source_episodes:
                    continue
                receipts = proc.get("receipts") or []
                for receipt in receipts:
                    if isinstance(receipt, dict):
                        status = str(receipt.get("status", "")).lower()
                        if status == "verified":
                            return True
            return False
        except Exception:
            # Default-safe: on storage error, assume NOT verified so the
            # integrity check fires (unverified_success warning /
            # require_receipt downgrade). The old code returned True here,
            # which suppressed hallucinated-success warnings on storage
            # errors — the opposite of safe.
            return False

    def integrity_warnings(self) -> list[dict[str, Any]]:
        """Return integrity warnings recorded for the current/last session.

        Warnings are preserved across ``end_session`` so callers can inspect
        them after the session closes. Each warning is a dict with
        ``code`` and ``message`` keys. Codes include:

        - ``malformed_arguments`` — ``log_tool_call`` got non-dict arguments
        - ``empty_tool_name`` — ``log_tool_call`` got empty/non-string name
        - ``step_observed_failure`` — a step's observation contained a
          failure marker (``error``, ``failed``, ``traceback``, ...)
        - ``unverified_success`` — ``end_session("success")`` was called
          but no verification receipt was attached and at least one step
          observed a failure. This is the canonical "hallucinated success"
          signal — the agent claimed success but Howdex has no proof.
        - ``missing_receipt_strict`` — ``end_session("success", require_receipt=True)``
          was called without a receipt; the session was downgraded to
          "unverified" instead of "success".
        """
        return list(self._session_integrity_warnings)

    def log_step(
        self,
        action: str,
        observation: str,
        *,
        sanitize: bool = True,
        **extra: Any,
    ) -> None:
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
                sanitize=sanitize,
                **structured,
            )
            return
        safe_action = _redact_uningested_text(
            action,
            content_type="action",
        )
        raw_extra = dict(extra)
        has_error = "error" in raw_extra
        raw_error = raw_extra.pop("error", None)
        safe_extra = redact_parameter_evidence(raw_extra)
        if sanitize:
            observation_record = self._ingest_session_text(
                str(observation or ""),
                source=self._current_session.source,
                content_type="observation",
                metadata={
                    "session_id": self._current_session.session_id,
                    "action": safe_action,
                },
            )
            safe_observation = observation_record.content
            safe_extra["observation_ingestion"] = (
                observation_record.audit_metadata()
            )
            if has_error and raw_error is not None:
                error_record = self._ingest_session_text(
                    str(raw_error),
                    source=self._current_session.source,
                    content_type="error",
                    metadata={
                        "session_id": self._current_session.session_id,
                        "action": safe_action,
                    },
                )
                safe_extra["error"] = error_record.content
                safe_extra["error_ingestion"] = (
                    error_record.audit_metadata()
                )
            elif has_error:
                safe_extra["error"] = None
        else:
            safe_observation = _redact_uningested_text(
                observation,
                content_type="observation",
            )
            if has_error:
                safe_extra["error"] = (
                    None
                    if raw_error is None
                    else _redact_uningested_text(
                        raw_error,
                        content_type="error",
                    )
                )
        self._current_session.add_step(
            safe_action,
            safe_observation,
            **safe_extra,
        )

    def _ingest_session_text(
        self,
        content: str,
        *,
        source: str,
        content_type: str,
        metadata: dict[str, Any],
    ) -> IngestionRecord:
        """Apply the configured pipeline plus mandatory final redaction."""
        record = self.ingestion_pipeline.ingest(
            content,
            source=source,
            content_type=content_type,
            metadata=metadata,
        )
        return _MANDATORY_SECRET_REDACTOR.transform(record)

    def log_tool_call(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        observation: str = "",
        metadata: dict[str, Any] | None = None,
        derive_semantics: bool = True,
        sanitize: bool = True,
        **extra: Any,
    ) -> None:
        """Record a canonical, structured tool step in the current session.

        Telemetry validation:
        - Emits a warning (visible via ``integrity_warnings()``) when
          ``arguments`` is not a dict (or None). Sloppy orchestrators that
          pass a string or list will not crash Howdex, but the warning
          surfaces the problem so it can be fixed at the source.
        - Emits a warning when ``observation`` contains common failure
          markers (``error``, ``failed``, ``traceback``) — this is not
          itself a problem, but ``end_session("success")`` later will
          cross-reference these warnings to catch hallucinated successes.
        """
        # Telemetry validation (Observer Effect mitigation)
        if arguments is not None and not isinstance(arguments, dict):
            self._record_integrity_warning(
                "malformed_arguments",
                f"log_tool_call({name!r}) received arguments of type "
                f"{type(arguments).__name__}, expected dict or None; "
                f"coercing to empty dict",
            )
            arguments = {}
        if not isinstance(name, str) or not name.strip():
            self._record_integrity_warning(
                "empty_tool_name",
                f"log_tool_call received empty/non-string name: {name!r}",
            )
            name = "unknown_action"
        canonical = canonicalize_tool_call(name, arguments, metadata)
        # Track failure-marker observations for session-integrity check
        obs_lower = str(observation or "").lower()
        if any(marker in obs_lower for marker in _FAILURE_MARKERS) and not any(
            marker in obs_lower for marker in _SUCCESS_MARKERS
        ):
            self._record_integrity_warning(
                "step_observed_failure",
                f"tool_call({name!r}) observation contains failure marker; "
                f"end_session('success') will be flagged if no receipt is attached",
            )
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
        self.log_step(
            canonical.raw_action,
            observation,
            sanitize=sanitize,
            **fields,
        )
        if derive_semantics:
            self._remember_tool_semantics(
                canonical,
                outcome=extra.get("outcome"),
            )

    def _remember_tool_semantics(
        self,
        canonical,
        *,
        outcome: str | None = None,
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
        error: str | None = None,
        *,
        max_segment_steps: int = DEFAULT_MAX_SEGMENT_STEPS,
        idle_gap_s: float = DEFAULT_IDLE_GAP_S,
        sanitize: bool = True,
        require_receipt: bool | None = None,
    ) -> Episode:
        """Close the current session and persist it as an episodic memory.

        Session integrity check (Observer Effect mitigation):
        - If ``outcome == "success"`` and at least one step's observation
          contained a failure marker (``error``, ``failed``, ``traceback``,
          ...) and no verification receipt has been attached to a procedure
          learned from this session, an ``unverified_success`` integrity
          warning is recorded. This surfaces "hallucinated success" — the
          agent claimed success but Howdex has no proof.
        - If ``require_receipt`` is True (or ``self.require_receipt_for_success``
          is True) and the above condition holds, the session outcome is
          downgraded from ``"success"`` to ``"unverified"`` and a
          ``missing_receipt_strict`` warning is recorded. The session is
          still persisted; the downgrade prevents ``learn()`` from
          consolidating an unverified trace into a procedure.
        """
        if not self._current_session:
            raise HowdexError("no active session")
        ep = self._current_session

        # Session integrity check (Verifier Requirement mitigation)
        if outcome == "success":
            strict = (
                require_receipt
                if require_receipt is not None
                else self.require_receipt_for_success
            )
            saw_failure = any(
                w["code"] == "step_observed_failure"
                for w in self._session_integrity_warnings
            )
            if saw_failure:
                # Check whether any procedure learned from this session
                # has a verified receipt attached.
                has_receipt = self._session_has_verified_receipt(ep.session_id)
                if not has_receipt:
                    self._record_integrity_warning(
                        "unverified_success",
                        f"end_session('success') called but session {ep.session_id[:8]} "
                        f"had failure-marker observations and no verified receipt; "
                        f"the agent may have hallucinated success",
                    )
                    if strict:
                        self._record_integrity_warning(
                            "missing_receipt_strict",
                            "require_receipt=True: downgrading outcome from "
                            "'success' to 'unverified'",
                        )
                        outcome = "unverified"

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
        safe_error = error
        if error is not None:
            if sanitize:
                error_record = self._ingest_session_text(
                    str(error),
                    source=ep.source,
                    content_type="error",
                    metadata={"session_id": ep.session_id},
                )
                safe_error = error_record.content
                ep.provenance = {
                    **ep.provenance,
                    "error_ingestion": error_record.audit_metadata(),
                }
            else:
                safe_error = _redact_uningested_text(
                    error,
                    content_type="error",
                )
        ep.close(outcome, safe_error)
        ep.steps = resolve_parallel_spans(
            ep.steps,
            episode_id=ep.session_id,
        )
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
        if outcome in {"success", "failure"}:
            for procedure_id in self.store.pending_procedure_uses(
                ep.session_id
            ):
                self.store.record_procedure_outcome(
                    procedure_id,
                    ep.session_id,
                    outcome,
                    now=ep.finished_at,
                )
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
    ) -> Procedure | None:
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
        limit: int | None = None,
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
        suggestions = suggest_procedures(
            self.list_procedures(min_confidence=0.0, limit=None),
            task,
            resolved_context,
            top_k=top_k,
            min_confidence=min_confidence,
        )

        if self._current_session is not None:
            for suggestion in suggestions:
                self.mark_procedure_suggested(
                    suggestion.procedure_id,
                    self._current_session.session_id,
                )
                self.mark_procedure_used(
                    suggestion.procedure_id,
                    self._current_session.session_id,
                )

        return suggestions

    def guidance(
        self,
        objective: str,
        *,
        query: str | None = None,
        top_k: int = 3,
        min_confidence: float = 0.0,
        constraints: list[str] | None = None,
        target_environment: str | None = None,
        current_environment: dict[str, object] | str | None = None,
        include_source: bool = False,
        include_failed_attempts: bool = True,
        include_verification: bool = True,
        max_chars: int = 6_000,
        max_procedures: int | None = None,
        min_relevance_score: float = 0.0,
        verified_only: bool = False,
        registry_dir: str | Path | None = None,
    ) -> str:
        """Retrieve relevant procedures and render agent-ready guidance.

        Context window management:
        - ``max_chars`` is a hard cap — the rendered guidance will never
          exceed this many characters (truncated with a marker if needed).
        - ``max_procedures`` (default: ``top_k``) limits the number of
          procedures injected. When the budget is tight, fewer procedures
          are included rather than truncating mid-procedure.
        - ``min_relevance_score`` filters out low-relevance procedures
          before selection. Default 0.0 (include all retrieved); raise to
          0.05–0.2 for stricter filtering on large Codex sets.
        - ``verified_only`` skips candidate (unverified) procedures —
          useful for production agents that should only act on proven
          procedures.

        Registry consultation (the network effect):
        - ``registry_dir`` — when set, Howdex also searches the local
          public registry at this path and includes matching verified
          procedures in the guidance. This is the "consult the registry
          first" behavior that makes the network effect work: an agent
          with no local memory can still get guidance from procedures
          other teams have verified and shared.
        - When local memory is empty AND no registry_dir is provided,
          the guidance tells the agent to ``howdex public-registry pull``
          before starting cold.

        Adaptive filtering: when ``max_chars`` is small (≤ 2000), Howdex
        automatically prefers verified procedures and raises the effective
        ``min_relevance_score`` to 0.15 to avoid wasting the budget on
        weak matches. This prevents context collapse on smaller models
        (e.g. gpt-4o-mini).

        See :meth:`guidance_budget_report` for an inspectable breakdown of
        how the budget was allocated.
        """
        with telemetry.span(
            "howdex.guidance.retrieve",
            {
                "howdex.include_source": include_source,
                "howdex.verified_only": verified_only,
            },
        ) as retrieve_span:
            suggestions = self.suggest_procedure(
                objective if query is None else query,
                top_k=top_k,
                min_confidence=min_confidence,
            )
            telemetry.set_attribute(
                retrieve_span,
                "howdex.selected_count",
                len(suggestions),
            )
        # Build a retrieval budget for adaptive filtering.
        from howdex.core.guidance_budget import GuidanceBudget
        # When max_chars is small, automatically tighten the budget to
        # avoid wasting the small context window on weak matches.
        if max_chars <= 2000:
            effective_min_relevance = max(min_relevance_score, 0.15)
            effective_verified_only = True
        else:
            effective_min_relevance = min_relevance_score
            effective_verified_only = verified_only
        budget = GuidanceBudget(
            max_procedures=max_procedures if max_procedures is not None else top_k,
            max_guidance_chars=max_chars,
            min_relevance_score=effective_min_relevance,
            include_verified_only=effective_verified_only,
            current_environment=current_environment,
        )
        # Registry consultation: when registry_dir is provided, search the
        # local public registry and merge matching verified procedures into
        # the suggestions. This is the "consult the registry first" behavior
        # that makes the network effect work.
        if registry_dir is not None:
            from howdex.public_registry import registry_search
            registry_hits = registry_search(
                objective,
                registry_dir,
                max_results=top_k,
            )
            if registry_hits:
                # Convert registry hits to suggestion-like dicts so they
                # flow through the same rendering pipeline
                for hit in registry_hits:
                    suggestions.append(type("RegHit", (), {
                        "procedure_id": hit.get("id", ""),
                        "task_signature": hit.get("title", ""),
                        "confidence": 0.9,
                        "support_count": 1,
                        "steps": [],
                        "score": hit.get("score", 0),
                        "receipts": [],
                    })())
        return render_agent_guidance(
            suggestions,
            objective=objective,
            constraints=constraints,
            target_environment=target_environment,
            current_environment=current_environment,
            include_source=include_source,
            include_failed_attempts=include_failed_attempts,
            include_verification=include_verification,
            max_chars=max_chars,
            retrieval_budget=budget,
        )

    def guidance_budget_report(
        self,
        objective: str,
        *,
        max_chars: int = 6_000,
        max_procedures: int | None = None,
        min_relevance_score: float = 0.05,
        verified_only: bool = False,
    ) -> dict[str, Any]:
        """Return an inspectable breakdown of how the guidance budget is allocated.

        Use this to monitor context-window pressure before injecting
        guidance into a smaller model. Returns a dict with:

        - ``total_candidates`` — how many procedures matched the query
        - ``selected_count`` — how many were selected after budgeting
        - ``omitted_count`` — how many were dropped
        - ``estimated_chars`` — estimated rendered size
        - ``max_chars`` — the budget cap
        - ``context_pressure`` — ``"low"`` / ``"medium"`` / ``"high"``
        - ``omitted`` — list of dicts with procedure_id, reason, relevance_score
        """
        from howdex.core.guidance_budget import (
            GuidanceBudget,
            select_guidance_procedures,
        )
        suggestions = self.suggest_procedure(objective, top_k=20)
        budget = GuidanceBudget(
            max_procedures=max_procedures if max_procedures is not None else 3,
            max_guidance_chars=max_chars,
            min_relevance_score=min_relevance_score,
            include_verified_only=verified_only,
        )
        selection = select_guidance_procedures(objective, suggestions, budget)
        estimated = sum(getattr(d, "estimated_chars", 0) for d in selection.selected)
        pressure = "low"
        if estimated > max_chars * 0.7:
            pressure = "medium"
        if estimated > max_chars * 0.9:
            pressure = "high"
        return {
            "total_candidates": len(suggestions),
            "selected_count": len(selection.selected),
            "omitted_count": selection.omitted_count,
            "estimated_chars": estimated,
            "max_chars": max_chars,
            "context_pressure": pressure,
            "omitted": [
                {
                    "procedure_id": d.procedure_id,
                    "title": d.title,
                    "reason": d.reason,
                    "relevance_score": d.relevance_score,
                    "status": d.status,
                    "staleness_status": d.staleness_status,
                }
                for d in (selection.excluded or [])
            ],
        }

    def detect_canonicalization_drift(
        self,
        *,
        min_confidence: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Detect procedures whose steps have low canonical confidence.

        This surfaces the brittleness risk described in the architectural
        review: when an agent changes how it formats JSON arguments between
        runs, the canonicalizer may fail to recognize semantic equivalence,
        producing steps with low ``canonical_confidence``. Such procedures
        are candidates for an LLM-assisted abstraction proposal
        (``propose_abstraction()``) to bridge the format gap.

        Returns a list of dicts, one per at-risk procedure, each with:
        - ``procedure_id`` — the procedure's id
        - ``task_signature`` — what the procedure does
        - ``at_risk_steps`` — count of steps with confidence < min_confidence
        - ``total_steps`` — total steps in the procedure
        - ``min_confidence`` — the lowest confidence across all steps
        - ``suggestion`` — a human-readable recommendation

        Call ``propose_abstraction([procedure, ...])`` on the returned
        procedures to generate an auditable equivalence proposal.
        """
        at_risk: list[dict[str, Any]] = []
        for proc_payload in self.store.all_procedures():
            proc = _normalise_procedure_payload(proc_payload)
            if proc is None:
                continue
            steps = proc.get("steps") or []
            if not steps:
                continue
            at_risk_count = 0
            min_conf = 1.0
            for step in steps:
                if not isinstance(step, dict):
                    continue
                conf = float(step.get("canonical_confidence", 1.0) or 1.0)
                min_conf = min(min_conf, conf)
                if conf < min_confidence:
                    at_risk_count += 1
            if at_risk_count > 0:
                at_risk.append({
                    "procedure_id": str(proc.get("id", "")),
                    "task_signature": str(proc.get("task_signature", "")),
                    "at_risk_steps": at_risk_count,
                    "total_steps": len(steps),
                    "min_confidence": round(min_conf, 3),
                    "suggestion": (
                        f"{at_risk_count}/{len(steps)} steps have canonical "
                        f"confidence < {min_confidence}. Consider calling "
                        f"propose_abstraction() to bridge format divergence."
                    ),
                })
        at_risk.sort(key=lambda d: d["min_confidence"])
        return at_risk

    # ------------------------------------------------------------------ #
    # trust calibration (Day-2 risk: context window sizing)
    # ------------------------------------------------------------------ #
    def trust_calibration_curve(self) -> dict[str, Any]:
        """Return the verified-vs-candidate distribution across all procedures.

        Addresses the Day-2 risk: "If the HNSW vector index retrieves 10
        slightly overlapping procedures for a single task, injecting all
        of them will cause severe 'Needle in a Haystack' context collapse
        for smaller models like Llama-3."

        The trust calibration curve tells you how many of your procedures
        are verified (independently proven) vs. candidate (observed only).
        Use it to decide:

        - If most procedures are candidates, raise ``min_relevance_score``
          and set ``verified_only=True`` in ``guidance()`` to avoid
          injecting unproven noise.
        - If most procedures are verified, you can afford a larger
          ``top_k`` because each injected procedure has proof.

        Returns a dict with:
        - ``total_procedures`` — count of all learned procedures
        - ``verified`` — count with at least one verified receipt
        - ``candidate`` — count with no verified receipt
        - ``failed`` — count with a failed receipt
        - ``verified_ratio`` — verified / total (0.0–1.0)
        - ``recommended_top_k`` — suggested top_k for guidance() based on
          the trust distribution (1 if ratio < 0.3, 2 if < 0.6, else 3)
        - ``recommended_verified_only`` — True if ratio < 0.3
        """
        total = 0
        verified = 0
        candidate = 0
        failed = 0
        for proc_payload in self.store.all_procedures():
            proc = _normalise_procedure_payload(proc_payload)
            if proc is None:
                continue
            total += 1
            receipts = proc.get("receipts") or []
            has_verified = False
            has_failed = False
            for receipt in receipts:
                if not isinstance(receipt, dict):
                    continue
                status = str(receipt.get("status", "")).lower()
                if status == "verified":
                    has_verified = True
                elif status == "failed":
                    has_failed = True
            if has_failed:
                # A failed receipt takes precedence over a verified one,
                # matching procedure_verification_status in receipts.py.
                # Previously this was checked AFTER has_verified, which
                # inflated the trust ratio and recommended unsafe
                # verified_only=False settings.
                failed += 1
            elif has_verified:
                verified += 1
            else:
                candidate += 1
        ratio = (verified / total) if total > 0 else 0.0
        if ratio < 0.3:
            recommended_top_k = 1
            recommended_verified_only = True
        elif ratio < 0.6:
            recommended_top_k = 2
            recommended_verified_only = False
        else:
            recommended_top_k = 3
            recommended_verified_only = False
        return {
            "total_procedures": total,
            "verified": verified,
            "candidate": candidate,
            "failed": failed,
            "verified_ratio": round(ratio, 3),
            "recommended_top_k": recommended_top_k,
            "recommended_verified_only": recommended_verified_only,
        }

    def needle_in_haystack_risk(
        self,
        objective: str,
        *,
        top_k: int = 5,
        max_chars: int = 6_000,
    ) -> dict[str, Any]:
        """Assess the risk of context collapse for a given objective.

        Returns a dict with:
        - ``risk_level`` — "low" / "medium" / "high"
        - ``retrieved_count`` — how many procedures matched
        - ``overlapping_count`` — how many share >50% of canonical steps
          with another retrieved procedure (the "haystack" problem)
        - ``estimated_chars`` — estimated rendered size of all retrieved
        - ``max_chars`` — the budget cap
        - ``recommendation`` — a human-readable suggestion

        A "high" risk means: too many overlapping procedures will be
        injected, causing the LLM to lose the needle. Mitigate by
        lowering ``top_k``, raising ``min_relevance_score``, or setting
        ``verified_only=True``.
        """
        suggestions = self.suggest_procedure(objective, top_k=top_k)
        retrieved_count = len(suggestions)
        # Detect overlap: procedures sharing >50% of canonical step names
        step_sets: list[set[str]] = []
        for s in suggestions:
            steps = set()
            # Handle both dict-like and object-like suggestions
            s_steps = getattr(s, "steps", None)
            if s_steps is None and isinstance(s, dict):
                s_steps = s.get("steps") or []
            for step in (s_steps or []):
                if isinstance(step, dict):
                    # Use canonical_name (the canonicalized action) not
                    # canonical_action (which doesn't exist on stored steps).
                    # The old code always fell back to raw 'action' text,
                    # defeating the canonical overlap detection.
                    cn = step.get("canonical_name") or step.get("action") or ""
                    if cn:
                        steps.add(str(cn))
            step_sets.append(steps)
        overlapping = 0
        for i, s1 in enumerate(step_sets):
            for j, s2 in enumerate(step_sets):
                if i >= j:
                    continue
                if not s1 or not s2:
                    continue
                overlap = len(s1 & s2) / max(len(s1 | s2), 1)
                if overlap > 0.5:
                    overlapping += 1
                    break
        # Rough char estimate: ~500 chars per procedure
        estimated_chars = retrieved_count * 500
        if estimated_chars > max_chars * 0.9 or overlapping > 2:
            risk = "high"
        elif estimated_chars > max_chars * 0.7 or overlapping > 0:
            risk = "medium"
        else:
            risk = "low"
        recs = {
            "high": (
                "High needle-in-haystack risk. Lower top_k to 1-2, raise "
                "min_relevance_score to 0.15+, and consider verified_only=True."
            ),
            "medium": (
                "Medium risk. Consider lowering top_k or raising min_relevance_score."
            ),
            "low": (
                "Low risk. Current retrieval settings should not cause context collapse."
            ),
        }
        return {
            "risk_level": risk,
            "retrieved_count": retrieved_count,
            "overlapping_count": overlapping,
            "estimated_chars": estimated_chars,
            "max_chars": max_chars,
            "recommendation": recs[risk],
        }

    def mark_procedure_suggested(
        self,
        procedure_id: str,
        session_id: str,
    ) -> Procedure:
        """Record that guidance was surfaced without claiming it was used."""
        self._require_procedure_id(procedure_id)
        self.store.mark_procedure_suggested(procedure_id, session_id)
        return self._procedure_by_id(procedure_id)

    def mark_procedure_used(
        self,
        procedure_id: str,
        session_id: str,
    ) -> Procedure:
        """Record a pending, not-yet-verified procedure use."""
        self._require_procedure_id(procedure_id)
        self.store.mark_procedure_used(procedure_id, session_id)
        return self._procedure_by_id(procedure_id)

    def record_procedure_outcome(
        self,
        procedure_id: str,
        episode_id: str,
        outcome: str,
    ) -> Procedure:
        """Attach one verified success/failure outcome to a procedure use."""
        self._require_procedure_id(procedure_id)
        self.store.record_procedure_outcome(
            procedure_id,
            episode_id,
            outcome,
        )
        return self._procedure_by_id(procedure_id)

    def attach_receipt(
        self,
        procedure_id: str,
        receipt: VerificationReceipt | dict[str, Any],
    ) -> VerificationReceipt:
        """Attach a generic verification receipt idempotently."""
        self._require_procedure_id(procedure_id)
        normalized = (
            receipt
            if isinstance(receipt, VerificationReceipt)
            else VerificationReceipt.from_dict(receipt)
        )
        procedure = self._procedure_by_id(procedure_id)
        if (
            normalized.procedure_id
            and normalized.procedure_id != procedure_id
        ):
            raise ValueError(
                "verification receipt procedure_id does not match "
                f"{procedure_id!r}"
            )
        if (
            normalized.task_signature
            and normalized.task_signature != procedure.task_signature
        ):
            raise ValueError(
                "verification receipt task_signature does not match "
                f"{procedure.task_signature!r}"
            )
        normalized = replace(
            normalized,
            procedure_id=procedure_id,
            task_signature=procedure.task_signature,
        )
        with telemetry.span(
            "howdex.receipt.attach",
            {
                "howdex.procedure_id": procedure_id,
                "howdex.receipt_status": normalized.status,
                "howdex.source_episode_count": 1
                if normalized.source_episode_id
                else 0,
            },
        ):
            self.store.attach_receipt(
                procedure_id,
                str(normalized.receipt_id),
                normalized.to_dict(),
            )
        return normalized

    def verify_procedure(
        self,
        procedure_id: str,
        *,
        verifier_type: str,
        verifier_command: str,
        expected_signal: str,
        observed_signal: str,
        exit_code: int,
        status: str | None = None,
        verified_at: float | str | None = None,
        environment_fingerprint: dict[str, Any] | None = None,
        artifact_hashes: dict[str, Any] | None = None,
        source_episode_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationReceipt:
        """Create and attach deterministic independent verification evidence.

        When ``status`` is omitted, verification succeeds when the verifier
        exits with code zero AND one of the following holds:

        - the expected signal is present in the observed signal (substring
          match, case-insensitive); OR
        - the verifier command is recognized as a standard test runner
          (pytest, jest, cargo test, go test, rspec, npm test, mvn test,
          gradle test, dotnet test) and ``exit_code == 0``. For these
          tools, exit code zero is the canonical success signal and the
          textual summary line is sometimes suppressed (e.g. ``pytest -q``
          ends with ``[100%]`` and never prints "passed"), so requiring
          a substring match would falsely reject real successes.

        Callers can explicitly attach ``stale`` or ``unknown`` evidence
        when no fresh verifier result exists.
        """
        resolved_status = status
        signal_matches = (
            str(expected_signal).casefold()
            in str(observed_signal).casefold()
        )
        exit_zero = int(exit_code) == 0
        # Standard test runners where exit_code=0 is sufficient evidence
        # of success even if the textual summary line is suppressed.
        test_runner_success = (
            exit_zero and _is_test_runner_command(verifier_command)
        )
        if resolved_status is None:
            resolved_status = (
                "verified"
                if (exit_zero and (signal_matches or test_runner_success))
                else "failed"
            )
        elif (
            str(resolved_status).strip().lower() in {"verified", "pass"}
            and (
                not exit_zero
                or (
                    not signal_matches
                    and not test_runner_success
                )
            )
        ):
            raise ValueError(
                "verified procedure receipt requires exit_code=0 and "
                "the expected signal in observed_signal (or a recognized "
                "test runner with exit_code=0)"
            )
        return self.attach_receipt(
            procedure_id,
            VerificationReceipt(
                verifier_type=verifier_type,
                verifier_command=verifier_command,
                expected_signal=expected_signal,
                observed_signal=observed_signal,
                exit_code=exit_code,
                verified_at=verified_at,
                environment_fingerprint=dict(
                    environment_fingerprint or {}
                ),
                artifact_hashes=dict(artifact_hashes or {}),
                source_episode_id=source_episode_id,
                status=resolved_status,
                metadata=dict(metadata or {}),
            ),
        )

    def list_receipts(self, procedure_id: str) -> list[VerificationReceipt]:
        """List generic verification receipts attached to a procedure."""
        self._require_procedure_id(procedure_id)
        return [
            VerificationReceipt.from_dict(payload)
            for payload in self.store.list_receipts(procedure_id)
        ]

    def import_bootproof_attestation(
        self,
        procedure_id: str,
        path: str | Path = ".bootproof/attestation.json",
    ) -> VerificationReceipt | None:
        """Attach a BootProof-like attestation when the optional file exists."""
        self._require_procedure_id(procedure_id)
        receipt = parse_bootproof_attestation(path)
        if receipt is not None:
            self.attach_receipt(procedure_id, receipt)
        return receipt

    def verify_receipt_file(
        self,
        path: str | Path,
        *,
        key_material: str | bytes | None = None,
    ):
        """Verify a Howdex or BootProof-like signed attestation file."""
        attestation = load_attestation_file(path)
        return verify_attestation(attestation, key_material=key_material)

    def import_signed_attestation(
        self,
        path: str | Path,
        *,
        procedure_id: str | None = None,
        key_material: str | bytes | None = None,
    ) -> VerificationReceipt:
        """Import signed or unsigned attestation evidence as a receipt.

        Signed attestations are marked as signed verified only when the
        payload hash and signature validate against supplied key material.
        Unsigned evidence remains attachable as observed evidence, but it is
        labelled separately in receipt metadata and never counts as a signed
        attestation.
        """
        attestation = load_attestation_file(path)
        target_procedure_id = procedure_id or attestation.procedure_id
        if not target_procedure_id:
            raise ValueError("attestation import requires procedure_id")
        if (
            procedure_id
            and attestation.procedure_id
            and attestation.procedure_id != procedure_id
        ):
            raise ValueError(
                "attestation procedure_id does not match "
                f"{procedure_id!r}"
            )
        if attestation.procedure_id != target_procedure_id:
            attestation = SignedReceiptAttestation(
                **{
                    **attestation.to_dict(),
                    "procedure_id": target_procedure_id,
                }
            )
        verification = verify_attestation(attestation, key_material=key_material)
        if verification.status == ATTESTATION_INVALID:
            raise ValueError(
                "signed attestation did not validate: "
                + "; ".join(verification.reasons)
            )
        return self.attach_receipt(
            target_procedure_id,
            attestation_to_receipt(attestation, verification),
        )

    def procedure_verification_status(self, procedure_id: str) -> str:
        """Return the receipt-backed verification state for one procedure."""
        return procedure_verification_status(self.list_receipts(procedure_id))

    def procedure_status(self, procedure_id: str) -> str:
        """Return the conservative trust status for one learned procedure."""
        return procedure_trust_status(
            self._procedure_by_id(procedure_id)
        )

    def _require_procedure_id(self, procedure_id: str) -> None:
        if self.store.get_procedure_by_id(procedure_id) is None:
            raise HowdexNotFoundError(f"no procedure with id={procedure_id}")

    def _procedure_by_id(self, procedure_id: str) -> Procedure:
        payload = self.store.get_procedure_by_id(procedure_id)
        if payload is None:
            raise HowdexNotFoundError(f"no procedure with id={procedure_id}")
        return Procedure(**_normalise_procedure_payload(payload))

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
        output: str | Path | None = None,
    ) -> dict[str, Any]:
        """Export learned procedures as portable Howdex JSON documents."""
        from howdex.portable import export_procedures

        return export_procedures(self.store, output)

    def import_procedures(self, source: str | Path) -> dict[str, int]:
        """Import portable procedure documents without duplicating tasks."""
        from howdex.portable import import_procedures

        return import_procedures(self.store, source)

    def init_codex(
        self,
        path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Create or reopen a local portable Howdex Codex registry."""
        from howdex.portable import init_codex

        return init_codex(path)

    def publish_codex(
        self,
        path: str | Path | None = None,
        *,
        require_signed_receipt: bool = False,
    ) -> dict[str, Any]:
        """Publish learned procedures into a local Howdex Codex registry."""
        from howdex.portable import publish_codex

        return publish_codex(
            self.store,
            path,
            require_signed_receipt=require_signed_receipt,
        )

    def pull_codex(self, path: str | Path) -> dict[str, int]:
        """Import procedures from another local Howdex Codex registry."""
        from howdex.portable import pull_codex

        return pull_codex(self.store, path)


    # ------------------------------------------------------------------ #
    # sync
    # ------------------------------------------------------------------ #
    def sync(self, peer: str | None = None) -> dict[str, int]:
        """Sync with a peer.

        ``peer`` can be:

          * an HTTP URL (``http://other-host:7331``) — uses :func:`sync_with_peer`
          * a file path ending in ``.json`` — uses :func:`sync_to_file` /
            :func:`sync_from_file` (depending on existence)
          * ``None`` — uses the ``HOWDEX_SYNC_PEER`` env var
        """
        from howdex.sync import sync_from_file, sync_to_file, sync_with_peer
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
