from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from .error_severity import (
    ERROR_LABEL_TO_SEVERITY,
    highest_severity,
    reaction_indices_from_path,
    validate_severity_mapping,
)
from .error_taxonomy import (
    ERROR_FAMILIES,
    ERROR_LABEL_TO_FAMILY,
    classify_error_label,
)


VARIANTS = ("full", "no_judge", "no_repair", "extraction_only")
PAPER_LEVEL_FAMILIES = {"scope_product", "missing_records", "evidence_schema"}


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_figure7_tables(output_root: str | Path, table_root: str | Path) -> dict[str, Path]:
    output_root = Path(output_root)
    table_root = Path(table_root)
    validate_severity_mapping()

    paper_ids = sorted(path.stem for path in (output_root / "audit/reports/full").glob("*.json"))
    if len(paper_ids) != 50:
        raise ValueError(f"Expected 50 paired papers, found {len(paper_ids)}.")

    severity_rows: list[dict] = []
    family_rows: list[dict] = []
    ablation_rows: list[dict] = []
    for variant in VARIANTS:
        variant_ids = sorted(
            path.stem for path in (output_root / "audit/reports" / variant).glob("*.json")
        )
        if variant_ids != paper_ids:
            raise ValueError(f"Variant {variant} does not contain the paired 50-paper set.")

        usable_reactions = 0
        usable_papers = 0
        papers_with_audit_issues = 0
        total_audit_issues = 0
        affected: dict[tuple[str, int], list[str]] = defaultdict(list)
        paper_family_hits: dict[str, set[str]] = defaultdict(set)
        reaction_family_hits: dict[str, set[tuple[str, int]]] = defaultdict(set)

        for paper_id in paper_ids:
            result = _load(output_root / "variants" / variant / "results" / f"{paper_id}.json")
            extraction = _load(
                output_root / "variants" / variant / "papers" / paper_id / "07_extraction.json"
            )
            report = _load(output_root / "audit/reports" / variant / f"{paper_id}.json")
            usable = result.get("status") == "usable"
            reactions = extraction.get("reactions") or []
            if usable:
                usable_papers += 1
                usable_reactions += len(reactions)
            issues = report.get("issues") or []
            papers_with_audit_issues += int(bool(issues))
            total_audit_issues += len(issues)

            for issue in issues:
                label = issue.get("issue_type") or issue.get("type")
                family = classify_error_label(label)
                if family in PAPER_LEVEL_FAMILIES:
                    paper_family_hits[family].add(paper_id)
                reaction_indices = reaction_indices_from_path(issue.get("path"))
                for reaction_index in reaction_indices:
                    if usable and reaction_index < len(reactions):
                        key = (paper_id, reaction_index)
                        affected[key].append(ERROR_LABEL_TO_SEVERITY[label])
                        if family not in PAPER_LEVEL_FAMILIES:
                            reaction_family_hits[family].add(key)

        severity_counts = Counter(highest_severity(values) for values in affected.values())
        severity_rows.append(
            {
                "variant": variant,
                "usable_reactions": usable_reactions,
                "critical_reactions": severity_counts["critical"],
                "major_reactions": severity_counts["major"],
                "minor_reactions": severity_counts["minor"],
                "affected_usable_reactions": len(affected),
                "affected_reaction_rate": len(affected) / usable_reactions if usable_reactions else 0,
            }
        )

        for family in ERROR_FAMILIES:
            paper_level = family in PAPER_LEVEL_FAMILIES
            numerator = (
                len(paper_family_hits[family])
                if paper_level
                else len(reaction_family_hits[family])
            )
            denominator = len(paper_ids) if paper_level else usable_reactions
            family_rows.append(
                {
                    "variant": variant,
                    "error_family": family,
                    "analysis_level": "paper" if paper_level else "reaction",
                    "numerator": numerator,
                    "denominator": denominator,
                    "rate": numerator / denominator if denominator else 0,
                }
            )

        ablation_rows.append(
            {
                "variant": variant,
                "usable_papers": usable_papers,
                "paper_retention_rate": usable_papers / len(paper_ids),
                "usable_reactions": usable_reactions,
                "reaction_retention_rate": 0.0,
                "papers_with_audit_issues": papers_with_audit_issues,
                "audit_issue_paper_rate": papers_with_audit_issues / len(paper_ids),
                "absolute_change_vs_full": 0.0,
                "total_audit_issues": total_audit_issues,
            }
        )

    extraction_reactions = next(
        row["usable_reactions"] for row in ablation_rows if row["variant"] == "extraction_only"
    )
    full_issue_rate = next(
        row["audit_issue_paper_rate"] for row in ablation_rows if row["variant"] == "full"
    )
    for row in ablation_rows:
        row["reaction_retention_rate"] = row["usable_reactions"] / extraction_reactions
        row["absolute_change_vs_full"] = round(
            row["audit_issue_paper_rate"] - full_issue_rate, 10
        )

    full_results = [
        _load(output_root / "variants/full/results" / f"{paper_id}.json")
        for paper_id in paper_ids
    ]
    repair_counter = Counter()
    for result in full_results:
        attempts = int(result.get("repair_attempts") or 0)
        usable = result.get("status") == "usable"
        if usable and attempts == 0:
            outcome = "usable_without_repair"
        elif usable and attempts == 1:
            outcome = "usable_after_one_attempt"
        elif usable and attempts == 2:
            outcome = "usable_after_two_attempts"
        elif not usable and attempts == 2:
            outcome = "rejected_after_two_attempts"
        else:
            raise ValueError(f"Unexpected full-workflow outcome: {result}")
        repair_counter[outcome] += 1
    repair_rows = [
        {"outcome": outcome, "paper_count": repair_counter[outcome], "paper_rate": repair_counter[outcome] / 50}
        for outcome in (
            "usable_without_repair",
            "usable_after_one_attempt",
            "usable_after_two_attempts",
            "rejected_after_two_attempts",
        )
    ]

    mapping_rows = [
        {
            "raw_error_label": label,
            "error_family": ERROR_LABEL_TO_FAMILY[label],
            "severity": ERROR_LABEL_TO_SEVERITY[label],
        }
        for label in sorted(ERROR_LABEL_TO_FAMILY)
    ]
    paths = {
        "severity": table_root / "record_level_error_severity.csv",
        "families": table_root / "error_family_standardized_rates.csv",
        "repair": table_root / "repair_attempt_outcomes.csv",
        "mapping": table_root / "error_severity_mapping.csv",
        "ablation": table_root / "workflow_ablation_summary.csv",
    }
    _write_csv(paths["severity"], severity_rows, list(severity_rows[0]))
    _write_csv(paths["families"], family_rows, list(family_rows[0]))
    _write_csv(paths["repair"], repair_rows, list(repair_rows[0]))
    _write_csv(paths["mapping"], mapping_rows, list(mapping_rows[0]))
    _write_csv(paths["ablation"], ablation_rows, list(ablation_rows[0]))
    return paths
