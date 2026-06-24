#!/usr/bin/env python3
"""Dogfood Howdex by recording Howdex roadmap work as procedural memory.

The CLI intentionally stays local-only: it stores a draft phase trace under
``.howdex/dogfood/current.json`` and commits that trace into a dedicated local
Howdex SQLite database when the phase ends.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from howdex import Howdex  # noqa: E402


DEFAULT_ROOT = Path(".howdex") / "dogfood"
DEFAULT_DB_NAME = "howdex.db"
STATE_FILE_NAME = "current.json"
CODEX_DIR_NAME = "codex"
DOGFOOD_SOURCE = "howdex-dogfood"


def _now() -> float:
    return time.time()


def _iso(ts: float | None = None) -> str:
    return time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(_now() if ts is None else ts),
    )


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_root(value: str | None = None) -> Path:
    return Path(value).expanduser() if value else DEFAULT_ROOT


def state_path(root: Path) -> Path:
    return root / STATE_FILE_NAME


def db_path(root: Path, override: str | None = None) -> Path:
    return Path(override).expanduser() if override else root / DEFAULT_DB_NAME


def codex_path(root: Path) -> Path:
    return root / CODEX_DIR_NAME


def load_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        raise SystemExit(
            f"no active dogfood phase at {path}; run `howdex_dogfood.py start` first"
        )
    return _read_json(path)


def start_phase(
    *,
    phase: str,
    objective: str,
    root: Path,
    db: Path,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = state_path(root)
    if path.exists():
        raise SystemExit(
            f"dogfood phase already active at {path}; end it before starting another"
        )

    root.mkdir(parents=True, exist_ok=True)
    memory = Howdex(path=db, embedder="hashing")
    try:
        episode = memory.start_session(
            objective,
            source=DOGFOOD_SOURCE,
            provenance={
                "phase": phase,
                "dogfood_state": str(path),
                **dict(metadata or {}),
            },
        )
        session_id = episode.session_id
    finally:
        memory.close()

    payload = {
        "created_at": _iso(),
        "db_path": str(db),
        "metadata": dict(metadata or {}),
        "objective": objective,
        "phase": phase,
        "session_id": session_id,
        "source": DOGFOOD_SOURCE,
        "started_at": _now(),
        "steps": [],
        "version": 1,
    }
    _write_json(path, payload)
    return payload


def log_step(
    *,
    root: Path,
    action: str,
    observation: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = load_state(root)
    step = {
        "action": action,
        "metadata": dict(metadata or {}),
        "observation": observation,
        "recorded_at": _iso(),
        "ts": _now(),
    }
    payload.setdefault("steps", []).append(step)
    _write_json(state_path(root), payload)
    return payload


def _replay_state(memory: Howdex, payload: dict[str, Any]) -> str:
    episode = memory.start_session(
        str(payload["objective"]),
        source=payload.get("source") or DOGFOOD_SOURCE,
        provenance={
            "dogfood": True,
            "phase": payload.get("phase"),
            "phase_metadata": payload.get("metadata", {}),
            "state_session_id": payload.get("session_id"),
        },
    )
    episode.session_id = str(payload["session_id"])
    episode.started_at = float(payload.get("started_at") or _now())
    for step in payload.get("steps", []):
        memory.log_step(
            str(step.get("action", "")),
            str(step.get("observation", "")),
            metadata={
                "dogfood_phase": payload.get("phase"),
                **dict(step.get("metadata") or {}),
            },
            ts=float(step.get("ts") or _now()),
        )
    return episode.session_id


def end_phase(
    *,
    root: Path,
    outcome: str,
    verifier: str | None = None,
    observed: str | None = None,
    expected: str | None = None,
    exit_code: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    payload = load_state(root)
    db = Path(payload.get("db_path") or db_path(root))
    memory = Howdex(path=db, embedder="hashing")
    try:
        episode_id = _replay_state(memory, payload)
        memory.end_session(outcome=outcome, error=error)
        learned = memory.learn(min_samples=1)

        # Publish immediately after learning so dogfood Codex entries are
        # candidate entries by default. Receipts are attached below as optional
        # local evidence and can be republished later by an explicit operator.
        published = memory.publish_codex(codex_path(root))

        receipts = []
        if verifier and observed is not None:
            resolved_expected = expected or observed
            resolved_exit_code = (
                int(exit_code)
                if exit_code is not None
                else (0 if outcome == "success" else 1)
            )
            for procedure in learned:
                receipts.append(
                    memory.verify_procedure(
                        procedure.id,
                        verifier_type="dogfood",
                        verifier_command=verifier,
                        expected_signal=resolved_expected,
                        observed_signal=observed,
                        exit_code=resolved_exit_code,
                        source_episode_id=episode_id,
                        environment_fingerprint={
                            "source": DOGFOOD_SOURCE,
                            "phase": payload.get("phase"),
                        },
                        metadata={
                            "dogfood": True,
                            "phase": payload.get("phase"),
                        },
                    )
                )

        state_path(root).unlink(missing_ok=True)
        return {
            "codex_path": str(codex_path(root)),
            "episode_id": episode_id,
            "learned_procedure_ids": [procedure.id for procedure in learned],
            "phase": payload.get("phase"),
            "published_files": [str(path) for path in published.get("files", [])],
            "receipt_ids": [str(receipt.receipt_id) for receipt in receipts],
        }
    finally:
        memory.close()


def render_guidance(
    *,
    objective: str,
    root: Path,
    db: Path,
    max_chars: int = 6000,
) -> str:
    memory = Howdex(path=db, embedder="hashing")
    try:
        return memory.guidance(
            objective,
            target_environment="Howdex repository dogfood build loop",
            constraints=[
                "Use prior dogfood procedures as guidance only.",
                "Do not include source artifacts unless explicitly requested.",
                "Verify the phase with local commands before treating it as complete.",
            ],
            include_source=False,
            include_verification=True,
            max_chars=max_chars,
        )
    finally:
        memory.close()


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--metadata must be JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("--metadata must be a JSON object")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dogfood Howdex by recording Howdex roadmap build phases."
    )
    parser.add_argument("--root", default=None, help="dogfood root; default .howdex/dogfood")
    parser.add_argument("--db", default=None, help="Howdex DB path; default <root>/howdex.db")

    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start a dogfood phase")
    start.add_argument("--phase", required=True)
    start.add_argument("--objective", required=True)
    start.add_argument("--metadata", default=None, help="optional JSON object")

    step = sub.add_parser("step", help="append a step to the active phase")
    step.add_argument("--action", required=True)
    step.add_argument("--observation", required=True)
    step.add_argument("--metadata", default=None, help="optional JSON object")

    end = sub.add_parser("end", help="end the active phase, learn, and publish candidate Codex")
    end.add_argument("--outcome", default="success")
    end.add_argument("--error", default=None)
    end.add_argument("--verifier", default=None)
    end.add_argument("--observed", default=None)
    end.add_argument("--expected", default=None)
    end.add_argument("--exit-code", type=int, default=None)

    guidance = sub.add_parser("guidance", help="render guidance for the next phase")
    guidance.add_argument("--objective", required=True)
    guidance.add_argument("--max-chars", type=int, default=6000)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = resolve_root(args.root)
    db = db_path(root, args.db)

    if args.command == "start":
        payload = start_phase(
            phase=args.phase,
            objective=args.objective,
            root=root,
            db=db,
            metadata=_parse_metadata(args.metadata),
        )
        print(f"active_session_id={payload['session_id']}")
        print(f"state={state_path(root)}")
        return 0

    if args.command == "step":
        payload = log_step(
            root=root,
            action=args.action,
            observation=args.observation,
            metadata=_parse_metadata(args.metadata),
        )
        print(f"active_session_id={payload['session_id']}")
        print(f"stored_steps={len(payload.get('steps', []))}")
        return 0

    if args.command == "end":
        result = end_phase(
            root=root,
            outcome=args.outcome,
            verifier=args.verifier,
            observed=args.observed,
            expected=args.expected,
            exit_code=args.exit_code,
            error=args.error,
        )
        print(f"episode_id={result['episode_id']}")
        print(
            "learned_procedure_ids="
            + ",".join(result["learned_procedure_ids"])
        )
        print(f"candidate_codex={result['codex_path']}")
        if result["receipt_ids"]:
            print("receipt_ids=" + ",".join(result["receipt_ids"]))
        return 0

    if args.command == "guidance":
        print(
            render_guidance(
                objective=args.objective,
                root=root,
                db=db,
                max_chars=args.max_chars,
            )
        )
        return 0

    raise AssertionError(f"unhandled command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
