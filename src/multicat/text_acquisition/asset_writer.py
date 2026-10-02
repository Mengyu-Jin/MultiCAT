from __future__ import annotations

import csv
import json
from pathlib import Path

from multicat.text_acquisition.agent_input_builder import build_agent_input_markdown


def write_text_package_assets(package: dict, paper_dir: Path) -> dict:
    paper_dir.mkdir(parents=True, exist_ok=True)

    markdown_path = paper_dir / "02_paper.md"
    json_path = paper_dir / "03_text_package.json"
    agent_input_path = paper_dir / "05_agent_input.md"
    tables_dir = paper_dir / "04_tables"
    tables_dir.mkdir(exist_ok=True)

    markdown_path.write_text(_package_to_markdown(package), encoding="utf-8")
    json_path.write_text(
        json.dumps(package, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    agent_input_path.write_text(build_agent_input_markdown(package), encoding="utf-8")
    table_paths = _write_tables(package.get("tables", []), tables_dir)

    return {
        "markdown_path": markdown_path,
        "json_path": json_path,
        "agent_input_path": agent_input_path,
        "table_paths": table_paths,
    }


def _package_to_markdown(package: dict) -> str:
    lines = [
        f"# {package.get('title', '')}",
        "",
        "## Metadata",
        "",
        f"- paper_id: {package.get('paper_id', '')}",
        f"- doi: {package.get('metadata', {}).get('doi', '')}",
        f"- xml_type: {package.get('xml_type', '')}",
        "",
        "## Abstract",
        "",
        package.get("abstract", ""),
        "",
    ]

    for section in package.get("sections", []):
        title = section.get("title") or "Untitled section"
        lines.extend([f"## {title}", "", section.get("text", ""), ""])

    if package.get("tables"):
        lines.extend(["## Appendix: Tables", ""])
        for index, table in enumerate(package["tables"], start=1):
            lines.extend([f"### Table {index}", ""])
            if table.get("caption"):
                lines.extend([table["caption"], ""])
            lines.extend(_table_to_markdown(table.get("rows", [])))
            lines.append("")

    if package.get("figure_captions"):
        lines.extend(["## Figure Captions", ""])
        for figure in package["figure_captions"]:
            lines.append(figure.get("caption", ""))
        lines.append("")

    return "\n".join(lines)


def _table_to_markdown(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(normalized[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * width) + " |")
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _write_tables(tables: list[dict], tables_dir: Path) -> list[Path]:
    paths = []
    for index, table in enumerate(tables, start=1):
        rows = table.get("rows", [])
        if not rows:
            continue
        table_path = tables_dir / f"Table{index}.csv"
        with table_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)
        paths.append(table_path)
    return paths
