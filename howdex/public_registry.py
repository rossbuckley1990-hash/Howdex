"""Howdex public Codex registry — the network-effect starter.

A public registry of verified procedures that any Howdex user can pull
from. This is the "npm for agent procedures" primitive — the thing that
pure-play memory can't replicate because the *verification* (not the
procedure itself) is the valuable, shareable artifact.

The registry is Git-based (like npm's early days): a public repo of
verified procedure JSON files that `howdex registry pull` syncs locally.
Anyone can `howdex registry push` to contribute (subject to governance
lint passing — only verified procedures are accepted).

This module is distinct from `howdex/registry.py` (which implements the
local Codex registry protocol). This module adds the *public* pull/push
operations on top of that protocol.

Usage::

    # Pull the public registry locally
    howdex registry pull --to ~/.howdex/registry

    # List available verified procedures
    howdex registry list --from-dir ~/.howdex/registry

    # Search the registry
    howdex registry search "fix missing node module" --from-dir ~/.howdex/registry

    # Push a verified procedure to the registry (contributor flow)
    howdex registry push ./my-codex/procedures/ --to ./howdex-public-registry/

The default public registry URL is configurable via $HOWDEX_REGISTRY_URL.
"""

from __future__ import annotations

import datetime
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_REGISTRY_URL = os.environ.get(
    "HOWDEX_REGISTRY_URL",
    "https://raw.githubusercontent.com/rossbuckley1990-hash/howdex-public-registry/main",
)


def registry_pull(
    target_dir: str | Path,
    *,
    registry_url: str | None = None,
) -> dict[str, Any]:
    """Pull the public registry to a local directory.

    Downloads the registry manifest and all procedure JSON files from
    ``registry_url`` (default: the public Howdex registry) into
    ``target_dir``.

    Returns a summary dict with the count of pulled procedures.
    """
    url = registry_url or DEFAULT_REGISTRY_URL
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    manifest_url = f"{url}/manifest.json"
    try:
        with urllib.request.urlopen(manifest_url, timeout=30) as resp:
            manifest = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {
            "pulled": 0,
            "error": (
                f"failed to fetch manifest from {manifest_url}: {exc}. "
                f"The public registry may not exist yet or may be empty. "
                f"To contribute, run: howdex public-registry push ./your-codex/procedures/ "
                f"--to ./your-registry/  then point --url at your registry."
            ),
        }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    procedures_dir = target / "procedures"
    procedures_dir.mkdir(exist_ok=True)
    pulled = 0
    for entry in manifest.get("procedures", []):
        entry_id = entry.get("id", "")
        if not entry_id:
            continue
        # Try the full ID first, then fall back to the stem (strip
        # any "howdex." prefix). This makes pull resilient to
        # ID/filename mismatches in the manifest.
        candidates = [entry_id]
        if entry_id.startswith("howdex."):
            candidates.append(entry_id[7:])  # strip "howdex." prefix
        for candidate_id in candidates:
            proc_url = f"{url}/procedures/{candidate_id}.json"
            try:
                with urllib.request.urlopen(proc_url, timeout=30) as resp:
                    content = resp.read().decode("utf-8")
                (procedures_dir / f"{candidate_id}.json").write_text(content, encoding="utf-8")
                pulled += 1
                break  # success — don't try the fallback
            except Exception:
                continue
    return {
        "pulled": pulled,
        "manifest_url": manifest_url,
        "target": str(target),
    }


def registry_list(source_dir: str | Path) -> list[dict[str, Any]]:
    """List all procedures in a local registry directory."""
    source = Path(source_dir)
    procedures_dir = source / "procedures"
    if not procedures_dir.is_dir():
        return []
    results: list[dict[str, Any]] = []
    for proc_file in sorted(procedures_dir.glob("*.json")):
        try:
            entry = json.loads(proc_file.read_text(encoding="utf-8"))
            results.append({
                "id": entry.get("id", proc_file.stem),
                "title": entry.get("title", ""),
                "status": entry.get("status", ""),
                "verifier_type": entry.get("verification", {}).get("verifier_type", ""),
                "receipt_id": entry.get("verification", {}).get("receipt_id", "")[:12],
            })
        except Exception:
            continue
    return results


def registry_search(
    query: str,
    source_dir: str | Path,
    *,
    max_results: int = 10,
    semantic: bool = True,
) -> list[dict[str, Any]]:
    """Search procedures in a local registry.

    Two search modes:
    - **Keyword** (always on): matches query terms against title, tags,
      learned_facts, and id. Score = number of matching terms.
    - **Semantic** (default on, when ``semantic=True``): additionally
      computes a token-overlap similarity between the query and the
      procedure's text blob, catching cases where the query uses
      different words for the same concept (e.g., "import error" matches
      "ModuleNotFoundError" because both share "error" and the procedure
      mentions "module").

    The final score is keyword_score + semantic_score, so procedures
    that match both ways rank highest.
    """
    query_terms = {t.lower() for t in query.split() if len(t) > 2}
    if not query_terms:
        return []
    source = Path(source_dir)
    procedures_dir = source / "procedures"
    if not procedures_dir.is_dir():
        return []
    # Build query token set for semantic overlap
    query_tokens = set()
    for term in query.split():
        query_tokens.update(t.lower() for t in term.replace("-", "_").split("_") if len(t) > 2)
    scored: list[tuple[float, dict[str, Any]]] = []
    for proc_file in sorted(procedures_dir.glob("*.json")):
        try:
            entry = json.loads(proc_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        text_parts = [
            entry.get("title", ""),
            " ".join(entry.get("tags", [])),
            " ".join(entry.get("learned_facts", [])),
            entry.get("id", ""),
        ]
        blob = " ".join(text_parts).lower()
        # Keyword score: exact term matches
        keyword_score = sum(1 for term in query_terms if term in blob)
        # Semantic score: token overlap (catches synonyms)
        semantic_score = 0.0
        if semantic:
            blob_tokens = set()
            for word in blob.split():
                blob_tokens.update(t for t in word.replace("-", "_").split("_") if len(t) > 2)
            if query_tokens and blob_tokens:
                overlap = len(query_tokens & blob_tokens)
                semantic_score = overlap / max(len(query_tokens), 1) * 0.5  # weight lower than keyword
        total_score = keyword_score + semantic_score
        if total_score > 0:
            scored.append((total_score, {
                "id": entry.get("id", proc_file.stem),
                "title": entry.get("title", ""),
                "status": entry.get("status", ""),
                "score": round(total_score, 2),
                "verifier_type": entry.get("verification", {}).get("verifier_type", ""),
            }))
    scored.sort(key=lambda x: (-x[0], x[1]["title"]))
    return [item[1] for item in scored[:max_results]]


def registry_push(
    source_procedures_dir: str | Path,
    target_registry_dir: str | Path,
) -> dict[str, Any]:
    """Push verified procedures from a local Codex to a registry directory.

    Only procedures with ``status == "verified"`` are pushed — the
    registry is a curated set of proven procedures, not a dump of
    candidates. Each procedure must have receipt material (receipt_id or
    receipts array) or it is skipped.
    """
    source = Path(source_procedures_dir)
    target = Path(target_registry_dir)
    target_procedures = target / "procedures"
    target_procedures.mkdir(parents=True, exist_ok=True)
    pushed = 0
    skipped_unverified = 0
    skipped_lint = 0
    for proc_file in sorted(source.glob("*.json")):
        try:
            entry = json.loads(proc_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if entry.get("status") != "verified":
            skipped_unverified += 1
            continue
        verification = entry.get("verification", {})
        if not verification.get("receipt_id") and not verification.get("receipts"):
            skipped_lint += 1
            continue
        entry_id = entry.get("id", proc_file.stem)
        dest = target_procedures / f"{entry_id}.json"
        dest.write_text(
            json.dumps(entry, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        pushed += 1
    manifest = {
        "format": "howdex-public-registry",
        "version": "1.0.0",
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "procedure_count": pushed,
        "procedures": [
            {"id": f.stem, "title": json.loads(f.read_text()).get("title", "")}
            for f in sorted(target_procedures.glob("*.json"))
        ],
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "pushed": pushed,
        "skipped_unverified": skipped_unverified,
        "skipped_lint": skipped_lint,
        "target": str(target),
    }
