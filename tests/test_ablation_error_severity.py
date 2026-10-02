from multicat.ablation.error_severity import (
    ERROR_LABEL_TO_SEVERITY,
    SEVERITY_ORDER,
    highest_severity,
    reaction_index_from_path,
    reaction_indices_from_path,
    validate_severity_mapping,
)
from multicat.ablation.error_taxonomy import ERROR_LABEL_TO_FAMILY


def test_all_registered_error_labels_have_one_severity():
    validate_severity_mapping()
    assert set(ERROR_LABEL_TO_SEVERITY) == set(ERROR_LABEL_TO_FAMILY)
    assert set(ERROR_LABEL_TO_SEVERITY.values()) == set(SEVERITY_ORDER)


def test_reaction_index_is_only_returned_for_unique_reaction_paths():
    assert reaction_index_from_path("reactions[12]") == 12
    assert reaction_index_from_path("reactions[12].yield.value") == 12
    assert reaction_index_from_path("reactions") is None
    assert reaction_index_from_path("catalysts[0]") is None


def test_all_explicit_reaction_indices_are_recovered_from_pair_paths():
    assert reaction_indices_from_path("reactions[1] and reactions[5]") == (1, 5)
    assert reaction_indices_from_path("reactions[0], reactions[4]") == (0, 4)
    assert reaction_indices_from_path("reactions") == ()


def test_highest_severity_prevents_double_counting_a_reaction():
    assert highest_severity(["minor", "critical", "major"]) == "critical"
    assert highest_severity(["minor", "major"]) == "major"
