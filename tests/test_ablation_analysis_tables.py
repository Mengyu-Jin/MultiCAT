from __future__ import annotations

import csv
import json
from pathlib import Path

from multicat.ablation.analysis_tables import build_analysis_tables


def test_build_analysis_tables_preserves_pairing_and_family_counts(tmp_path: Path):
    variants = ("full", "no_judge", "no_repair", "extraction_only")
    for variant in variants:
        report_dir = tmp_path / "audit" / "reports" / variant
        result_dir = tmp_path / "variants" / variant / "results"
        paper_dir = tmp_path / "variants" / variant / "papers" / "P1"
        report_dir.mkdir(parents=True)
        result_dir.mkdir(parents=True)
        paper_dir.mkdir(parents=True)
        issues = [] if variant == "full" else [
            {"type": "scope_violation"},
            {"type": "missing_reaction"},
        ]
        (report_dir / "P1.json").write_text(
            json.dumps({"status": "pass" if not issues else "fail", "issues": issues}),
            encoding="utf-8",
        )
        (result_dir / "P1.json").write_text(
            json.dumps({"status": "usable"}), encoding="utf-8"
        )
        (paper_dir / "07_extraction.json").write_text(
            json.dumps({"reactions": [{}, {}]}), encoding="utf-8"
        )

    paths = build_analysis_tables(tmp_path, tmp_path / "tables")

    with paths["paper_level"].open("r", encoding="utf-8-sig", newline="") as handle:
        paper_rows = list(csv.DictReader(handle))
    assert len(paper_rows) == 4
    no_judge = next(row for row in paper_rows if row["variant"] == "no_judge")
    assert no_judge["has_error"] == "1"
    assert no_judge["total_error_count"] == "2"
    assert no_judge["scope_product_count"] == "1"
    assert no_judge["missing_records_count"] == "1"

    with paths["family_summary"].open("r", encoding="utf-8-sig", newline="") as handle:
        family_rows = list(csv.DictReader(handle))
    assert any(
        row["variant"] == "no_judge"
        and row["error_family"] == "scope_product"
        and row["issue_count"] == "1"
        for row in family_rows
    )

    with paths["paired_tests"].open("r", encoding="utf-8-sig", newline="") as handle:
        paired_rows = list(csv.DictReader(handle))
    assert len(paired_rows) == 3
