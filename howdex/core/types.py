"""Core type definitions for Howdex's memory system."""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


class MemoryLayer(str, enum.Enum):
    """The four cognitive memory layers.

    Mirrors the human cognitive science model (Atkinson-Shiffrin + Tulving),
    adapted for AI agents.

    * WORKING   — current turn / current task scratchpad; short TTL
    * SEMANTIC  — distilled facts, embeddings, knowledge graph
    * EPISODIC  — session logs, outcomes, error traces (what happened)
    * PROCEDURAL — learned workflows, decision trees (how to do things)
    """

    WORKING = "working"
    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    PROCEDURAL = "procedural"


class MemoryType(str, enum.Enum):
    """Fine-grained type tag within a layer."""

    # working
    CONTEXT = "context"
    SCRATCH = "scratch"
    # semantic
    FACT = "fact"
    PREFERENCE = "preference"
    ENTITY = "entity"
    RELATION = "relation"
    # episodic
    SESSION = "session"
    OUTCOME = "outcome"
    ERROR = "error"
    TURN = "turn"
    # procedural
    WORKFLOW = "workflow"
    PATTERN = "pattern"
    RECIPE = "recipe"


@dataclass
class Memory:
    """A single memory record — the atomic unit of Howdex.

    Memories are immutable after creation (append-only store). Updates create
    a new revision pointing at the parent via ``parent_id``.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    layer: MemoryLayer = MemoryLayer.SEMANTIC
    type: MemoryType = MemoryType.FACT
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    # vector embedding (float32, dim depends on embedder)
    embedding: Optional[list[float]] = None
    # graph edges (semantic layer)
    relations: list[dict[str, str]] = field(default_factory=list)
    # provenance
    source: str = "user"           # user | agent | system | sync
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    parent_id: Optional[str] = None
    # timing
    created_at: float = field(default_factory=time.time)
    accessed_at: float = field(default_factory=time.time)
    access_count: int = 0
    importance: float = 0.5        # 0.0 – 1.0, affects retention
    ttl: Optional[float] = None    # seconds; None = forever
    # sync
    vector_clock: int = 0          # CRDT-style logical clock

    def touch(self) -> None:
        """Mark this memory as accessed (for recency scoring & consolidation)."""
        self.accessed_at = time.time()
        self.access_count += 1

    def is_expired(self, now: Optional[float] = None) -> bool:
        if self.ttl is None:
            return False
        now = now or time.time()
        return (now - self.created_at) > self.ttl

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["layer"] = self.layer.value
        d["type"] = self.type.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Memory":
        d = dict(d)
        if isinstance(d.get("layer"), str):
            d["layer"] = MemoryLayer(d["layer"])
        if isinstance(d.get("type"), str):
            d["type"] = MemoryType(d["type"])
        return cls(**d)


@dataclass
class HowdexResult:
    """A hit returned by :meth:`Howdex.search` or :meth:`Howdex.recall`."""

    memory: Memory
    score: float                    # 0.0 – 1.0 similarity / relevance
    matched_by: str = "vector"      # vector | keyword | graph | hybrid

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory": self.memory.to_dict(),
            "score": self.score,
            "matched_by": self.matched_by,
        }


@dataclass
class Episode:
    """A unit of episodic memory — one observable agent interaction."""

    session_id: str
    agent_id: str
    task: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    outcome: Optional[str] = None       # success | failure | partial
    error: Optional[str] = None
    duration_s: float = 0.0
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    source: str = "agent"
    provenance: dict[str, Any] = field(default_factory=dict)
    parent_session_id: Optional[str] = None
    is_segment: bool = False

    def add_step(self, action: str, observation: str, **extra: Any) -> None:
        step = dict(extra)
        timestamp = float(step.pop("ts", time.time()))
        start_time = float(
            step.pop("start_time", step.pop("started_at", timestamp))
        )
        duration_s = step.get("duration_s")
        end_time = step.pop("end_time", step.pop("finished_at", None))
        if end_time is None and duration_s is not None:
            end_time = start_time + max(0.0, float(duration_s))
        self.steps.append(
            {
                "action": action,
                "observation": observation,
                "ts": timestamp,
                "start_time": start_time,
                "end_time": end_time,
                **step,
            }
        )

    def close(self, outcome: str, error: Optional[str] = None) -> None:
        self.outcome = outcome
        self.error = error
        self.finished_at = time.time()
        self.duration_s = self.finished_at - self.started_at

    def to_memory(self) -> Memory:
        """Convert into a storable episodic Memory."""
        content = (
            f"Task: {self.task}\n"
            f"Outcome: {self.outcome}\n"
            f"Duration: {self.duration_s:.2f}s\n"
            f"Steps: {len(self.steps)}\n"
        )
        if self.error:
            content += f"Error: {self.error}\n"
        content += "\n".join(
            f"  {i+1}. {s['action']} → {s['observation']}"
            for i, s in enumerate(self.steps)
        )
        return Memory(
            layer=MemoryLayer.EPISODIC,
            type=MemoryType.SESSION if self.outcome == "success" else MemoryType.ERROR,
            content=content,
            metadata={
                "session_id": self.session_id,
                "agent_id": self.agent_id,
                "task": self.task,
                "task_signature": self.task,
                "outcome": self.outcome,
                "error": self.error,
                "error_summary": self.error,
                "duration_s": self.duration_s,
                "step_count": len(self.steps),
                "start_time": self.started_at,
                "end_time": self.finished_at,
                "source": self.source,
                "provenance": self.provenance,
                "parent_session_id": self.parent_session_id,
                "is_segment": self.is_segment,
            },
            source=self.source,
            agent_id=self.agent_id,
            session_id=self.session_id,
        )

    @property
    def task_signature(self) -> str:
        return self.task

    @property
    def start_time(self) -> float:
        return self.started_at

    @property
    def end_time(self) -> Optional[float]:
        return self.finished_at

    @property
    def step_count(self) -> int:
        return len(self.steps)

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.session_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "task": self.task,
            "steps": self.steps,
            "outcome": self.outcome,
            "error": self.error,
            "duration_s": self.duration_s,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "step_count": self.step_count,
            "source": self.source,
            "provenance": self.provenance,
            "parent_session_id": self.parent_session_id,
            "is_segment": self.is_segment,
        }


@dataclass
class Procedure:
    """A learned procedure — the output of consolidation.

    Procedures are distilled from many episodes that share a task signature.
    They become the agent's "muscle memory".
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_signature: str = ""           # canonical task description
    steps: list[dict[str, Any]] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    expected_outcome: str = ""
    success_rate: float = 0.0          # 0.0 – 1.0
    sample_count: int = 0
    support_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    confidence: float = 0.0
    base_confidence: float = 0.0
    feedback_success_count: int = 0
    feedback_failure_count: int = 0
    suggestion_count: int = 0
    unverified_use_count: int = 0
    raw_supporting_examples: list[dict[str, Any]] = field(default_factory=list)
    source_episode_ids: list[str] = field(default_factory=list)
    receipts: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_used_at: Optional[float] = None
    use_count: int = 0

    def to_memory(self) -> Memory:
        action_names = [
            str(step.get("action", ""))
            for step in self.steps
            if isinstance(step, dict) and step.get("action")
        ]
        return Memory(
            layer=MemoryLayer.PROCEDURAL,
            type=MemoryType.WORKFLOW,
            content=(
                f"{self.task_signature}\n"
                f"Procedure: {' -> '.join(action_names)}"
            ),
            metadata={
                "procedure_id": self.id,
                "steps": self.steps,
                "preconditions": self.preconditions,
                "expected_outcome": self.expected_outcome,
                "success_rate": self.success_rate,
                "sample_count": self.sample_count,
                "support_count": self.support_count,
                "success_count": self.success_count,
                "failure_count": self.failure_count,
                "confidence": self.confidence,
                "base_confidence": self.base_confidence,
                "feedback_success_count": self.feedback_success_count,
                "feedback_failure_count": self.feedback_failure_count,
                "suggestion_count": self.suggestion_count,
                "unverified_use_count": self.unverified_use_count,
                "raw_supporting_examples": self.raw_supporting_examples,
                "source_episode_ids": self.source_episode_ids,
                "verification_receipts": self.receipts,
                "use_count": self.use_count,
                "last_used_at": self.last_used_at,
            },
            source="system",
            importance=max(0.7, self.success_rate, self.confidence),
        )
