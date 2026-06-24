"""
Howdex — procedural memory for autonomous agents

Howdex records what agents tried, what failed, and what worked, then turns
repeated successful traces into reusable procedures.

    >>> from howdex import Howdex
    >>> memory = Howdex()              # zero-config, creates ~/.howdex
    >>> memory.remember("User prefers dark mode", layer="semantic")
    >>> memory.search("UI preferences")
    >>> memory.learn()                 # consolidate episodes → procedures

Visit https://github.com/rossbuckley1990-hash/Howdex for full docs.
"""

from howdex.abstraction import (
    AbstractionProposal,
    accept_abstraction,
    export_abstraction_audit_log,
    list_abstraction_proposals,
    propose_abstraction,
    reject_abstraction,
)
from howdex.attestation import (
    AttestationVerification,
    SignedReceiptAttestation,
    create_signed_attestation,
    verify_attestation,
)
from howdex.core.engine import Howdex
from howdex.core.errors import (
    ConsolidationError,
    HowdexError,
    HowdexNotFoundError,
    StoreError,
    SyncError,
)
from howdex.core.parallel import ParallelSpanResolver
from howdex.core.parameterize import ParameterizedAction, ParameterizedStep
from howdex.core.receipts import VerificationReceipt
from howdex.core.types import (
    Episode,
    HowdexResult,
    Memory,
    MemoryLayer,
    MemoryType,
    Procedure,
)
from howdex.ingest import IngestionPipeline, IngestionRecord
from howdex.core.agent_guidance import render_system_prompt_snippet

__version__ = "0.3.0"
__author__ = "Howdex Collective"
__license__ = "Apache-2.0"

__all__ = [
    "Howdex",
    "Memory",
    "MemoryLayer",
    "MemoryType",
    "HowdexResult",
    "Episode",
    "Procedure",
    "VerificationReceipt",
    "SignedReceiptAttestation",
    "AttestationVerification",
    "create_signed_attestation",
    "verify_attestation",
    "AbstractionProposal",
    "propose_abstraction",
    "accept_abstraction",
    "reject_abstraction",
    "list_abstraction_proposals",
    "export_abstraction_audit_log",
    "ParameterizedAction",
    "ParameterizedStep",
    "ParallelSpanResolver",
    "IngestionRecord",
    "IngestionPipeline",
    "render_system_prompt_snippet",
    "HowdexError",
    "StoreError",
    "HowdexNotFoundError",
    "ConsolidationError",
    "SyncError",
    "__version__",
]
