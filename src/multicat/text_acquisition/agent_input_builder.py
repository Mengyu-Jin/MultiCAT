from __future__ import annotations

import re

HIGH_VALUE_KEYWORDS = (
    "experimental",
    "method",
    "material",
    "catalytic",
    "activity",
    "result",
    "discussion",
    "performance",
    "conversion",
)

REACTION_TABLE_KEYWORDS = (
    "reaction",
    "catalytic",
    "conversion",
    "yield",
    "selectivity",
    "performance",
    "substrate",
    "solvent",
    "temperature",
    "time",
)

# In ml_core mode only recycling/reuse/stability tables are excluded. Reaction
# tables AND characterization tables (BET, acidity, pore) are kept, because the
# catalyst schema fields (bet_area, acidity, pore volume) are sourced from them.
EXCLUDED_TABLE_KEYWORDS = (
    "recycling",
    "recycle",
    "successive use",
    "reuse",
    "stability",
)

LOW_VALUE_TITLES = (
    "introduction",
    "conclusion",
    "conclusions",
    "references",
    "acknowledgements",
    "acknowledgments",
    "author contributions",
    "competing interests",
    "additional information",
    "data availability",
)

ML_CORE_SECTION_CHAR_LIMIT = 1200


def build_agent_input_markdown(package: dict, mode: str = "full") -> str:
    title = package.get("title", "")
    metadata = package.get("metadata", {})
    sections = _select_sections(package.get("sections", []), mode=mode)
    tables = _select_tables(package.get("tables", []), mode=mode)

    lines = [
        f"# Agent Input: {title}",
        "",
        "## Paper Metadata",
        "",
        f"- paper_id: {package.get('paper_id', '')}",
        f"- DOI: {metadata.get('doi', '')}",
        "",
        "## Abstract",
        "",
        package.get("abstract", ""),
        "",
        "## High-Value Sections",
        "",
    ]

    for section in sections:
        section_title = section.get("title") or "Untitled section"
        section_text = _section_text(section.get("text", ""), mode=mode)
        lines.extend([f"## {section_title}", "", section_text, ""])

    if tables:
        lines.extend(["## Textual Tables", ""])
        for index, table in enumerate(tables, start=1):
            lines.extend([f"### Table {index}", ""])
            if table.get("caption"):
                lines.extend([table["caption"], ""])
            lines.extend(_table_to_markdown(table.get("rows", [])))
            lines.append("")

    if package.get("figure_captions"):
        lines.extend(["## Figure Captions", ""])
        for figure in package["figure_captions"]:
            fid = figure.get("id", "")
            caption = figure.get("caption", "")
            if caption and fid:
                lines.append(f"- {fid}: {caption}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _select_sections(sections: list[dict], mode: str = "full") -> list[dict]:
    high_value = [
        section
        for section in sections
        if _is_high_value_section(section.get("title", ""), mode=mode)
    ]
    if high_value:
        return high_value
    return [section for section in sections if not _is_low_value_section(section.get("title", ""))]


def _is_high_value_section(title: str, mode: str = "full") -> bool:
    lowered = title.lower()
    if _is_low_value_section(title):
        return False
    if mode == "ml_core" and any(keyword in lowered for keyword in ("recycling", "reuse", "kinetic", "mechanism")):
        return False
    return any(keyword in lowered for keyword in HIGH_VALUE_KEYWORDS)


def _is_low_value_section(title: str) -> bool:
    lowered = title.strip().lower()
    return any(lowered == low_value or lowered.startswith(low_value) for low_value in LOW_VALUE_TITLES)


def _section_text(text: str, mode: str = "full") -> str:
    if mode != "ml_core" or len(text) <= ML_CORE_SECTION_CHAR_LIMIT:
        return text
    return text[:ML_CORE_SECTION_CHAR_LIMIT].rstrip() + "\n\n[truncated for ml_core]"


def _select_tables(tables: list[dict], mode: str = "full") -> list[dict]:
    if mode != "ml_core":
        return tables
    return [table for table in tables if not _is_excluded_table(table)]


def _is_excluded_table(table: dict) -> bool:
    text = " ".join(
        [
            str(table.get("caption", "")),
            " ".join(str(cell) for row in table.get("rows", [])[:2] for cell in row),
        ]
    ).lower()
    return any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in EXCLUDED_TABLE_KEYWORDS)


FOOTNOTE_MARKER_PATTERN = re.compile(r"(?<=\S)\s+[a-z]$")


def _strip_footnote_marker(cell: str) -> str:
    """Strip a trailing single-letter footnote marker from a table cell.

    Papers commonly mark table entries with superscript footnote letters such
    as "HCl b" or "ICC d", where the letter refers to a footnote, not part of
    the catalyst name. Left in place, isolated single-letter suffixes like
    this have caused the extraction LLM to produce malformed/runaway JSON
    output (observed on P000003, table cell "ICC d").
    """
    return FOOTNOTE_MARKER_PATTERN.sub("", cell)


def _table_to_markdown(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    rows = [[_strip_footnote_marker(str(cell)) for cell in row] for row in rows]
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(normalized[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * width) + " |")
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return lines
