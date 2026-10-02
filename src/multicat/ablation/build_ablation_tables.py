from __future__ import annotations

import csv
import json
from pathlib import Path


def build_quality_summary(output_root: Path, destination: Path) -> list[dict]:
    rows: list[dict] = []
    variants_root = output_root / "variants"
    if not variants_root.exists():
        return rows

    for variant_dir in sorted(path for path in variants_root.iterdir() if path.is_dir()):
        variant = variant_dir.name
        paper_dirs = sorted((variant_dir / "papers").glob("P*"))
        usable_ids: set[str] = set()
        for result_path in (variant_dir / "results").glob("*.json"):
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if result.get("status") == "usable":
                usable_ids.add(result_path.stem)
        usable_reactions = 0
        for paper_dir in paper_dirs:
            if paper_dir.name not in usable_ids:
                continue
            extraction_path = paper_dir / "07_extraction.json"
            if extraction_path.exists():
                payload = json.loads(extraction_path.read_text(encoding="utf-8"))
                usable_reactions += len(payload.get("reactions") or [])

        reports = sorted((output_root / "audit" / "reports" / variant).glob("*.json"))
        issue_counts: dict[str, int] = {}
        papers_with_error = 0
        for report_path in reports:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            issues = report.get("issues") or []
            if issues:
                papers_with_error += 1
            for issue in issues:
                issue_type = issue.get("issue_type") or issue.get("type") or "other"
                issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1

        row = {
            "variant": variant,
            "usable_papers": len(usable_ids),
            "usable_reactions": usable_reactions,
            "audited_papers": len(reports),
            "audited_papers_with_error_rate": (
                round(100 * papers_with_error / len(reports), 3) if reports else 0.0
            ),
            **issue_counts,
        }
        rows.append(row)

    destination.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "variant",
        "usable_papers",
        "usable_reactions",
        "audited_papers",
        "audited_papers_with_error_rate",
    ]
    for key in sorted({key for row in rows for key in row} - set(fieldnames)):
        fieldnames.append(key)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return rows
