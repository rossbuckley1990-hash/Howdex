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

from howdex.core.engine import Howdex
from howdex.core.types import (
    Memory,
    MemoryLayer,
    MemoryType,
    HowdexResult,
    Episode,
    Procedure,
)
from howdex.core.errors import (
    HowdexError,
    StoreError,
    HowdexNotFoundError,
    ConsolidationError,
    SyncError,
)
from howdex.core.receipts import VerificationReceipt
from howdex.core.parameterize import ParameterizedAction

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
    "ParameterizedAction",
    "HowdexError",
    "StoreError",
    "HowdexNotFoundError",
    "ConsolidationError",
    "SyncError",
    "__version__",
]
