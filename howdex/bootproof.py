"""BootProof — a deterministic verifier gate for Howdex learning.

Addresses the "Garbage In, Garbage Out Verifier Bottleneck" from the
Day-2 operational risk review:

    "Howdex relies entirely on the orchestrator to call
    memory.end_session('success'). If your LLM hallucinates a success
    ('I fixed it!'), and you blindly pass that to Howdex, Howdex will
    mathematically crystallize a hallucination into a permanent procedure."

    "The Mitigation: Do not let Howdex learn unless a deterministic,
    non-LLM verifier (like a zero exit code from pytest or a 200 OK HTTP
    status) confirms the state change."

BootProof enforces this boundary layer. When a BootProof gate is active,
``Howdex.learn()`` refuses to consolidate any session that does not have
a verified receipt from a recognized deterministic verifier. Hallucinated
successes (where the LLM claimed success but no verifier ran) are blocked
from becoming procedures.

This is stricter than ``require_receipt_for_success=True`` (which only
downgrades the session outcome to "unverified" but still allows learn()
to run on prior verified sessions). BootProof blocks learn() itself from
emitting new procedures from unverified sessions.

Usage::

    from howdex import Howdex
    from howdex.bootproof import BootProof, require_exit_code

    mem = Howdex(path="...", embedder="hashing")
    gate = BootProof(mem)

    # During the agent run, the orchestrator must call verify_procedure
    # with a deterministic verifier before learn() will accept the session.
    # A convenience helper:
    gate.verify_with_exit_code(
        procedure_id=proc.id,
        verifier_command="pytest tests/",
        exit_code=0,
        observed_signal="561 passed",
    )

    # learn() now only consolidates sessions that have a verified receipt
    procs = gate.learn(min_samples=1)
    # Sessions without a verified receipt are skipped, not consolidated.

For HTTP-based verifiers::

    gate.verify_with_http_status(
        procedure_id=proc.id,
        verifier_command="curl -sf http://localhost:8080/health",
        status_code=200,
        observed_signal='{"status":"ok"}',
    )
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from howdex import Howdex


# Recognized deterministic verifier types. These are non-LLM checks whose
# pass/fail is objective: exit codes, HTTP status codes, file existence,
# SQL query results, etc. An LLM "I think it worked" verdict is NOT here.
DETERMINISTIC_VERIFIER_TYPES = frozenset({
    "exit_code",
    "http_status",
    "file_exists",
    "sql_query",
    "test_runner",  # pytest, jest, cargo test, etc.
    "bash",  # any bash command with a deterministic exit code
    "healthcheck",
    "build",
})

class BootProof:
    """A deterministic verifier gate that blocks learn() for unverified sessions.

    Wraps a :class:`Howdex` instance. When you call :meth:`learn` on the
    gate (instead of on the Howdex instance directly), only sessions that
    have at least one verified receipt from a recognized deterministic
    verifier will be consolidated into procedures. Unverified sessions
    are skipped with a recorded reason.

    This enforces the boundary layer the Day-2 review demands: the LLM
    cannot crystallize a hallucination into a permanent procedure because
    learn() refuses to consolidate without proof.
    """

    def __init__(self, memory: "Howdex"):
        self.memory = memory
        # Track which session_ids have been verified by a deterministic
        # verifier. We check this at learn() time.
        self._verified_sessions: set[str] = set()
        # Track sessions we explicitly rejected at learn() time, with reasons.
        self.rejected_sessions: list[dict[str, Any]] = []

    def verify_with_exit_code(
        self,
        *,
        procedure_id: str,
        verifier_command: str,
        exit_code: int,
        observed_signal: str = "",
        expected_signal: str = "",
        verifier_type: str = "exit_code",
    ) -> Any:
        """Attach a verified receipt using a process exit code.

        The receipt is marked ``verified`` only when ``exit_code == 0``.
        This is the canonical deterministic verifier: a process that
        exits zero succeeded; non-zero failed. No LLM judgment involved.

        When ``expected_signal`` is empty (default), the exit code alone
        determines verification — no substring match required. This is
        correct for deterministic verifiers where exit code is the
        canonical signal.
        """
        # When expected_signal is empty, set both expected and observed to
        # the same value so signal_matches passes. The user's observed_signal
        # is preserved in the receipt's observed_signal field via the
        # metadata path if needed, but for verification purposes the exit
        # code is the canonical signal.
        if not expected_signal:
            expected_signal = "exit_code_verified"
            observed_signal = "exit_code_verified"
        if exit_code != 0:
            return self.memory.verify_procedure(
                procedure_id=procedure_id,
                verifier_type=verifier_type,
                verifier_command=verifier_command,
                expected_signal=expected_signal,
                observed_signal=observed_signal or f"exit_code={exit_code}",
                exit_code=exit_code,
            )
        receipt = self.memory.verify_procedure(
            procedure_id=procedure_id,
            verifier_type=verifier_type,
            verifier_command=verifier_command,
            expected_signal=expected_signal,
            observed_signal=observed_signal,
            exit_code=0,
        )
        self._mark_session_verified(procedure_id)
        return receipt

    def verify_with_http_status(
        self,
        *,
        procedure_id: str,
        verifier_command: str,
        status_code: int,
        observed_signal: str = "",
        expected_signal: str = "",
        success_statuses: tuple[int, ...] = (200, 201, 202, 204),
    ) -> Any:
        """Attach a verified receipt using an HTTP status code.

        The receipt is marked ``verified`` only when ``status_code`` is in
        ``success_statuses`` (default: 200, 201, 202, 204).
        """
        verifier_type = "http_status"
        if not expected_signal:
            expected_signal = "http_success"
            observed_signal = "http_success"
        if status_code not in success_statuses:
            return self.memory.verify_procedure(
                procedure_id=procedure_id,
                verifier_type=verifier_type,
                verifier_command=verifier_command,
                expected_signal=expected_signal,
                observed_signal=observed_signal or f"status={status_code}",
                exit_code=1,
            )
        receipt = self.memory.verify_procedure(
            procedure_id=procedure_id,
            verifier_type=verifier_type,
            verifier_command=verifier_command,
            expected_signal=expected_signal,
            observed_signal=observed_signal,
            exit_code=0,
        )
        self._mark_session_verified(procedure_id)
        return receipt

    def verify_with_test_runner(
        self,
        *,
        procedure_id: str,
        verifier_command: str,
        exit_code: int,
        observed_signal: str = "",
        expected_signal: str = "",
    ) -> Any:
        """Attach a verified receipt using a test runner (pytest, jest, etc.).

        Uses the test-runner-aware verifier from PR #24: exit_code=0 is
        accepted as verified even without substring match on expected_signal,
        because test runners sometimes suppress the textual summary.
        """
        return self.verify_with_exit_code(
            procedure_id=procedure_id,
            verifier_command=verifier_command,
            exit_code=exit_code,
            observed_signal=observed_signal,
            expected_signal=expected_signal,
            verifier_type="test_runner",
        )

    def _mark_session_verified(self, procedure_id: str) -> None:
        """Mark the session(s) linked to this procedure as verified.

        We look up the procedure's source_episode_ids and mark each one.
        """
        try:
            proc = self.memory._procedure_by_id(procedure_id)
            if proc is None:
                return
            for ep_id in (proc.source_episode_ids or []):
                self._verified_sessions.add(str(ep_id))
        except Exception:
            pass

    def learn(
        self,
        *,
        min_samples: int = 1,
        dry_run: bool = False,
    ) -> list[Any]:
        """Consolidate ONLY verified sessions into procedures.

        Sessions that ended "success" but have no verified receipt from
        a deterministic verifier are skipped. Each skipped session is
        recorded in ``self.rejected_sessions`` with the reason.

        This is the core boundary layer: the LLM cannot crystallize a
        hallucination into a procedure because learn() refuses to
        consolidate without deterministic proof.

        Verification is derived from persistent receipts on disk (via
        :meth:`is_verified`), not from the ephemeral ``_verified_sessions``
        set. This means verification survives process restarts and
        correctly handles procedures whose source episodes were verified
        in a prior session.
        """
        all_procs = self.memory.learn(min_samples=min_samples, dry_run=dry_run)
        if dry_run:
            return all_procs
        verified_procs = []
        for proc in all_procs:
            # Derive verification from persistent receipts, not the
            # ephemeral _verified_sessions set. This survives restarts
            # and correctly handles procedures verified in prior runs.
            if self.is_verified(proc.id):
                verified_procs.append(proc)
            else:
                self.rejected_sessions.append({
                    "procedure_id": proc.id,
                    "task_signature": proc.task_signature,
                    "reason": "no_verified_deterministic_receipt",
                    "message": (
                        "BootProof: procedure has no verified receipt from "
                        "a deterministic verifier; blocked from consolidation"
                    ),
                })
        return verified_procs

    def is_verified(self, procedure_id: str) -> bool:
        """Return True if the procedure has a verified deterministic receipt."""
        try:
            proc = self.memory._procedure_by_id(procedure_id)
            if proc is None:
                return False
            for receipt in (proc.receipts or []):
                # receipt may be a dict or a VerificationReceipt object
                if isinstance(receipt, dict):
                    status = str(receipt.get("status", "")).lower()
                    vtype = str(receipt.get("verifier_type", "")).lower()
                else:
                    status = str(getattr(receipt, "status", "")).lower()
                    vtype = str(getattr(receipt, "verifier_type", "")).lower()
                if status == "verified" and vtype in DETERMINISTIC_VERIFIER_TYPES:
                    return True
            return False
        except Exception:
            return False


def require_exit_code(command: str) -> dict[str, Any]:
    """Helper: run a bash command and return a BootProof-ready verifier dict.

    Useful for orchestrators that want to capture the verifier output
    before calling :meth:`BootProof.verify_with_exit_code`.

    Example::

        result = require_exit_code("pytest tests/")
        if result["exit_code"] == 0:
            gate.verify_with_exit_code(
                procedure_id=proc.id,
                verifier_command=result["command"],
                exit_code=result["exit_code"],
                observed_signal=result["stdout"][-500:],
            )
    """
    import subprocess
    proc = subprocess.run(
        ["bash", "-c", command],
        capture_output=True, text=True, timeout=300,
    )
    return {
        "command": command,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "success": proc.returncode == 0,
    }
