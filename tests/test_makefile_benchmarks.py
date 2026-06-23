"""Makefile benchmark command surface tests."""

from __future__ import annotations

from pathlib import Path


def test_makefile_contains_docker_benchmark_targets():
    makefile = Path(__file__).resolve().parents[1] / "Makefile"
    assert makefile.is_file()
    text = makefile.read_text(encoding="utf-8")

    assert "test:" in text
    assert "bench:" in text
    assert "bench-docker:" in text
    assert "bench-docker-n20:" in text
    assert (
        "HOWDEX_DOCKER_TRIALS=20 HOWDEX_DOCKER_MAX_TURNS=15"
        in text
    )
    assert "python3 real_docker_recovery_ab_test.py" in text
    assert "benchmark-results" in text
