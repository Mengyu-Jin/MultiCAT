from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from .error_taxonomy import (
    ERROR_FAMILIES,
    ERROR_LABEL_TO_FAMILY,
    classify_error_label,
    validate_taxonomy,
)
from .paired_statistics import exact_mcnemar, holm_adjust, wilson_interval


VARIANTS = ("full", "no_judge", "no_repair", "extraction_only")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_analysis_tables(output_root: Path, table_root: Path) -> dict[str, Path]:
    report_ids = {
        variant: {path.stem for path in (output_root / "audit" / "reports" / variant).glob("*.json")}
        for variant in VARIANTS
    }
    if not report_ids["full"] or any(ids != report_ids["full"] for ids in report_ids.values()):
        raise ValueError("All four variants must contain the same paired paper IDs.")
    paper_ids = sorted(report_ids["full"])

    observed_labels: set[str] = set()
    reports: dict[tuple[str, str], dict] = {}
    for variant in VARIANTS:
        for paper_id in paper_ids:
            report_path = output_root / "audit" / "reports" / variant / f"{paper_id}.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            reports[(variant, paper_id)] = report
            for issue in report.get("issues") or []:
                observed_labels.add(issue.get("issue_type") or issue.get("type"))
    validate_taxonomy(observed_labels)

    mapping_rows = [
        {"raw_error_label": label, "error_family": family}
        for label, family in sorted(ERROR_LABEL_TO_FAMILY.items())
    ]

    paper_rows: list[dict] = []
    family_summary: Counter[tuple[str, str]] = Counter()
    for variant in VARIANTS:
        for paper_id in paper_ids:
            report = reports[(variant, paper_id)]
            issues = report.get("issues") or []
            family_counts = Counter(
                classify_error_label(issue.get("issue_type") or issue.get("type"))
                for issue in issues
            )
            for family, count in family_counts.items():
                family_summary[(variant, family)] += count
            result = json.loads(
                (output_root / "variants" / variant / "results" / f"{paper_id}.json").read_text(
                    encoding="utf-8"
                )
            )
            extraction = json.loads(
                (
                    output_root
                    / "variants"
                    / variant
                    / "papers"
                    / paper_id
                    / "07_extraction.json"
                ).read_text(encoding="utf-8")
            )
            paper_rows.append(
                {
                    "paper_id": paper_id,
                    "variant": variant,
                    "usable": int(result.get("status") == "usable"),
                    "reaction_count": len(extraction.get("reactions") or []),
                    "has_error": int(bool(issues)),
                    "total_error_count": len(issues),
                    **{f"{family}_count": family_counts.get(family, 0) for family in ERROR_FAMILIES},
                }
            )

    family_rows = [
        {
            "variant": variant,
            "error_family": family,
            "issue_count": family_summary[(variant, family)],
            "papers_with_family_error": sum(
                row[f"{family}_count"] > 0 for row in paper_rows if row["variant"] == variant
            ),
        }
        for variant in VARIANTS
        for family in ERROR_FAMILIES
    ]

    rate_rows: list[dict] = []
    errors_by_variant: dict[str, list[bool]] = {}
    for variant in VARIANTS:
        rows = [row for row in paper_rows if row["variant"] == variant]
        errors = [bool(row["has_error"]) for row in rows]
        errors_by_variant[variant] = errors
        count = sum(errors)
        low, high = wilson_interval(count, len(rows))
        rate_rows.append(
            {
                "variant": variant,
                "n_papers": len(rows),
                "papers_with_error": count,
                "error_rate": count / len(rows),
                "wilson_ci_low": low,
                "wilson_ci_high": high,
                "usable_papers": sum(row["usable"] for row in rows),
                "usable_reactions": sum(
                    row["reaction_count"] for row in rows if row["usable"]
                ),
            }
        )

    comparisons = VARIANTS[1:]
    mcnemar = [exact_mcnemar(errors_by_variant["full"], errors_by_variant[v]) for v in comparisons]
    adjusted = holm_adjust([result.p_value for result in mcnemar])
    paired_rows = [
        {
            "reference": "full",
            "comparator": variant,
            "n_pairs": len(paper_ids),
            "full_clean_comparator_error": result.full_clean_comparator_error,
            "full_error_comparator_clean": result.full_error_comparator_clean,
            "discordant_pairs": result.discordant_pairs,
            "mcnemar_exact_p": result.p_value,
            "holm_adjusted_p": adjusted[index],
        }
        for index, (variant, result) in enumerate(zip(comparisons, mcnemar))
    ]

    paths = {
        "mapping": table_root / "error_taxonomy_mapping.csv",
        "family_summary": table_root / "error_family_by_variant.csv",
        "paper_level": table_root / "paper_level_paired_metrics.csv",
        "rate_summary": table_root / "workflow_rate_summary.csv",
        "paired_tests": table_root / "paired_statistical_tests.csv",
    }
    _write_csv(paths["mapping"], mapping_rows, ["raw_error_label", "error_family"])
    _write_csv(
        paths["family_summary"],
        family_rows,
        ["variant", "error_family", "issue_count", "papers_with_family_error"],
    )
    _write_csv(paths["paper_level"], paper_rows, list(paper_rows[0]))
    _write_csv(paths["rate_summary"], rate_rows, list(rate_rows[0]))
    _write_csv(paths["paired_tests"], paired_rows, list(paired_rows[0]))
    return paths
