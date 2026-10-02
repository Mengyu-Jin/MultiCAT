from __future__ import annotations

import pytest

from multicat.ablation.error_taxonomy import (
    ERROR_FAMILIES,
    ERROR_LABEL_TO_FAMILY,
    classify_error_label,
    validate_taxonomy,
)


def test_taxonomy_is_exhaustive_and_mutually_exclusive_for_frozen_labels():
    frozen_labels = {
        "aggregate_placeholder", "ambiguous_conditions", "catalyst_mismatch",
        "condition_mismatch", "data_extraction_error", "data_interpretation_error",
        "data_quality", "duplicate_conditions", "duplicate_data", "duplicate_metric",
        "duplicate_metrics", "duplicate_product_entry", "duplicate_product_name",
        "duplicate_reaction", "extraction_failure", "incomplete_extraction",
        "inconsistent_catalyst_loading", "inconsistent_catalyst_naming",
        "inconsistent_condition_text", "inconsistent_conditions", "inconsistent_data",
        "inconsistent_evidence", "inconsistent_time", "incorrect_scope_exclusion",
        "incorrect_solvent", "incorrect_time_conversion", "invalid_catalyst",
        "invalid_catalyst_assignment", "invalid_catalyst_naming",
        "invalid_catalyst_reference", "invalid_product", "invalid_product_name",
        "invalid_split", "merged_reactions", "merged_rows", "merged_table_rows",
        "missing_catalyst", "missing_catalyst_amount", "missing_catalyst_loading",
        "missing_catalyst_variants", "missing_condition", "missing_condition_data",
        "missing_condition_detail", "missing_conditions", "missing_evidence",
        "missing_product", "missing_reaction", "missing_reaction_conditions",
        "missing_reaction_time", "missing_solvent", "orphaned_reaction", "out_of_scope",
        "product_identity_mismatch", "product_mapping", "product_name_mismatch",
        "product_naming", "schema_violation", "scope_violation", "solvent_volume_error",
        "unit_inconsistency", "wrong_product",
    }
    assert set(ERROR_LABEL_TO_FAMILY) == frozen_labels
    assert set(ERROR_LABEL_TO_FAMILY.values()) <= set(ERROR_FAMILIES)
    validate_taxonomy(frozen_labels)


def test_unknown_error_label_raises_instead_of_falling_back_to_other():
    with pytest.raises(KeyError, match="unregistered_error"):
        classify_error_label("unregistered_error")


def test_representative_labels_map_to_expected_families():
    assert classify_error_label("scope_violation") == "scope_product"
    assert classify_error_label("missing_reaction") == "missing_records"
    assert classify_error_label("merged_rows") == "merged_duplicate"
    assert classify_error_label("invalid_catalyst_assignment") == "catalyst_assignment"
    assert classify_error_label("incorrect_time_conversion") == "condition_unit"
    assert classify_error_label("missing_evidence") == "evidence_schema"

