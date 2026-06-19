from __future__ import annotations

from benchmarks.swe_repeat.families import RepoSpec


NODE_EXPORT_TASKS = [
    RepoSpec(
        name="is-number",
        url="https://github.com/jonschlinkert/is-number.git",
        target_file="index.js",
        install_command=["npm", "install"],
        test_command=["npm", "test"],
    ),
    RepoSpec(
        name="kind-of",
        url="https://github.com/jonschlinkert/kind-of.git",
        target_file="index.js",
        install_command=["npm", "install"],
        test_command=["npm", "test"],
    ),
    RepoSpec(
        name="is-primitive",
        url="https://github.com/jonschlinkert/is-primitive.git",
        target_file="index.js",
        install_command=["npm", "install"],
        test_command=["npm", "test"],
    ),
]



PACKAGE_JSON_TEST_SCRIPT_TASKS = [
    RepoSpec(
        name="is-number",
        url="https://github.com/jonschlinkert/is-number.git",
        target_file="package.json",
        install_command=["npm", "install"],
        test_command=["npm", "test"],
    ),
    RepoSpec(
        name="kind-of",
        url="https://github.com/jonschlinkert/kind-of.git",
        target_file="package.json",
        install_command=["npm", "install"],
        test_command=["npm", "test"],
    ),
    RepoSpec(
        name="is-primitive",
        url="https://github.com/jonschlinkert/is-primitive.git",
        target_file="package.json",
        install_command=["npm", "install"],
        test_command=["npm", "test"],
    ),
]



JSON_CONFIG_SYNTAX_TASKS = [
    RepoSpec(
        name="is-number",
        url="https://github.com/jonschlinkert/is-number.git",
        target_file="package.json",
        install_command=["npm", "install"],
        test_command=["npm", "test"],
    ),
    RepoSpec(
        name="kind-of",
        url="https://github.com/jonschlinkert/kind-of.git",
        target_file="package.json",
        install_command=["npm", "install"],
        test_command=["npm", "test"],
    ),
    RepoSpec(
        name="is-primitive",
        url="https://github.com/jonschlinkert/is-primitive.git",
        target_file="package.json",
        install_command=["npm", "install"],
        test_command=["npm", "test"],
    ),
]


ALL_TASKS = {
    "node_export_broken": NODE_EXPORT_TASKS,
    "package_json_test_script_missing": PACKAGE_JSON_TEST_SCRIPT_TASKS,
    "json_config_syntax_broken": JSON_CONFIG_SYNTAX_TASKS,
}
