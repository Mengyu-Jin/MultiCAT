from __future__ import annotations


ERROR_FAMILIES = (
    "scope_product",
    "missing_records",
    "merged_duplicate",
    "catalyst_assignment",
    "condition_unit",
    "evidence_schema",
)


def _labels(family: str, labels: str) -> dict[str, str]:
    return {label: family for label in labels.split()}


ERROR_LABEL_TO_FAMILY = {
    **_labels(
        "scope_product",
        "incorrect_scope_exclusion invalid_product invalid_product_name out_of_scope "
        "product_identity_mismatch product_mapping product_name_mismatch product_naming "
        "scope_violation wrong_product",
    ),
    **_labels(
        "missing_records",
        "data_extraction_error extraction_failure incomplete_extraction missing_catalyst "
        "missing_catalyst_variants missing_product missing_reaction",
    ),
    **_labels(
        "merged_duplicate",
        "aggregate_placeholder duplicate_conditions duplicate_data duplicate_metric "
        "duplicate_metrics duplicate_product_entry duplicate_product_name duplicate_reaction "
        "invalid_split merged_reactions merged_rows merged_table_rows",
    ),
    **_labels(
        "catalyst_assignment",
        "catalyst_mismatch inconsistent_catalyst_loading inconsistent_catalyst_naming "
        "invalid_catalyst invalid_catalyst_assignment invalid_catalyst_naming "
        "invalid_catalyst_reference orphaned_reaction",
    ),
    **_labels(
        "condition_unit",
        "ambiguous_conditions condition_mismatch inconsistent_condition_text "
        "inconsistent_conditions inconsistent_time incorrect_solvent incorrect_time_conversion "
        "missing_catalyst_amount missing_catalyst_loading missing_condition "
        "missing_condition_data missing_condition_detail missing_conditions "
        "missing_reaction_conditions missing_reaction_time missing_solvent solvent_volume_error "
        "unit_inconsistency",
    ),
    **_labels(
        "evidence_schema",
        "data_interpretation_error data_quality inconsistent_data inconsistent_evidence "
        "missing_evidence schema_violation",
    ),
}


def classify_error_label(label: str) -> str:
    try:
        return ERROR_LABEL_TO_FAMILY[label]
    except KeyError as exc:
        raise KeyError(f"Unregistered error label: {label}") from exc


def validate_taxonomy(observed_labels: set[str]) -> None:
    missing = observed_labels - set(ERROR_LABEL_TO_FAMILY)
    if missing:
        raise ValueError(f"Taxonomy mismatch; missing={sorted(missing)}")
    invalid = set(ERROR_LABEL_TO_FAMILY.values()) - set(ERROR_FAMILIES)
    if invalid:
        raise ValueError(f"Unknown error families: {sorted(invalid)}")
