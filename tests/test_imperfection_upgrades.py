"""Tests for the imperfection upgrades: verified registry, semantic search, pull."""

import json
import pytest
from pathlib import Path

from howdex import Howdex, public_registry


# --------------------------------------------------------------------------- #
# Imp #1: Bundled registry procedures are all verified
# --------------------------------------------------------------------------- #
def test_bundled_registry_procedures_are_all_verified():
    """Every procedure in the bundled registry/ must have status=verified."""
    repo_root = Path(__file__).parent.parent
    registry_dir = repo_root / "registry"
    if not registry_dir.exists():
        pytest.skip("registry/ directory not found")
    procedures_dir = registry_dir / "procedures"
    proc_files = list(procedures_dir.glob("*.json"))
    assert len(proc_files) >= 4, f"expected >=4 procedures, got {len(proc_files)}"
    for proc_file in proc_files:
        entry = json.loads(proc_file.read_text())
        assert entry["status"] == "verified", (
            f"{proc_file.name} has status={entry['status']}, expected 'verified'"
        )
        # Must have receipt material
        verification = entry.get("verification", {})
        assert verification.get("receipt_id") or verification.get("receipts"), (
            f"{proc_file.name} has no receipt material"
        )


def test_bundled_registry_manifest_has_correct_count():
    """The bundled manifest should match the actual procedure count."""
    repo_root = Path(__file__).parent.parent
    manifest_path = repo_root / "registry" / "manifest.json"
    if not manifest_path.exists():
        pytest.skip("registry/manifest.json not found")
    manifest = json.loads(manifest_path.read_text())
    procedures_dir = repo_root / "registry" / "procedures"
    actual_count = len(list(procedures_dir.glob("*.json")))
    assert manifest["procedure_count"] == actual_count, (
        f"manifest says {manifest['procedure_count']}, actual is {actual_count}"
    )


# --------------------------------------------------------------------------- #
# Imp #2: Semantic search finds procedures via synonym overlap
# --------------------------------------------------------------------------- #
def test_semantic_search_finds_via_token_overlap(tmp_path):
    """Semantic search should find procedures even when the query uses
    different words for the same concept."""
    # Build a test registry with a procedure that mentions "ModuleNotFoundError"
    registry_dir = tmp_path / "registry"
    procedures_dir = registry_dir / "procedures"
    procedures_dir.mkdir(parents=True)
    proc = {
        "id": "test-module-fix",
        "title": "Fix ModuleNotFoundError on import",
        "status": "verified",
        "tags": ["module", "import", "error", "python"],
        "learned_facts": ["rename the module file"],
        "verification": {"verifier_type": "bash", "status": "verified"},
    }
    (procedures_dir / "test-module-fix.json").write_text(
        json.dumps(proc), encoding="utf-8"
    )
    # Search with "import error" — should match via token overlap
    # even though "ModuleNotFoundError" is one word
    results = public_registry.registry_search(
        "import error",
        registry_dir,
        semantic=True,
    )
    assert len(results) >= 1, "semantic search should find the procedure"
    assert results[0]["title"] == "Fix ModuleNotFoundError on import"


def test_keyword_only_search_still_works(tmp_path):
    """When semantic=False, only exact keyword matches are returned."""
    registry_dir = tmp_path / "registry"
    procedures_dir = registry_dir / "procedures"
    procedures_dir.mkdir(parents=True)
    proc = {
        "id": "test-docker",
        "title": "Recover Docker Compose service",
        "status": "verified",
        "tags": ["docker", "compose"],
        "learned_facts": [],
        "verification": {"verifier_type": "bash", "status": "verified"},
    }
    (procedures_dir / "test-docker.json").write_text(
        json.dumps(proc), encoding="utf-8"
    )
    # Keyword search for "docker" should match
    results = public_registry.registry_search(
        "docker recovery",
        registry_dir,
        semantic=False,
    )
    assert len(results) >= 1
    assert results[0]["title"] == "Recover Docker Compose service"


def test_semantic_search_ranks_keyword_matches_higher(tmp_path):
    """Procedures that match both keyword AND semantic should rank highest."""
    registry_dir = tmp_path / "registry"
    procedures_dir = registry_dir / "procedures"
    procedures_dir.mkdir(parents=True)
    # Procedure 1: exact keyword match
    proc1 = {
        "id": "exact-match",
        "title": "Fix Docker Compose health",
        "status": "verified",
        "tags": ["docker", "compose", "health"],
        "learned_facts": [],
        "verification": {"verifier_type": "bash"},
    }
    # Procedure 2: semantic-only match (different words, same concept)
    proc2 = {
        "id": "semantic-match",
        "title": "Recover container orchestration service",
        "status": "verified",
        "tags": ["container", "orchestration", "service"],
        "learned_facts": [],
        "verification": {"verifier_type": "bash"},
    }
    (procedures_dir / "exact-match.json").write_text(json.dumps(proc1))
    (procedures_dir / "semantic-match.json").write_text(json.dumps(proc2))
    results = public_registry.registry_search(
        "docker compose",
        registry_dir,
        semantic=True,
    )
    assert len(results) >= 1
    # The exact match should rank first (higher score)
    assert results[0]["id"] == "exact-match"


# --------------------------------------------------------------------------- #
# Imp #3: public-registry pull works against the real remote
# --------------------------------------------------------------------------- #
def test_public_registry_pull_returns_procedures(tmp_path):
    """Pulling the public registry should return verified procedures.

    This test hits the real howdex-public-registry GitHub repo. It may
    be slow (network) and is skipped if the network is unavailable.
    """
    import urllib.request
    # Check network availability first
    try:
        urllib.request.urlopen(
            "https://raw.githubusercontent.com/rossbuckley1990-hash/howdex-public-registry/main/manifest.json",
            timeout=10,
        )
    except Exception:
        pytest.skip("network unavailable — cannot test public-registry pull")

    result = public_registry.registry_pull(str(tmp_path / "pulled"))
    assert result["pulled"] >= 1, (
        f"expected to pull >=1 procedure from the public registry, got {result}"
    )
    # The pulled procedures should be in the target directory
    pulled_dir = tmp_path / "pulled" / "procedures"
    proc_files = list(pulled_dir.glob("*.json"))
    assert len(proc_files) >= 1
    # At least one should be verified
    for proc_file in proc_files:
        entry = json.loads(proc_file.read_text())
        if entry.get("status") == "verified":
            return  # found a verified one
    pytest.fail("no verified procedures found in pulled registry")
