from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class HowdexSession:
    memory: object
    task: str
    active: bool = False
    closed: bool = False

    def __enter__(self):
        self.memory.start_session(self.task)
        self.active = True
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.closed:
            return False

        if exc is not None:
            self.failure(str(exc))
            return False

        self.success()
        return False

    def step(self, action: str, observation: str):
        if not self.active:
            raise RuntimeError("Howdex session is not active.")

        if self.closed:
            raise RuntimeError("Howdex session is already closed.")

        self.memory.log_step(action, observation)
        return self

    def success(self):
        if not self.closed:
            self.memory.end_session("success")
            self.closed = True
        return self

    def failure(self, error: Optional[str] = None):
        if not self.closed:
            self.memory.end_session("failure", error=error)
            self.closed = True
        return self
