"""Tests for the vector index."""

import numpy as np
import pytest

from howdex.vectors import HashingEmbedder, VectorIndex


@pytest.fixture
def index():
    return VectorIndex(dim=8, metric="cosine")


def test_add_and_search(index):
    index.add("a", [1, 0, 0, 0, 0, 0, 0, 0])
    index.add("b", [0, 1, 0, 0, 0, 0, 0, 0])
    index.add("c", [0.9, 0.1, 0, 0, 0, 0, 0, 0])
    hits = index.search([1, 0, 0, 0, 0, 0, 0, 0], k=2)
    assert len(hits) == 2
    assert hits[0][0] == "a"
    assert hits[0][1] > 0.99


def test_search_empty_index(index):
    assert index.search([1, 0, 0, 0, 0, 0, 0, 0], k=5) == []


def test_remove(index):
    index.add("a", [1, 0, 0, 0, 0, 0, 0, 0])
    index.add("b", [0, 1, 0, 0, 0, 0, 0, 0])
    index.remove("a")
    hits = index.search([1, 0, 0, 0, 0, 0, 0, 0], k=5)
    ids = [h[0] for h in hits]
    assert "a" not in ids


def test_hashing_embedder_deterministic():
    e = HashingEmbedder(dim=64)
    v1 = e.embed("hello world")
    v2 = e.embed("hello world")
    assert v1 == v2


def test_hashing_embedder_normalized():
    e = HashingEmbedder(dim=64)
    v = e.embed("hello world")
    norm = sum(x * x for x in v) ** 0.5
    assert abs(norm - 1.0) < 1e-5


def test_hashing_embedder_similar():
    """Similar texts should produce higher cosine sim than dissimilar."""
    e = HashingEmbedder(dim=256)
    v1 = np.array(e.embed("user prefers dark mode"))
    v2 = np.array(e.embed("user prefers dark mode ui"))
    v3 = np.array(e.embed("the weather is sunny today"))
    sim_similar = v1 @ v2
    sim_diff = v1 @ v3
    assert sim_similar > sim_diff
