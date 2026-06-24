"""Source-artifact and failed-attempt extraction for guidance renderers."""

from __future__ import annotations

import json
from typing import Any

from howdex.core.guidance_utils import as_list, get_value, unique_strings


def extract_tool_args(step: Any) -> dict[str, Any]:
    if not isinstance(step, dict):
        return {}
    for key in ("tool_args", "parameterized_args", "args", "arguments"):
        value = step.get(key)
        if isinstance(value, dict):
            return value
    return {}


def extract_observation(step: Any) -> str:
    if not isinstance(step, dict):
        return ""
    for key in ("observation", "output", "result"):
        value = step.get(key)
        if value:
            return str(value)
    return ""


def source_artifacts(procedure: Any) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for artifact in as_list(get_value(procedure, "source_artifacts")):
        if not isinstance(artifact, dict):
            continue
        file_path = (
            artifact.get("file_path")
            or artifact.get("path")
            or artifact.get("filename")
        )
        content = artifact.get("content")
        if file_path and content:
            artifacts.append(
                {"file_path": str(file_path), "content": str(content)}
            )

    for example in raw_examples(procedure):
        if not isinstance(example, dict):
            continue
        for step in example.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            tool_name = str(
                step.get("tool_name")
                or step.get("canonical_action")
                or step.get("canonical_name")
                or step.get("action")
                or ""
            )
            if not any(
                token in tool_name
                for token in ("fs_write", "write_file", "execute_fs_write")
            ):
                continue
            args = extract_tool_args(step)
            file_path = (
                args.get("file_path")
                or args.get("path")
                or args.get("filename")
            )
            content = args.get("content")
            if file_path and content:
                artifacts.append(
                    {"file_path": str(file_path), "content": str(content)}
                )

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for artifact in artifacts:
        key = (artifact["file_path"], artifact["content"])
        if key not in seen:
            seen.add(key)
            deduped.append(artifact)
    return deduped


def failed_attempts(procedure: Any) -> list[str]:
    failed = unique_strings(get_value(procedure, "failed_attempts"))
    for example in raw_examples(procedure):
        if not isinstance(example, dict):
            continue
        for step in example.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            observation = extract_observation(step).lower()
            if not any(
                marker in observation
                for marker in (
                    "fatal",
                    "error",
                    "failed",
                    "wrong",
                    "not found",
                    "timed out",
                )
            ):
                continue
            if any(
                marker in observation
                for marker in ("success", "successful", "passed")
            ):
                continue
            # Avoid false-positives from success summaries that mention
            # failure counts in the negative, e.g. "parsed 6/6 dates, 0 failed"
            # or "0 errors" or "no failures". The step actually succeeded;
            # the word "failed"/"error" appears only as part of a zero-count.
            if _is_failure_marker_negated(observation):
                continue
            args = extract_tool_args(step)
            if args.get("cmd"):
                failed.append(f"run `{args['cmd']}`")
            else:
                failed.append(
                    str(
                        step.get("tool_name")
                        or step.get("canonical_action")
                        or step.get("canonical_name")
                        or step.get("action")
                        or "unknown action"
                    )
                )
    return unique_strings(failed)


def _is_failure_marker_negated(observation: str) -> bool:
    """Return True when failure-marker words appear only as zero/negative counts.

    Examples that should be treated as NOT a failure:
      "parsed 6/6 dates, 0 failed"
      "0 errors, 0 warnings"
      "no failures detected"
      "exit=0 :: 0 failed, 0 errors"

    Examples that ARE real failures:
      "ImportError: no module named foo"
      "1 failed, 5 passed"
      "fatal: database is locked"
    """
    import re

    negation_patterns = [
        # "0 failed", "0 errors", "0 failures", "0 fatal"
        r"\b0\s+(failed|failures|errors?|fatal)\b",
        # "no failed", "no failures", "no errors"
        r"\bno\s+(failed|failures|errors?|fatal)\b",
        # "failed=0", "errors=0", "failures=0"
        r"\b(failed|failures|errors?)\s*=\s*0\b",
    ]
    for pattern in negation_patterns:
        if re.search(pattern, observation):
            return True
    return False


def raw_examples(procedure: Any) -> list[Any]:
    examples = (
        get_value(procedure, "trace_evidence")
        or get_value(procedure, "raw_examples")
        or get_value(procedure, "raw_supporting_examples")
        or get_value(procedure, "supporting_examples")
        or []
    )
    if isinstance(examples, str):
        try:
            decoded = json.loads(examples)
        except (TypeError, json.JSONDecodeError):
            return []
        return decoded if isinstance(decoded, list) else []
    return as_list(examples)


def ordered_artifacts_and_failures(
    procedure: Any,
) -> tuple[dict[int, dict[str, str]], dict[int, dict[str, Any]]]:
    """Extract artifact/failure evidence keyed by deterministic step order."""
    artifacts: dict[int, dict[str, str]] = {}
    failures: dict[int, dict[str, Any]] = {}
    for example in raw_examples(procedure):
        if not isinstance(example, dict):
            continue
        for step in example.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            try:
                ordering_index = int(step.get("ordering_index", 0))
            except (TypeError, ValueError):
                ordering_index = 0
            observation = extract_observation(step)
            lowered = observation.lower()
            is_failure = any(
                marker in lowered
                for marker in (
                    "fatal",
                    "error",
                    "failed",
                    "failure",
                    "command failed",
                    "does not exist",
                    "not found",
                )
            ) and not any(
                marker in lowered
                for marker in (
                    "success",
                    "successful",
                    "passed",
                    "healthy",
                    "online",
                )
            )
            if is_failure:
                failures[ordering_index] = step

            tool_name = str(
                step.get("tool_name")
                or step.get("canonical_action")
                or step.get("action")
                or ""
            )
            if not any(
                token in tool_name
                for token in ("fs_write", "write_file", "execute_fs_write")
            ):
                continue
            args = extract_tool_args(step)
            file_path = (
                args.get("file_path")
                or args.get("path")
                or args.get("filename")
            )
            content = args.get("content")
            if file_path and content:
                artifacts[ordering_index] = {
                    "file_path": str(file_path),
                    "content": str(content),
                }
    return artifacts, failures


def render_artifact(artifact: dict[str, str]) -> str:
    file_path = artifact["file_path"]
    language = "python" if file_path.endswith(".py") else ""
    return (
        f"write `{file_path}` with this exact content:\n\n"
        f"```{language}\n{artifact['content'].rstrip()}\n```"
    )


def command_from_step(
    step: dict[str, Any],
    bindings: dict[str, str] | None = None,
) -> str | None:
    args = extract_tool_args(step)
    command = args.get("cmd")
    if not command:
        return None
    rendered = str(command)
    for placeholder, replacement in (bindings or {}).items():
        rendered = rendered.replace(str(placeholder), str(replacement))
    return rendered.replace("data_1.zdat", "data_2.zdat")


def language_for_path(file_path: str) -> str:
    lower = str(file_path).lower()
    if lower.endswith(".py"):
        return "python"
    if lower.endswith(".sh"):
        return "bash"
    if lower.endswith(".json"):
        return "json"
    return ""
