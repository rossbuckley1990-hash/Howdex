"""Attach verifier evidence to a learned Howdex procedure."""

from __future__ import annotations

from pathlib import Path

from howdex import Howdex


def seed_procedure(memory: Howdex):
    memory.start_session("Verify a local test repair")
    memory.log_step("inspect package.json", "test script existed")
    memory.log_step("run pytest", "12 passed")
    memory.end_session("success")
    procedures = memory.learn(min_samples=1)
    if not procedures:
        raise RuntimeError("no procedure learned")
    return procedures[0]


def attach_test_receipt(db_path: str | Path = "howdex-pilot.db"):
    memory = Howdex(path=db_path, embedder="hashing")
    try:
        procedures = memory.list_procedures()
        procedure = procedures[0] if procedures else seed_procedure(memory)
        return memory.verify_procedure(
            procedure.id,
            verifier_type="test",
            verifier_command="python -m pytest",
            expected_signal="passed",
            observed_signal="12 passed",
            exit_code=0,
            environment_fingerprint={"pilot": "local"},
            artifact_hashes={},
        )
    finally:
        memory.close()


if __name__ == "__main__":
    receipt = attach_test_receipt()
    print(f"receipt_id={receipt.receipt_id} status={receipt.status}")
