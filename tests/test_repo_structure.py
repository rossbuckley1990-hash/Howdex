from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_repo_structure_doc_exists_and_describes_main_directories():
    doc = _read("docs/REPO_STRUCTURE.md")

    for directory in (
        "howdex/",
        "tests/",
        "docs/",
        "examples/",
        "benchmarks/",
        "evidence/",
        "scripts/",
        "codex/",
        "launch/",
    ):
        assert directory in doc


def test_readme_links_to_benchmarks_without_build_diary_language():
    readme = _read("README.md").casefold()

    assert "docs/benchmarks.md" in readme
    assert "remaining roadmap phases" not in readme
    assert "roadmap phases" not in readme
    assert "build diary" not in readme


def test_root_benchmark_files_are_compatibility_wrappers_only():
    wrappers = {
        "real_docker_recovery_ab_test.py": "benchmarks.docker_recovery.real_docker_recovery_ab_test",
        "docker_compounding_curve_test.py": "benchmarks.docker_recovery.docker_compounding_curve_test",
        "real_macgyver_test.py": "benchmarks.macgyver.real_macgyver_test",
        "real_macgyver_ab_test.py": "benchmarks.macgyver.real_macgyver_ab_test",
        "polyglot_macgyver_test.py": "benchmarks.polyglot.polyglot_macgyver_test",
        "polyglot_macgyver_nosynth_test.py": "benchmarks.polyglot.polyglot_macgyver_nosynth_test",
        "cross_model_verified_transfer_test.py": "benchmarks.transfer.cross_model_verified_transfer_test",
        "procedure_trust_calibration_test.py": "benchmarks.trust_calibration.procedure_trust_calibration_test",
    }

    for filename, module_path in wrappers.items():
        text = _read(filename)
        assert "Compatibility wrapper" in text
        assert module_path in text
        assert len(text.splitlines()) <= 12


def test_committed_dogfood_evidence_lives_under_evidence():
    committed_root = ROOT / "evidence" / "dogfood" / "results"

    assert committed_root.is_dir()
    assert (committed_root / "metrics.csv").is_file()
    assert list(committed_root.glob("*/summary.json"))
    assert not (ROOT / "dogfood-results").exists()


def test_benchmark_evidence_lives_under_evidence():
    assert (
        ROOT
        / "evidence"
        / "docker_n20"
        / "docker_hard_ab_n20_20260623_172737.txt"
    ).is_file()
    assert (
        ROOT
        / "evidence"
        / "trust_calibration"
        / "TRUST_CALIBRATION_RESULTS.md"
    ).is_file()
    assert (
        ROOT
        / "evidence"
        / "awm_head_to_head"
        / "AWM_HEAD_TO_HEAD_RESULTS.md"
    ).is_file()


def test_awm_result_note_stays_caveated():
    text = _read("evidence/awm_head_to_head/AWM_HEAD_TO_HEAD_RESULTS.md")

    assert "dry-run harness numbers" in text
    assert (
        "This is a local AWM-style approximation unless explicitly stated otherwise. "
        "It is not a claim that Howdex has beaten the AWM paper or public "
        "WebArena/Mind2Web baselines."
    ) in text


def test_makefile_benchmark_targets_point_to_valid_wrapper():
    text = _read("Makefile")

    assert "make bench-docker-n20" in text
    assert "python3 real_docker_recovery_ab_test.py" in text
    assert (ROOT / "real_docker_recovery_ab_test.py").is_file()
