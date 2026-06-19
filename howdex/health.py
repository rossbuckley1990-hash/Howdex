from __future__ import annotations

from pathlib import Path
import tempfile

from howdex import Howdex


def healthcheck() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "howdex.db"
        mem = Howdex(path=str(path))

        m = mem.remember_trusted(
            "Healthcheck memory.",
            source="system",
            trust="verified",
            safety="general",
            importance=0.9,
        )

        results = mem.search("healthcheck", top_k=1, min_score=0.0)

        with mem.session("healthcheck task") as s:
            s.step("check", "passed")
            s.success()

        stats = mem.stats()

        return {
            "ok": bool(results),
            "memory_id": getattr(m, "id", None),
            "stats": stats,
            "db_path": str(path),
        }


if __name__ == "__main__":
    result = healthcheck()
    print(result)
    raise SystemExit(0 if result["ok"] else 1)
