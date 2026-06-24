"""Framework-neutral decorators and middleware for Howdex."""

from __future__ import annotations

import functools
import inspect
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, TypeVar, cast

from howdex.adapters._shared import adapter_guidance, learned_summary

F = TypeVar("F", bound=Callable[..., Any])
DEFAULT_GUIDANCE_MAX_CHARS = 6_000


@dataclass(frozen=True)
class _SessionFrame:
    memory: Any
    session_id: str
    parent_session: Any


_SESSION_STACK: ContextVar[tuple[_SessionFrame, ...]] = ContextVar(
    "howdex_generic_session_stack",
    default=(),
)


def howdex_task(
    memory: Any,
    objective: str | Callable[..., str] | None = None,
    learn: bool = True,
    metadata: dict[str, Any] | None = None,
) -> Callable[[F], F]:
    """Decorate any Python function as a Howdex-recorded task.

    A session starts before the function runs, closes on success/failure, and
    learns procedures when ``learn=True``. Nested decorated tasks temporarily
    detach and restore their parent session so parent evidence is not closed or
    corrupted by the child.
    """

    def decorator(func: F) -> F:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                task = _resolve_objective(objective, func, args, kwargs)
                _start_managed_session(memory, task, metadata=metadata)
                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    _end_managed_session(
                        memory,
                        outcome="failure",
                        error=_error_text(exc),
                        learn=learn,
                    )
                    raise
                _end_managed_session(memory, outcome="success", learn=learn)
                return result

            return cast(F, async_wrapper)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            task = _resolve_objective(objective, func, args, kwargs)
            _start_managed_session(memory, task, metadata=metadata)
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                _end_managed_session(
                    memory,
                    outcome="failure",
                    error=_error_text(exc),
                    learn=learn,
                )
                raise
            _end_managed_session(memory, outcome="success", learn=learn)
            return result

        return cast(F, wrapper)

    return decorator


def howdex_tool(
    memory: Any,
    name: str | None = None,
) -> Callable[[F], F]:
    """Decorate a tool function so calls are logged to the active session."""

    def decorator(func: F) -> F:
        tool_name = name or func.__name__

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                arguments = _bound_arguments(func, args, kwargs)
                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    _log_tool_if_active(
                        memory,
                        tool_name,
                        arguments,
                        _error_text(exc),
                        status="failure",
                        error=_error_text(exc),
                    )
                    raise
                _log_tool_if_active(
                    memory,
                    tool_name,
                    arguments,
                    _observation_text(result),
                    status="success",
                )
                return result

            return cast(F, async_wrapper)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            arguments = _bound_arguments(func, args, kwargs)
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                _log_tool_if_active(
                    memory,
                    tool_name,
                    arguments,
                    _error_text(exc),
                    status="failure",
                    error=_error_text(exc),
                )
                raise
            _log_tool_if_active(
                memory,
                tool_name,
                arguments,
                _observation_text(result),
                status="success",
            )
            return result

        return cast(F, wrapper)

    return decorator


class HowdexMiddleware:
    """Framework-neutral session middleware for Python agent loops."""

    def __init__(
        self,
        memory: Any,
        *,
        max_chars: int = DEFAULT_GUIDANCE_MAX_CHARS,
        verified_only: bool = False,
        include_source: bool = False,
        top_k: int = 3,
        min_confidence: float = 0.0,
        min_samples: int = 1,
    ):
        self.memory = memory
        self.max_chars = int(max_chars)
        self.verified_only = bool(verified_only)
        self.include_source = bool(include_source)
        self.top_k = int(top_k)
        self.min_confidence = float(min_confidence)
        self.min_samples = int(min_samples)

    def before_task(self, objective: str, **metadata: Any) -> str:
        """Start a task session and return deterministic Howdex guidance."""
        constraints = metadata.get("constraints")
        environment = metadata.get("environment") or metadata.get(
            "target_environment"
        )
        _start_managed_session(
            self.memory,
            objective,
            source="generic_middleware",
            metadata=metadata,
        )
        return adapter_guidance(
            self.memory,
            objective,
            constraints=constraints,
            environment=environment,
            max_chars=self.max_chars,
            verified_only=self.verified_only,
            include_source=self.include_source,
            top_k=self.top_k,
            min_confidence=self.min_confidence,
            adapter="generic",
        )

    def after_tool(
        self,
        name: str,
        args: dict[str, Any] | None,
        observation: str,
        status: str,
    ) -> None:
        """Record a structured tool call in the active middleware session."""
        _log_tool_if_active(
            self.memory,
            name,
            args or {},
            observation,
            status=status,
        )

    def after_task(
        self,
        outcome: str,
        error: str | None = None,
        learn: bool = True,
    ) -> list[dict[str, Any]]:
        """End the active middleware session and optionally learn."""
        return _end_managed_session(
            self.memory,
            outcome=outcome,
            error=error,
            learn=learn,
            min_samples=self.min_samples,
        )


def _start_managed_session(
    memory: Any,
    objective: str,
    *,
    source: str = "generic",
    metadata: dict[str, Any] | None = None,
) -> str:
    parent_session = getattr(memory, "_current_session", None)
    if parent_session is not None and not getattr(
        parent_session,
        "finished_at",
        None,
    ):
        memory._current_session = None
    else:
        parent_session = None

    episode = memory.start_session(
        objective or "python agent task",
        source=source,
        provenance={
            "adapter": source,
            "metadata": dict(metadata or {}),
        },
    )
    _SESSION_STACK.set(
        _SESSION_STACK.get()
        + (
            _SessionFrame(
                memory=memory,
                session_id=episode.session_id,
                parent_session=parent_session,
            ),
        )
    )
    return episode.session_id


def _end_managed_session(
    memory: Any,
    *,
    outcome: str,
    error: str | None = None,
    learn: bool = True,
    min_samples: int = 1,
) -> list[dict[str, Any]]:
    frame = _pop_frame(memory)
    parent_session = frame.parent_session if frame is not None else None
    try:
        if frame is not None:
            current = getattr(memory, "_current_session", None)
            if getattr(current, "session_id", None) != frame.session_id:
                raise RuntimeError("active Howdex session changed before task end")
        memory.end_session(outcome=outcome, error=error)
        if not learn:
            return []
        return learned_summary(memory.learn(min_samples=min_samples))
    finally:
        if parent_session is not None and not getattr(
            parent_session,
            "finished_at",
            None,
        ):
            memory._current_session = parent_session


def _pop_frame(memory: Any) -> _SessionFrame | None:
    stack = list(_SESSION_STACK.get())
    for index in range(len(stack) - 1, -1, -1):
        if stack[index].memory is memory:
            frame = stack.pop(index)
            _SESSION_STACK.set(tuple(stack))
            return frame
    return None


def _log_tool_if_active(
    memory: Any,
    name: str,
    arguments: dict[str, Any],
    observation: str,
    *,
    status: str,
    error: str | None = None,
) -> None:
    if getattr(memory, "_current_session", None) is None:
        return
    extra: dict[str, Any] = {"outcome": status}
    if error is not None:
        extra["error"] = error
    memory.log_tool_call(
        name,
        arguments=arguments,
        observation=observation,
        metadata={"adapter": "generic"},
        **extra,
    )


def _resolve_objective(
    objective: str | Callable[..., str] | None,
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str:
    if callable(objective):
        return " ".join(str(objective(*args, **kwargs) or "").split())
    if objective:
        return " ".join(str(objective).split())
    return func.__name__.replace("_", " ")


def _bound_arguments(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)
    except (TypeError, ValueError):
        return {"args": list(args), "kwargs": dict(kwargs)}


def _observation_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    return repr(result)


def _error_text(exc: BaseException) -> str:
    return f"{exc.__class__.__name__}: {exc}"


__all__ = [
    "HowdexMiddleware",
    "howdex_task",
    "howdex_tool",
]
