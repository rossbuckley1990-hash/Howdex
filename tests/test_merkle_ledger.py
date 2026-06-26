"""Tests for the Merkle audit ledger — chain integrity, tamper detection, export."""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from howdex import Howdex, MemoryLedger


def _seed_ledger(mem, n=5):
    """Seed a Howdex instance with n ledger entries."""
    ledger = mem.ledger()
    for i in range(n):
        ledger.append("log_tool_call", {
            "tool": "execute_bash",
            "cmd": f"echo {i}",
            "observation": f"output {i}",
        })
    return ledger


# --------------------------------------------------------------------------- #
# Chain integrity
# --------------------------------------------------------------------------- #
def test_ledger_empty_chain_verifies(tmp_path):
    """An empty ledger should verify as valid."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        ledger = mem.ledger()
        valid, error = ledger.verify()
        assert valid
        assert error is None
        assert ledger.block_count() == 0
        assert ledger.chain_root() == "0" * 64
    finally:
        mem.close()


def test_ledger_appends_and_verifies(tmp_path):
    """Appending blocks should produce a valid chain."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        ledger = _seed_ledger(mem, n=5)
        assert ledger.block_count() == 5
        valid, error = ledger.verify()
        assert valid
        assert error is None
        # Chain root should be non-trivial
        root = ledger.chain_root()
        assert len(root) == 64
        assert root != "0" * 64
    finally:
        mem.close()


def test_ledger_chain_is_sequential(tmp_path):
    """Each block's prev_hash must match the previous block's hash."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        ledger = _seed_ledger(mem, n=3)
        blocks = ledger.get_blocks(start=0, limit=100)
        assert len(blocks) == 3
        assert blocks[0]["prev_hash"] == "0" * 64
        assert blocks[1]["prev_hash"] == blocks[0]["hash"]
        assert blocks[2]["prev_hash"] == blocks[1]["hash"]
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# Tamper detection
# --------------------------------------------------------------------------- #
def test_ledger_detects_tampered_data(tmp_path):
    """Modifying a block's data should break the chain."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        ledger = _seed_ledger(mem, n=3)
        assert ledger.verify()[0]  # valid before tampering

        # Tamper: modify a block's data directly in SQLite
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.execute(
            "UPDATE memory_ledger SET data=? WHERE block_index=1",
            (json.dumps({"tampered": True}),),
        )
        conn.commit()
        conn.close()

        # Re-open and verify
        valid, error = ledger.verify()
        assert not valid
        assert "tampered" in error.lower() or "mismatch" in error.lower()
    finally:
        mem.close()


def test_ledger_detects_tampered_hash(tmp_path):
    """Modifying a block's hash should break the chain."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        ledger = _seed_ledger(mem, n=3)
        assert ledger.verify()[0]

        # Tamper: modify a block's hash directly
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.execute(
            "UPDATE memory_ledger SET hash=? WHERE block_index=0",
            ("a" * 64,),
        )
        conn.commit()
        conn.close()

        valid, error = ledger.verify()
        assert not valid
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def test_ledger_export_json(tmp_path):
    """JSON export should contain all blocks and the chain root."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        ledger = _seed_ledger(mem, n=3)
        out = ledger.export(tmp_path / "export.json", fmt="json")
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["block_count"] == 3
        assert data["verified"] is True
        assert len(data["blocks"]) == 3
        assert "chain_root" in data
    finally:
        mem.close()


def test_ledger_export_soc2(tmp_path):
    """SOC 2 export should contain control mappings."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        ledger = _seed_ledger(mem, n=3)
        out = ledger.export(tmp_path / "soc2_report.md", fmt="soc2")
        assert out.exists()
        content = out.read_text()
        assert "SOC 2" in content
        assert "CC7.1" in content
        assert "EU AI Act Article 12" in content
        assert "VERIFIED" in content
    finally:
        mem.close()


def test_ledger_export_csv(tmp_path):
    """CSV export should have a header row and one row per block."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        ledger = _seed_ledger(mem, n=3)
        out = ledger.export(tmp_path / "export.csv", fmt="csv")
        assert out.exists()
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 4  # header + 3 blocks
        assert "index" in lines[0]
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# Attestation
# --------------------------------------------------------------------------- #
def test_ledger_attest_unsigned(tmp_path):
    """Unsigned attestation should include chain root and verification status."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        ledger = _seed_ledger(mem, n=3)
        att = ledger.attest()
        assert att["verified"] is True
        assert len(att["chain_root"]) == 64
        assert att["block_count"] == 3
        assert "signature" not in att
    finally:
        mem.close()


def test_ledger_attest_signed(tmp_path):
    """Signed attestation should include an HMAC signature."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        ledger = _seed_ledger(mem, n=3)
        att = ledger.attest(hmac_key="secret-key")
        assert att["verified"] is True
        assert "signature" in att
        assert att["signature_algorithm"] == "HMAC-SHA256"
        assert len(att["signature"]) == 64

        # Verify the signature
        import hmac as _hmac
        import hashlib
        expected = _hmac.new(
            b"secret-key", att["chain_root"].encode(), hashlib.sha256
        ).hexdigest()
        assert att["signature"] == expected
    finally:
        mem.close()


# --------------------------------------------------------------------------- #
# Integration with Howdex engine
# --------------------------------------------------------------------------- #
def test_ledger_accessible_from_howdex(tmp_path):
    """Howdex.ledger() should return a MemoryLedger instance."""
    mem = Howdex(path=str(tmp_path / "test.db"), embedder="hashing")
    try:
        ledger = mem.ledger()
        assert isinstance(ledger, MemoryLedger)
        # Calling again should return the same instance
        assert mem.ledger() is ledger
    finally:
        mem.close()


def test_ledger_survives_restart(tmp_path):
    """The ledger should persist across Howdex restarts."""
    db_path = str(tmp_path / "test.db")

    # First session: write some blocks
    mem1 = Howdex(path=db_path, embedder="hashing")
    ledger1 = mem1.ledger()
    ledger1.append("log_tool_call", {"cmd": "echo hello"})
    ledger1.append("end_session", {"outcome": "success"})
    root1 = ledger1.chain_root()
    mem1.close()

    # Second session: verify the blocks are still there
    mem2 = Howdex(path=db_path, embedder="hashing")
    ledger2 = mem2.ledger()
    assert ledger2.block_count() == 2
    assert ledger2.chain_root() == root1
    valid, _ = ledger2.verify()
    assert valid
    mem2.close()


# --------------------------------------------------------------------------- #
# CLI integration
# --------------------------------------------------------------------------- #
def test_cli_ledger_verify(tmp_path):
    """`howdex ledger verify` should work from the CLI."""
    import subprocess
    import sys
    db = tmp_path / "ledger.db"
    # First, create a Howdex instance and add some ledger entries
    mem = Howdex(path=str(db), embedder="hashing")
    ledger = mem.ledger()
    ledger.append("log_tool_call", {"cmd": "test"})
    mem.close()
    # Now verify from CLI
    result = subprocess.run(
        [sys.executable, "-m", "howdex.cli", "--path", str(db),
         "--embedder", "hashing", "ledger", "verify"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "verified" in result.stdout.lower()


def test_cli_ledger_root(tmp_path):
    """`howdex ledger root` should print the chain root."""
    import subprocess
    import sys
    db = tmp_path / "ledger.db"
    mem = Howdex(path=str(db), embedder="hashing")
    mem.ledger().append("test", {"data": "hello"})
    mem.close()
    result = subprocess.run(
        [sys.executable, "-m", "howdex.cli", "--path", str(db),
         "--embedder", "hashing", "ledger", "root"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    root = result.stdout.strip()
    assert len(root) == 64  # SHA-256 hex
