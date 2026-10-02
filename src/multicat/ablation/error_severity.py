from __future__ import annotations

import re

from .error_taxonomy import ERROR_LABEL_TO_FAMILY


SEVERITY_ORDER = ("minor", "major", "critical")

MINOR_LABELS = {
    "inconsistent_catalyst_naming",
    "invalid_catalyst_naming",
    "product_naming",
    "schema_violation",
}

MAJOR_LABELS = {
    label
    for label, family in ERROR_LABEL_TO_FAMILY.items()
    if family in {"condition_unit", "evidence_schema"}
} | {
    "data_extraction_error",
    "data_interpretation_error",
    "data_quality",
    "extraction_failure",
    "incomplete_extraction",
    "inconsistent_catalyst_loading",
    "missing_catalyst_amount",
    "missing_catalyst_loading",
    "missing_condition",
    "missing_condition_data",
    "missing_condition_detail",
    "missing_conditions",
    "missing_reaction_conditions",
    "missing_reaction_time",
    "orphaned_reaction",
}

ERROR_LABEL_TO_SEVERITY = {
    label: (
        "minor"
        if label in MINOR_LABELS
        else "major"
        if label in MAJOR_LABELS
        else "critical"
    )
    for label in ERROR_LABEL_TO_FAMILY
}


def validate_severity_mapping() -> None:
    labels = set(ERROR_LABEL_TO_FAMILY)
    mapped = set(ERROR_LABEL_TO_SEVERITY)
    if labels != mapped:
        raise ValueError(
            f"Severity mapping mismatch; missing={sorted(labels - mapped)}, "
            f"extra={sorted(mapped - labels)}"
        )
    invalid = set(ERROR_LABEL_TO_SEVERITY.values()) - set(SEVERITY_ORDER)
    if invalid:
        raise ValueError(f"Unknown severity levels: {sorted(invalid)}")


def reaction_index_from_path(path: str | None) -> int | None:
    match = re.match(r"^reactions\[(\d+)\](?:\.|$)", path or "")
    return int(match.group(1)) if match else None


def reaction_indices_from_path(path: str | None) -> tuple[int, ...]:
    return tuple(dict.fromkeys(int(value) for value in re.findall(r"reactions\[(\d+)\]", path or "")))


def highest_severity(severities: list[str]) -> str:
    if not severities:
        raise ValueError("At least one severity is required.")
    rank = {severity: index for index, severity in enumerate(SEVERITY_ORDER)}
    unknown = set(severities) - set(rank)
    if unknown:
        raise ValueError(f"Unknown severity levels: {sorted(unknown)}")
    return max(severities, key=rank.__getitem__)
