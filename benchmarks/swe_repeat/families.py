from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class RepoSpec:
    name: str
    url: str
    target_file: str
    install_command: list[str]
    test_command: list[str]


@dataclass(frozen=True)
class FaultFamily:
    name: str
    description: str
    inject: Callable[[Path, RepoSpec], bool]
    repair: Callable[[Path, RepoSpec], bool]
    expected_procedure: list[str]


def replace_in_file(path: Path, old: str, new: str) -> bool:
    if not path.exists():
        return False

    text = path.read_text(errors="ignore")
    if old not in text:
        return False

    path.write_text(text.replace(old, new, 1))
    return True


def repair_replace_in_file(path: Path, broken: str, fixed: str) -> bool:
    if not path.exists():
        return False

    text = path.read_text(errors="ignore")
    if broken not in text:
        return False

    path.write_text(text.replace(broken, fixed, 1))
    return True


def inject_node_export_break(repo: Path, spec: RepoSpec) -> bool:
    target = repo / spec.target_file
    return replace_in_file(
        target,
        "module.exports = function",
        "module.exports_broken = function",
    )


def repair_node_export_break(repo: Path, spec: RepoSpec) -> bool:
    target = repo / spec.target_file
    return repair_replace_in_file(
        target,
        "module.exports_broken = function",
        "module.exports = function",
    )


NODE_EXPORT_BROKEN = FaultFamily(
    name="node_export_broken",
    description="Breaks a CommonJS module export so tests fail until the export is restored.",
    inject=inject_node_export_break,
    repair=repair_node_export_break,
    expected_procedure=[
        "check_target_file",
        "fix_target_file",
        "run_tests",
    ],
)


def inject_package_json_test_script_missing(repo: Path, spec: RepoSpec) -> bool:
    target = repo / "package.json"
    if not target.exists():
        return False

    text = target.read_text(errors="ignore")
    if '"test"' not in text:
        return False

    # Rename the test script key so `npm test` no longer works.
    target.write_text(text.replace('"test"', '"test_broken"', 1))
    return True


def repair_package_json_test_script_missing(repo: Path, spec: RepoSpec) -> bool:
    target = repo / "package.json"
    if not target.exists():
        return False

    text = target.read_text(errors="ignore")
    if '"test_broken"' not in text:
        return False

    target.write_text(text.replace('"test_broken"', '"test"', 1))
    return True


PACKAGE_JSON_TEST_SCRIPT_MISSING = FaultFamily(
    name="package_json_test_script_missing",
    description="Renames the package.json test script so npm test fails until the test script is restored.",
    inject=inject_package_json_test_script_missing,
    repair=repair_package_json_test_script_missing,
    expected_procedure=[
        "check_package_json",
        "fix_package_json_test_script",
        "run_tests",
    ],
)


def inject_json_config_syntax_broken(repo: Path, spec: RepoSpec) -> bool:
    target = repo / spec.target_file
    if not target.exists():
        return False

    text = target.read_text(errors="ignore").strip()
    if not text:
        return False

    # Break JSON syntax by removing the final closing brace/bracket.
    if text.endswith("}"):
        target.write_text(text[:-1])
        return True

    if text.endswith("]"):
        target.write_text(text[:-1])
        return True

    return False


def repair_json_config_syntax_broken(repo: Path, spec: RepoSpec) -> bool:
    target = repo / spec.target_file
    if not target.exists():
        return False

    text = target.read_text(errors="ignore").strip()
    if not text:
        return False

    # Repair by balancing the outer JSON delimiter. Checking only
    # text.endswith("}") is insufficient because removing the final outer
    # brace can still leave the file ending with an inner object brace.
    if text.startswith("{"):
        missing = text.count("{") - text.count("}")
        if missing > 0:
            target.write_text(text + ("}" * missing))
            return True

    if text.startswith("["):
        missing = text.count("[") - text.count("]")
        if missing > 0:
            target.write_text(text + ("]" * missing))
            return True

    return False


JSON_CONFIG_SYNTAX_BROKEN = FaultFamily(
    name="json_config_syntax_broken",
    description="Breaks JSON config syntax so tests or package tooling fail until the config is repaired.",
    inject=inject_json_config_syntax_broken,
    repair=repair_json_config_syntax_broken,
    expected_procedure=[
        "check_json_config",
        "fix_json_syntax",
        "run_tests",
    ],
)


FAULT_FAMILIES = [
    NODE_EXPORT_BROKEN,
    PACKAGE_JSON_TEST_SCRIPT_MISSING,
    JSON_CONFIG_SYNTAX_BROKEN,
]
