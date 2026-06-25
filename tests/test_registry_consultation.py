"""Tests for the registry-consultation-first behavior (the network effect)."""

import json
from pathlib import Path

import pytest

from howdex import Howdex, public_registry


def test_empty_memory_guidance_mentions_registry(tmp_path):
    """When local memory is empty, guidance should tell the agent to
    consult the public registry."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        guidance = mem.guidance("Fix a Docker container that won't start", max_chars=4000)
        assert "public registry" in guidance.lower(), (
            "guidance with empty memory should mention the public registry"
        )
        assert "search" in guidance.lower(), (
            "guidance should tell the agent to search the registry"
        )
    finally:
        mem.close()


def test_empty_memory_guidance_no_registry_tip_for_small_budget(tmp_path):
    """When max_chars is ≤1000, the registry tip should be omitted
    to avoid truncating later sections."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        # Use 1000 chars — above the base guidance size, below the
        # registry-tip threshold (max_chars > 1000)
        guidance = mem.guidance("Fix a bug", max_chars=1000)
        # The registry tip should NOT appear (max_chars ≤ 1000)
        assert "public registry" not in guidance.lower(), (
            "registry tip should be omitted when max_chars ≤ 1000"
        )
        # But the core sections should be present
        assert "HOWDEX OPERATIONAL MEMORY" in guidance
    finally:
        mem.close()


def test_guidance_with_registry_dir_merges_hits(tmp_path):
    """When registry_dir is provided, guidance should include matching
    procedures from the registry."""
    # Build a minimal registry
    registry_dir = tmp_path / "registry"
    procedures_dir = registry_dir / "procedures"
    procedures_dir.mkdir(parents=True)
    proc = {
        "id": "test-docker-recovery",
        "title": "Recover Docker Compose service health",
        "status": "verified",
        "tags": ["docker", "compose", "health", "recovery"],
        "learned_facts": ["inspect the Docker Compose service configuration"],
        "verification": {
            "verifier_type": "bash",
            "verifier_command": "docker compose ps | grep -q 'healthy'",
            "status": "verified",
            "receipt_id": "abc123",
        },
    }
    (procedures_dir / "test-docker-recovery.json").write_text(
        json.dumps(proc), encoding="utf-8"
    )
    # Create a manifest
    manifest = {
        "format": "howdex-public-registry",
        "version": "1.0.0",
        "procedures": [{"id": "test-docker-recovery", "title": proc["title"]}],
    }
    (registry_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    # Agent with empty local memory but registry access
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        guidance = mem.guidance(
            "Fix a Docker Compose service that won't start",
            max_chars=4000,
            registry_dir=str(registry_dir),
        )
        # The Docker procedure from the registry should appear
        assert "Docker" in guidance or "docker" in guidance, (
            "guidance should include the Docker procedure from the registry"
        )
    finally:
        mem.close()


def test_registry_search_finds_bundled_procedures():
    """The bundled registry in the repo should be searchable."""
    import os
    repo_root = Path(__file__).parent.parent
    registry_dir = repo_root / "registry"
    if not registry_dir.exists():
        pytest.skip("registry/ directory not found in repo root")
    results = public_registry.registry_search(
        "docker compose health recovery",
        registry_dir,
    )
    assert len(results) >= 1, "expected at least 1 Docker-related procedure in the bundled registry"
    # The Docker Compose health recovery procedure should be found
    titles = [r["title"].lower() for r in results]
    assert any("docker" in t for t in titles), (
        f"expected a Docker-related procedure, got: {titles}"
    )
