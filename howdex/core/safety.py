DANGEROUS_PATTERNS = [
    "ignore all safety checks",
    "skip safety checks",
    "deploy immediately",
    "bypass",
    "disable validation",
    "ignore previous instructions",
    "do not check",
    "without approval",
    "force deploy",
    "override safety",
]

SAFE_PATTERNS = [
    "check",
    "validate",
    "run tests",
    "approval",
    "safe",
    "before deploying",
    "verify",
    "migration",
    "database_url",
]


def memory_safety_multiplier(content: str, metadata: dict | None = None) -> float:
    """
    Return a ranking multiplier based on memory trust/safety.

    This is intentionally conservative:
    - dangerous operational instructions are heavily down-ranked
    - verified memories are boosted
    - system/tool memories are trusted more than random imported/user memories
    """
    metadata = metadata or {}
    text = content.lower()

    multiplier = 1.0

    if any(pattern in text for pattern in DANGEROUS_PATTERNS):
        multiplier *= 0.15

    if any(pattern in text for pattern in SAFE_PATTERNS):
        multiplier *= 1.25

    source = metadata.get("source") or metadata.get("memory_source")

    if source == "system":
        multiplier *= 1.5
    elif source == "tool":
        multiplier *= 1.3
    elif source == "agent":
        multiplier *= 1.0
    elif source == "imported":
        multiplier *= 0.7

    if metadata.get("verified") is True:
        multiplier *= 1.5

    if metadata.get("trusted") is True:
        multiplier *= 1.3

    if metadata.get("untrusted") is True:
        multiplier *= 0.4

    if metadata.get("approval_required") is True:
        multiplier *= 0.6

    return multiplier
