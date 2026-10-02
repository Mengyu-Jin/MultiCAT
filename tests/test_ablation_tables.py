from __future__ import annotations

import csv
import json
from pathlib import Path

from multicat.ablation.build_ablation_tables import build_quality_summary


def test_build_quality_summary_reports_paper_reaction_and_error_rates(tmp_path: Path):
    for variant, reactions in {"full": 3, "no_judge": 5}.items():
        paper_dir = tmp_path / "variants" / variant / "papers" / "P1"
        paper_dir.mkdir(parents=True)
        (paper_dir / "07_extraction.json").write_text(
            json.dumps({"reactions": [{}] * reactions}), encoding="utf-8"
        )
        result_dir = tmp_path / "variants" / variant / "results"
        result_dir.mkdir(parents=True)
        (result_dir / "P1.json").write_text(
            json.dumps({"status": "usable" if variant == "full" else "rejected"}),
            encoding="utf-8",
        )
        report_dir = tmp_path / "audit" / "reports" / variant
        report_dir.mkdir(parents=True)
        issues = [] if variant == "full" else [
            {"type": "scope_violation"},
            {"type": "merged_rows"},
        ]
        (report_dir / "P1.json").write_text(
            json.dumps({"status": "pass" if not issues else "fail", "issues": issues}),
            encoding="utf-8",
        )

    output = tmp_path / "tables" / "quality_summary.csv"
    rows = build_quality_summary(tmp_path, output)

    assert [row["variant"] for row in rows] == ["full", "no_judge"]
    assert rows[0]["usable_papers"] == 1
    assert rows[0]["usable_reactions"] == 3
    assert rows[0]["audited_papers_with_error_rate"] == 0.0
    assert rows[1]["usable_papers"] == 0
    assert rows[1]["usable_reactions"] == 0
    assert rows[1]["scope_violation"] == 1
    assert rows[1]["merged_rows"] == 1
    assert rows[1]["audited_papers_with_error_rate"] == 100.0
    with output.open("r", encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 2
