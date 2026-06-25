from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MemorySource = Literal["system", "tool", "agent", "user", "imported"]
TrustLevel = Literal["verified", "trusted", "neutral", "untrusted"]
SafetyClass = Literal["general", "operational", "security", "personal", "unknown"]


@dataclass(frozen=True)
class TrustMetadata:
    source: MemorySource = "agent"
    trust: TrustLevel = "neutral"
    safety: SafetyClass = "general"
    approval_required: bool = False

    def to_metadata(self) -> dict:
        metadata = {
            "source": self.source,
            "trust": self.trust,
            "safety": self.safety,
            "approval_required": self.approval_required,
        }

        if self.trust in {"verified", "trusted"}:
            metadata["trusted"] = True

        if self.trust == "verified":
            metadata["verified"] = True

        if self.trust == "untrusted":
            metadata["untrusted"] = True

        return metadata
