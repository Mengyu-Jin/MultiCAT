from __future__ import annotations

import json
from pathlib import Path

MOJIBAKE_PATTERNS = ("¦", "Ã", "Â", "�")


def qa_paper_assets(paper_dir: Path) -> dict:
    issues = []
    xml_path = paper_dir / "01_paper.xml"
    markdown_path = paper_dir / "02_paper.md"
    package_path = paper_dir / "03_text_package.json"
    tables_dir = paper_dir / "04_tables"

    if not xml_path.exists():
        issues.append(_issue("missing_xml", "01_paper.xml is missing."))
    if not markdown_path.exists():
        issues.append(_issue("missing_markdown", "02_paper.md is missing."))
    if not package_path.exists():
        issues.append(_issue("missing_text_package", "03_text_package.json is missing."))
        return _report(issues, {})

    package = json.loads(package_path.read_text(encoding="utf-8"))
    title = package.get("title", "")
    abstract = package.get("abstract", "")
    sections = package.get("sections", [])
    tables = package.get("tables", [])

    if not title.strip():
        issues.append(_issue("empty_title", "Parsed title is empty."))
    if not abstract.strip():
        issues.append(_issue("empty_abstract", "Parsed abstract is empty."))
    if not sections:
        issues.append(_issue("empty_sections", "No sections were parsed."))

    table_csv_count = len(list(tables_dir.glob("Table*.csv"))) if tables_dir.exists() else 0
    nonempty_json_tables = sum(1 for table in tables if table.get("rows"))
    if table_csv_count != nonempty_json_tables:
        issues.append(
            _issue(
                "table_count_mismatch",
                f"CSV table count {table_csv_count} does not match JSON table count {nonempty_json_tables}.",
            )
        )

    searchable_text = " ".join(
        [
            title,
            abstract,
            " ".join(section.get("title", "") + " " + section.get("text", "") for section in sections),
        ]
    )
    if any(pattern in searchable_text for pattern in MOJIBAKE_PATTERNS):
        issues.append(_issue("mojibake_pattern", "Common mojibake pattern detected."))

    metrics = {
        "title_chars": len(title),
        "abstract_chars": len(abstract),
        "section_count": len(sections),
        "json_table_count": nonempty_json_tables,
        "csv_table_count": table_csv_count,
    }
    return _report(issues, metrics)


def _issue(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _report(issues: list[dict], metrics: dict) -> dict:
    return {
        "status": "fail" if issues else "pass",
        "issues": issues,
        "metrics": metrics,
    }
