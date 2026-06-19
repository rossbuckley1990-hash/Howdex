"""Tests for the CLI."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

CLI = [sys.executable, "-m", "howdex.cli"]


def _run(args, env=None):
    return subprocess.run(CLI + args, capture_output=True, text=True, env=env)


def test_init(tmp_path):
    db = tmp_path / "r.db"
    r = _run(["--path", str(db), "init"])
    assert r.returncode == 0
    assert db.exists()


def test_remember_and_search(tmp_path):
    db = tmp_path / "r.db"
    _run(["--path", str(db), "--embedder", "hashing", "init"])
    r = _run(["--path", str(db), "--embedder", "hashing",
              "remember", "user loves python",
              "--layer", "semantic", "--importance", "0.9"])
    assert r.returncode == 0
    r = _run(["--path", str(db), "--embedder", "hashing",
              "search", "user programming preference"])
    assert r.returncode == 0
    assert "python" in r.stdout.lower()


def test_recall_is_compatibility_alias(tmp_path):
    db = tmp_path / "r.db"
    _run(["--path", str(db), "--embedder", "hashing", "remember", "alias memory"])
    r = _run(["--path", str(db), "--embedder", "hashing", "recall", "alias"])
    assert r.returncode == 0
    assert "alias memory" in r.stdout.lower()


def test_version():
    r = _run(["--version"])
    assert r.returncode == 0
    assert r.stdout.strip().startswith("howdex ")


def test_stats(tmp_path):
    db = tmp_path / "r.db"
    _run(["--path", str(db), "--embedder", "hashing", "init"])
    _run(["--path", str(db), "--embedder", "hashing", "remember", "x"])
    r = _run(["--path", str(db), "--embedder", "hashing", "stats"])
    assert r.returncode == 0
    assert "total memories" in r.stdout.lower()


def test_export(tmp_path):
    db = tmp_path / "r.db"
    _run(["--path", str(db), "--embedder", "hashing", "init"])
    _run(["--path", str(db), "--embedder", "hashing", "remember", "test memory"])
    out = tmp_path / "export.json"
    r = _run(["--path", str(db), "--embedder", "hashing", "export", str(out)])
    assert r.returncode == 0
    data = json.loads(out.read_text())
    assert len(data["memories"]) >= 1
