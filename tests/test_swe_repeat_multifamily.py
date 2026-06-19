from benchmarks.swe_repeat.families import FAULT_FAMILIES
from benchmarks.swe_repeat.tasks import ALL_TASKS


def test_swe_repeat_multifamily_config_shape():
    family_names = [family.name for family in FAULT_FAMILIES]

    assert "node_export_broken" in family_names
    assert "package_json_test_script_missing" in family_names
    assert "json_config_syntax_broken" in family_names

    assert set(ALL_TASKS).issubset(set(family_names))
    assert sum(len(tasks) for tasks in ALL_TASKS.values()) >= 9


def test_each_family_has_expected_procedure():
    for family in FAULT_FAMILIES:
        assert family.expected_procedure
        assert family.expected_procedure[-1] == "run_tests"
