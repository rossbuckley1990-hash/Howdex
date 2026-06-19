from __future__ import annotations

from typing import Any


class Mem0Unavailable(RuntimeError):
    pass


class Mem0ComparisonMemory:
    """Small wrapper around Mem0 for benchmark comparison.

    This intentionally treats Mem0 as context memory: store text, search text.
    It does not give Mem0 Howdex's procedural consolidation logic.
    """

    def __init__(self, user_id: str = "howdex-benchmark"):
        try:
            from mem0 import Memory
        except Exception as exc:
            raise Mem0Unavailable(
                "mem0ai is not installed or could not be imported. "
                "Install with: python -m pip install mem0ai"
            ) from exc

        self.user_id = user_id
        self.memory = Memory()

    def remember_episode(self, task: str, actions: list[str], outcome: str) -> None:
        content = (
            f"Task: {task}\n"
            f"Actions taken: {', '.join(actions)}\n"
            f"Outcome: {outcome}"
        )

        # Mem0 API versions vary. Keep this benchmark robust: Mem0 gets
        # credit only if it can store/search context under its installed API.
        try:
            self.memory.add(content, user_id=self.user_id)
            return
        except Exception as first_error:
            self.last_add_error = str(first_error)

        try:
            self.memory.add(
                messages=[{"role": "user", "content": content}],
                user_id=self.user_id,
            )
            return
        except Exception as second_error:
            self.last_add_error = str(second_error)

        try:
            self.memory.add(
                messages=[{"role": "user", "content": content}],
                filters={"user_id": self.user_id},
            )
            return
        except Exception as third_error:
            self.last_add_error = str(third_error)

    def search(self, query: str, limit: int = 5) -> list[Any]:
        attempts = [
            lambda: self.memory.search(
                query=query,
                filters={"user_id": self.user_id},
                limit=limit,
            ),
            lambda: self.memory.search(
                query,
                filters={"user_id": self.user_id},
                limit=limit,
            ),
            lambda: self.memory.search(
                query=query,
                user_id=self.user_id,
                limit=limit,
            ),
            lambda: self.memory.search(
                query,
                user_id=self.user_id,
                limit=limit,
            ),
        ]

        result = None
        errors: list[str] = []

        for attempt in attempts:
            try:
                result = attempt()
                break
            except Exception as exc:
                errors.append(str(exc))

        if result is None:
            self.last_search_error = " | ".join(errors[-3:])
            return []

        if isinstance(result, list):
            return result

        if isinstance(result, dict):
            for key in ("results", "memories", "data"):
                value = result.get(key)
                if isinstance(value, list):
                    return value

        return []
