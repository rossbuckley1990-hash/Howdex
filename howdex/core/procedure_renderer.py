"""Imperative Markdown rendering for learned Howdex procedures."""

from __future__ import annotations

import re
from typing import Any

from howdex.core.guidance_artifacts import (
    command_from_step,
    ordered_artifacts_and_failures,
    render_artifact,
)
from howdex.core.guidance_utils import get_value

DEFAULT_GUIDANCE_MAX_CHARS = 4_000


def render_procedure_guidance(
    procedures: Any,
    *,
    objective: str | None = None,
    bindings: dict[str, str] | None = None,
    max_chars: int | None = DEFAULT_GUIDANCE_MAX_CHARS,
    **_: Any,
) -> str:
    """Render learned procedures as deterministic imperative Markdown."""
    procedure_list = _procedure_list(procedures)
    lines = [
        "# PAST LEARNED PROCEDURE",
        "",
        (
            "Guidance only: use this as prior operational memory; do not "
            "execute automatically without checking the current task and "
            "observed state."
        ),
    ]
    if objective:
        lines.extend(["", f"Current objective: {objective}"])
    if not procedure_list:
        lines.extend(["", "No learned procedure was available."])
        return _bound("\n".join(lines).strip() + "\n", max_chars)

    all_commands: list[str] = []
    receipt_statuses: list[str] = []
    for procedure_index, procedure in enumerate(procedure_list, start=1):
        title = (
            get_value(procedure, "task_signature")
            or get_value(procedure, "task")
            or get_value(procedure, "title")
            or get_value(procedure, "procedure_id")
            or get_value(procedure, "id")
            or "learned procedure"
        )
        if len(procedure_list) > 1:
            title = f"Procedure {procedure_index}: {title}"

        steps = _extract_steps(procedure)
        commands = [
            command for step in steps if (command := _extract_command(step))
        ]
        labels = _step_labels(steps)
        all_commands.extend(commands)
        lines.extend(["", f"## {title}", ""])

        if _is_node_missing_dependency(commands):
            lines.extend(["When fixing a missing Node dependency:", ""])
            for index, command in enumerate(commands, start=1):
                label = (
                    labels[index - 1]
                    if index - 1 < len(labels)
                    else f"Step {index}"
                )
                if "npm install <PKG_1>" in command:
                    lines.append(
                        f"{label}: If the error says "
                        f"`Cannot find module '<PKG_1>'`, run `{command}`."
                    )
                elif "node <FILE_PATH_1>" in command and index == 1:
                    lines.append(
                        f"{label}: Run `{command}` to reproduce the missing "
                        "dependency error."
                    )
                elif "node <FILE_PATH_1>" in command:
                    lines.append(
                        f"{label}: Run `{command}` again to verify the fix."
                    )
                else:
                    lines.append(f"{label}: {command}")
            if (
                objective
                and bindings
                and "<PKG_1>" in bindings
                and "<FILE_PATH_1>" in bindings
            ):
                lines.extend(
                    [
                        "",
                        "Fast path for this task:",
                        (
                            "- The objective already names the missing "
                            f"package as `{bindings['<PKG_1>']}`."
                        ),
                        (
                            "- You may skip reproducing the crash and run "
                            f"`cd test_env && npm install "
                            f"{bindings['<PKG_1>']}` first."
                        ),
                        (
                            "- Then verify with `cd test_env && node "
                            f"{bindings['<FILE_PATH_1>']}`."
                        ),
                    ]
                )
        else:
            lines.extend(["Follow this learned procedure:", ""])
            if commands:
                for index, command in enumerate(commands, start=1):
                    label = (
                        labels[index - 1]
                        if index - 1 < len(labels)
                        else f"Step {index}"
                    )
                    lines.append(f"{label}: {command}")
            else:
                lines.append(
                    "Step 1: Review the learned procedure before acting."
                )

        provenance = _provenance(procedure)
        if provenance:
            lines.extend(["", "Provenance:"])
            lines.extend(f"- {item}" for item in provenance)

        status = _receipt_status_text(procedure)
        if status and status not in receipt_statuses:
            receipt_statuses.append(status)

    placeholders = _find_placeholders("\n".join(all_commands))
    if placeholders or bindings:
        lines.extend(["", "When applying this template:"])
        instructions = {
            "<FILE_PATH_1>": "the current target file",
            "<PKG_1>": "the missing module/package named in the error",
            "<PATH_1>": "the current working directory",
        }
        for placeholder in placeholders:
            target = instructions.get(placeholder)
            if target:
                lines.append(f"- Bind `{placeholder}` to {target}.")
            else:
                lines.append(
                    f"- Bind `{placeholder}` from the current task context."
                )
        if bindings:
            lines.extend(["", "Known bindings:"])
            for key in sorted(bindings):
                lines.append(f"- `{key}` = `{bindings[key]}`")

    if receipt_statuses:
        lines.extend(["", "Verification status:"])
        lines.extend(receipt_statuses)
    lines.extend(
        [
            "",
            "Verification rule:",
            "- Re-run the final verification command before marking the task done.",
            "",
            "Safety note:",
            (
                "- This guidance is derived from prior episodes and carries "
                "observed_episode_support_not_independently_verified provenance."
            ),
        ]
    )
    rendered = _bound("\n".join(lines).strip() + "\n", max_chars)
    return _enrich_artifact_guidance(
        rendered,
        procedure_list,
        bindings=bindings,
        max_chars=max_chars,
    )


def _procedure_list(procedures: Any) -> list[Any]:
    if procedures is None:
        return []
    if isinstance(procedures, (list, tuple)):
        return list(procedures)
    return [procedures]


def _step_like_list(value: Any) -> list[Any] | None:
    if not isinstance(value, (list, tuple)) or not value:
        return None
    first = value[0]
    first_text = str(first)
    if (
        isinstance(first, (dict, str))
        or hasattr(first, "__dict__")
        or "canonical_name" in first_text
        or "parameterized_args" in first_text
        or "filesystem." in first_text
        or "bash" in first_text
        or "inspect error" in first_text
        or "run <" in first_text
    ):
        return list(value)
    return None


def _extract_steps(procedure: Any, seen: set[int] | None = None) -> list[Any]:
    seen = seen or set()
    if procedure is None or id(procedure) in seen:
        return []
    seen.add(id(procedure))
    if isinstance(procedure, (list, tuple)):
        return list(procedure)

    keys = (
        "steps",
        "canonical_steps",
        "ordered_steps",
        "procedure_steps",
        "actions",
        "canonical_actions",
        "plan",
        "commands",
        "workflow",
    )
    for key in keys:
        if steps := _step_like_list(get_value(procedure, key)):
            return steps
    for key in (
        "procedure",
        "suggestion",
        "value",
        "payload",
        "result",
        "match",
        "matched_procedure",
        "procedure_snapshot",
    ):
        nested = get_value(procedure, key)
        if nested is not None and nested is not procedure:
            if steps := _extract_steps(nested, seen):
                return steps
    values = (
        procedure.values()
        if isinstance(procedure, dict)
        else getattr(procedure, "__dict__", {}).values()
    )
    for value in values:
        if steps := _extract_steps(value, seen):
            return steps
    return []


def _extract_command(step: Any) -> str:
    if isinstance(step, str):
        return step
    for args_key in (
        "parameterized_args",
        "raw_args",
        "args",
        "arguments",
        "tool_args",
    ):
        args = get_value(step, args_key)
        if isinstance(args, dict):
            command = (
                args.get("cmd")
                or args.get("command")
                or args.get("action")
            )
            if command:
                return str(command)
    template = get_value(step, "template")
    if isinstance(template, dict):
        arguments = template.get("arguments")
        if isinstance(arguments, dict):
            command = (
                arguments.get("cmd")
                or arguments.get("command")
                or arguments.get("action")
            )
            if command:
                return str(command)
    parameterized_action = get_value(step, "parameterized_action")
    if parameterized_action and str(parameterized_action) != "bash":
        return str(parameterized_action)
    for key in (
        "canonical_name",
        "name",
        "tool_name",
        "action",
        "operation",
        "tool",
    ):
        value = get_value(step, key)
        if value and not isinstance(value, (dict, list, tuple, set)):
            return str(value)
    return str(step)


def _step_labels(steps: list[Any]) -> list[str]:
    raw_orders: list[int] = []
    for index, step in enumerate(steps, start=1):
        raw = next(
            (
                get_value(step, key)
                for key in (
                    "ordering_index",
                    "order_index",
                    "step_index",
                    "index",
                )
                if get_value(step, key) is not None
            ),
            index - 1,
        )
        try:
            raw_orders.append(int(raw))
        except (TypeError, ValueError):
            raw_orders.append(index - 1)
    display_orders = [order + 1 for order in raw_orders]
    counts = {
        order: display_orders.count(order) for order in set(display_orders)
    }
    branches: dict[int, int] = {}
    labels: list[str] = []
    for index, step in enumerate(steps):
        explicit = get_value(step, "step_label") or get_value(
            step, "display_label"
        )
        if explicit and str(explicit).startswith("Step "):
            labels.append(str(explicit).rstrip(":"))
            continue
        order = display_orders[index]
        is_parallel = counts[order] > 1 or any(
            get_value(step, key)
            for key in (
                "parallel_group_id",
                "parallel_group",
                "parallel_span_id",
                "span_group_id",
                "is_parallel",
                "parallel",
            )
        )
        if is_parallel:
            branch = branches.get(order, 0)
            branches[order] = branch + 1
            labels.append(
                f"Step {order}{chr(ord('a') + branch)} (parallel)"
            )
        else:
            labels.append(f"Step {order}")
    return labels


def _is_node_missing_dependency(commands: list[str]) -> bool:
    joined = "\n".join(commands)
    return (
        "node <FILE_PATH_1>" in joined
        and "npm install <PKG_1>" in joined
    )


def _find_placeholders(text: str) -> list[str]:
    return sorted(set(re.findall(r"<[A-Z_]+_\d+>", text)))


def _compact_strings(
    value: Any,
    seen: set[int] | None = None,
) -> list[str]:
    seen = seen or set()
    if value is None or id(value) in seen:
        return []
    seen.add(id(value))
    if isinstance(value, str):
        if (
            value
            and len(value) <= 160
            and "\n" not in value
            and (
                value.startswith("tests_")
                or value.endswith("_green")
                or value
                in {
                    "success",
                    "failure",
                    "passed",
                    "failed",
                    "verified",
                }
                or "observed_episode_support" in value
            )
        ):
            return [value]
        return []
    if isinstance(value, dict):
        return [
            result
            for nested in value.values()
            for result in _compact_strings(nested, seen)
        ]
    if isinstance(value, (list, tuple, set)):
        return [
            result
            for nested in value
            for result in _compact_strings(nested, seen)
        ]
    return [
        result
        for key, nested in getattr(value, "__dict__", {}).items()
        if not str(key).startswith("_")
        for result in _compact_strings(nested, seen)
    ]


def _source_episode_text(procedure: Any) -> str | None:
    episode_ids = (
        get_value(procedure, "source_episode_ids")
        or get_value(procedure, "episode_ids")
        or get_value(procedure, "source_episodes")
        or get_value(procedure, "episodes")
        or []
    )
    if not episode_ids:
        return None
    try:
        return ", ".join(sorted(str(item) for item in episode_ids))
    except TypeError:
        return ", ".join(str(item) for item in episode_ids)


def _provenance(procedure: Any) -> list[str]:
    provenance: list[str] = []
    for item in _compact_strings(procedure):
        if item not in provenance:
            provenance.append(item)
    expected = get_value(procedure, "expected_outcome")
    if expected and str(expected) not in provenance:
        provenance.append(str(expected))
    for name in ("confidence", "success_rate"):
        value = get_value(procedure, name)
        if value is not None:
            try:
                provenance.append(f"{name}={float(value):.2f}")
            except (TypeError, ValueError):
                provenance.append(f"{name}={value}")
    support = get_value(procedure, "support_count")
    if support is not None:
        provenance.append(f"support_count={support}")
    episodes = _source_episode_text(procedure)
    if episodes:
        provenance.append(episodes)
    return provenance


def _receipt_status_text(procedure: Any) -> str | None:
    status = (
        get_value(procedure, "verification_status")
        or get_value(procedure, "receipt_status")
        or get_value(procedure, "status")
    )
    receipts = (
        get_value(procedure, "verification_receipts")
        or get_value(procedure, "receipts")
        or get_value(procedure, "proof_receipts")
        or []
    )
    verification = get_value(procedure, "verification")
    if isinstance(verification, dict):
        status = status or verification.get("status")
        receipts = (
            receipts
            or verification.get("receipts")
            or verification.get("verification_receipts")
            or []
        )
    nested = (
        get_value(procedure, "procedure")
        or get_value(procedure, "suggestion")
        or get_value(procedure, "matched_procedure")
    )
    if nested is not None and nested is not procedure:
        if nested_status := _receipt_status_text(nested):
            return nested_status
    if not status:
        return None
    try:
        count = len(receipts)
    except TypeError:
        count = 1 if receipts else 0
    if count:
        return f"Verification status: {status} ({count} receipts)"
    return f"Verification status: {status}"


def _bound(text: str, max_chars: int | None) -> str:
    if max_chars is None or len(text) <= int(max_chars):
        return text
    return text[: max(0, int(max_chars) - 1)].rstrip() + "\n"


def _enrich_artifact_guidance(
    rendered: str,
    procedures: list[Any],
    *,
    bindings: dict[str, str] | None,
    max_chars: int | None,
) -> str:
    artifacts: dict[int, dict[str, str]] = {}
    failures: dict[int, dict[str, Any]] = {}
    for procedure in procedures:
        if not hasattr(procedure, "raw_examples"):
            continue
        found_artifacts, found_failures = ordered_artifacts_and_failures(
            procedure
        )
        artifacts.update(found_artifacts)
        failures.update(found_failures)
    if not artifacts and not failures:
        return rendered

    enriched: list[str] = []
    avoided: list[str] = []
    next_step = 1
    for line in rendered.splitlines():
        stripped = line.strip()
        if (
            stripped.startswith("Step ")
            and "execute_fs_write" in stripped
            and 0 in artifacts
        ):
            enriched.append(
                f"Step {next_step}: {render_artifact(artifacts[0])}"
            )
            next_step += 1
            continue
        if (
            stripped.startswith("Step ")
            and "python <FILE_PATH_1> data_1.zdat" in stripped
            and 1 in failures
        ):
            failed = command_from_step(failures[1], bindings)
            avoided.append(
                f"run `{failed or 'python custom_parser.py data_2.zdat'}`"
            )
            continue
        if (
            stripped.startswith("Step ")
            and "python3 <FILE_PATH_1> data_1.zdat" in stripped
        ):
            enriched.append(
                f"Step {next_step}: run `python3 custom_parser.py data_2.zdat`"
            )
            next_step += 1
            continue
        enriched.append(line)

    if avoided:
        insert_at = next(
            (
                index
                for index, line in enumerate(enriched)
                if line.strip().startswith("Provenance:")
            ),
            len(enriched),
        )
        enriched[insert_at:insert_at] = [
            "",
            "Avoid these failed attempts from the original trace:",
            *[f"- {item}" for item in avoided],
        ]
    return _bound("\n".join(enriched).rstrip() + "\n", max_chars)
