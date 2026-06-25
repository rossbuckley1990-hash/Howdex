"""LLM-assisted diagnostic capture for Howdex procedures.

Addresses issue #35: procedures capture *that* an edit happened, not
*what* was edited. The procedural knowledge that would actually transfer
(the diagnostic path) is in the source episode, not the consolidated
procedure.

This module adds an optional ``enrich_diagnostics()`` step that runs
after ``learn()`` and before ``guidance()``. An LLM provider reads the
raw episode steps and produces:

1. A **diagnostic summary** — what was investigated, what was found
2. A **fix description** — what was changed and why
3. A **transfer hint** — what a fresh agent should look for

The LLM output is explicitly marked as a proposal (not verified) — only
the receipt is proof. This preserves the BootProof trust boundary.

Usage::

    from howdex import Howdex
    from howdex.diagnostics import enrich_diagnostics, DryRunLLMProvider

    mem = Howdex(path="...", embedder="st")
    procs = mem.learn(min_samples=1)

    # Dry-run (no LLM needed — produces a template)
    enrich_diagnostics(mem, procs[0], llm_provider=DryRunLLMProvider())

    # With a real LLM
    enrich_diagnostics(mem, procs[0], llm_provider=my_provider)

    # Now guidance() includes the diagnostic summary + fix description
    g = mem.guidance("Fix a similar bug")
"""

from __future__ import annotations

import json
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from howdex import Howdex


class LLMProvider(Protocol):
    """Interface for an LLM provider that generates diagnostic summaries."""

    def complete(self, prompt: str) -> str:
        """Return the LLM's completion for the given prompt."""
        ...


class DryRunLLMProvider:
    """A deterministic dry-run provider that produces template diagnostics.

    No LLM is called — this produces a structured template from the
    procedure's steps. Useful for testing and for users who want to
    enrich diagnostics manually.
    """

    def complete(self, prompt: str) -> str:
        # Extract the procedure JSON from the prompt
        try:
            json_start = prompt.index("{")
            json_end = prompt.rindex("}") + 1
            proc_data = json.loads(prompt[json_start:json_end])
        except (ValueError, json.JSONDecodeError):
            proc_data = {}

        steps = proc_data.get("steps", [])
        task = proc_data.get("task_signature", "unknown task")

        # Build a deterministic diagnostic from the steps
        actions = [s.get("action", "?") for s in steps if isinstance(s, dict)]
        observations = [
            s.get("observation", "")[:100]
            for s in steps if isinstance(s, dict)
        ]

        diagnostic_summary = (
            f"Investigated {task} by executing: {', '.join(actions)}. "
            f"Key observations: {' | '.join(observations[:3])}"
        )
        fix_description = (
            f"Applied {len(actions)} steps to resolve {task}. "
            f"The fix involved: {', '.join(actions[-2:]) if len(actions) >= 2 else ', '.join(actions)}."
        )
        transfer_hint = (
            f"For a similar {task}, check: {', '.join(actions[:2]) if len(actions) >= 2 else actions[0] if actions else 'the error message'}. "
            f"Then apply the fix and verify with a deterministic checker."
        )

        return json.dumps({
            "diagnostic_summary": diagnostic_summary,
            "fix_description": fix_description,
            "transfer_hint": transfer_hint,
        })


def enrich_diagnostics(
    memory: "Howdex",
    procedure: Any,
    *,
    llm_provider: LLMProvider | None = None,
) -> dict[str, str]:
    """Enrich a procedure with LLM-assisted diagnostic capture.

    Adds three fields to the procedure's metadata:
    - ``diagnostic_summary`` — what was investigated and found
    - ``fix_description`` — what was changed and why
    - ``transfer_hint`` — what a fresh agent should look for

    The LLM output is explicitly marked as ``source: "llm_proposal"`` —
    it is NOT verification evidence. Only the receipt is proof.

    Args:
        memory: The Howdex instance.
        procedure: The Procedure object to enrich.
        llm_provider: An LLM provider implementing ``complete(prompt)``.
            If None, uses :class:`DryRunLLMProvider` (no LLM call).

    Returns:
        A dict with the three diagnostic fields.
    """
    provider = llm_provider or DryRunLLMProvider()

    # Build the prompt from the procedure's steps
    proc_data = {
        "task_signature": getattr(procedure, "task_signature", ""),
        "steps": [
            {
                "action": s.get("action", ""),
                "observation": s.get("observation", "")[:200],
                "canonical_name": s.get("canonical_name", ""),
            }
            for s in (getattr(procedure, "steps", []) or [])
            if isinstance(s, dict)
        ],
    }

    prompt = (
        "You are a diagnostic assistant for an AI agent's procedure. "
        "Analyze the following procedure and produce a JSON object with "
        "three fields: diagnostic_summary, fix_description, transfer_hint.\n\n"
        "Rules:\n"
        "- Do not include source code.\n"
        "- Do not claim verification — this is a proposal only.\n"
        "- Be concise (1-2 sentences per field).\n\n"
        f"Procedure:\n{json.dumps(proc_data, indent=2)}"
    )

    response = provider.complete(prompt)

    # Parse the response
    try:
        diagnostics = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        diagnostics = {
            "diagnostic_summary": f"Failed to parse LLM response for {proc_data['task_signature']}",
            "fix_description": "",
            "transfer_hint": "",
        }

    # Store the diagnostics on the procedure
    proc_id = getattr(procedure, "id", "")
    task_sig = getattr(procedure, "task_signature", "")
    if proc_id or task_sig:
        # Look up the procedure in the store and update its metadata
        proc_payload = None
        if task_sig:
            proc_payload = memory.store.get_procedure(task_sig)
        if proc_payload is None and proc_id:
            # Try finding by ID
            for payload in memory.store.all_procedures():
                if isinstance(payload, dict) and str(payload.get("id", "")) == proc_id:
                    proc_payload = payload
                    break
        if proc_payload is not None and isinstance(proc_payload, dict):
            metadata = proc_payload.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            elif isinstance(metadata, str):
                import json as _json
                try:
                    metadata = _json.loads(metadata)
                except Exception:
                    metadata = {}
            metadata["diagnostics"] = {
                **diagnostics,
                "source": "llm_proposal",
                "verified": False,
            }
            proc_payload["metadata"] = metadata
            memory.store.put_procedure(proc_payload)

    return diagnostics


def get_diagnostics(memory: "Howdex", procedure_id: str) -> dict[str, Any] | None:
    """Retrieve the diagnostic enrichment for a procedure, if present."""
    try:
        proc = memory._procedure_by_id(procedure_id)
        if proc is None:
            return None
        metadata = getattr(proc, "metadata", None) or {}
        if isinstance(metadata, dict):
            return metadata.get("diagnostics")
        return None
    except Exception:
        return None
