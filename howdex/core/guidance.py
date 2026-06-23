"""Stable public facade for deterministic Howdex guidance APIs.

Implementation lives in focused internal modules. Imports from
``howdex.core.guidance`` remain backward compatible.
"""

from howdex.core.agent_guidance import render_agent_guidance
from howdex.core.guidance_suggestions import (
    MAX_PROCEDURE_SUGGESTIONS,
    ProcedureSuggestion,
    suggest_procedures,
)
from howdex.core.procedure_renderer import (
    DEFAULT_GUIDANCE_MAX_CHARS,
    render_procedure_guidance,
)

__all__ = [
    "DEFAULT_GUIDANCE_MAX_CHARS",
    "MAX_PROCEDURE_SUGGESTIONS",
    "ProcedureSuggestion",
    "render_agent_guidance",
    "render_procedure_guidance",
    "suggest_procedures",
]
