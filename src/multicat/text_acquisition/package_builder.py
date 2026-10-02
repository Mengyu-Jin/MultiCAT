from __future__ import annotations

import re
import xml.etree.ElementTree as ET


def build_text_package_from_xml(paper_id: str, metadata: dict, xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    xml_type = _detect_xml_type(root)
    title = _extract_title(root, xml_type)
    abstract = _extract_abstract(root, xml_type)

    return {
        "paper_id": paper_id,
        "metadata": metadata,
        "title": title,
        "abstract": abstract,
        "sections": _extract_sections(root, xml_type),
        "tables": _extract_tables(root, xml_type),
        "table_captions": _extract_table_captions(root, xml_type),
        "figure_captions": _extract_figure_captions(root),
        "source_format": "xml",
        "xml_type": xml_type,
    }


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _findall(root: ET.Element, tag: str) -> list[ET.Element]:
    return [element for element in root.iter() if _strip_namespace(element.tag) == tag]


def _first(root: ET.Element, tag: str) -> ET.Element | None:
    matches = _findall(root, tag)
    return matches[0] if matches else None


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return _clean_text(" ".join(text for text in element.itertext() if text))


def _first_text(root: ET.Element, tag: str) -> str:
    return _element_text(_first(root, tag))


def _joined_texts(root: ET.Element, tag: str) -> str:
    return _clean_text(" ".join(_element_text(element) for element in _findall(root, tag)))


def _detect_xml_type(root: ET.Element) -> str:
    if _strip_namespace(root.tag) == "full-text-retrieval-response" or _first(root, "sections") is not None:
        return "elsevier"
    return "jats"


def _extract_title(root: ET.Element, xml_type: str) -> str:
    if xml_type == "elsevier":
        return _first_text(root, "title")
    return _first_text(root, "article-title")


def _extract_abstract(root: ET.Element, xml_type: str) -> str:
    if xml_type == "elsevier":
        return _first_text(root, "description")
    return _joined_texts(root, "abstract")


def _extract_sections(root: ET.Element, xml_type: str) -> list[dict]:
    sections = []
    section_tag = "section" if xml_type == "elsevier" else "sec"
    title_tag = "section-title" if xml_type == "elsevier" else "title"
    paragraph_tag = "para" if xml_type == "elsevier" else "p"
    for sec in _findall(root, section_tag):
        title = _first_text(sec, title_tag)
        paragraphs = [_element_text(p) for p in _findall(sec, paragraph_tag)]
        sections.append(
            {
                "title": title,
                "text": _clean_text(" ".join(paragraphs)),
            }
        )
    return sections


def _caption_text(element: ET.Element) -> str:
    label = _first(element, "label")
    caption = _first(element, "caption")
    return _clean_text(" ".join(part for part in [_element_text(label), _element_text(caption)] if part))


def _extract_table_captions(root: ET.Element, xml_type: str) -> list[str]:
    table_tag = "table" if xml_type == "elsevier" else "table-wrap"
    return [_caption_text(table) for table in _findall(root, table_tag)]


def _extract_tables(root: ET.Element, xml_type: str) -> list[dict]:
    tables = []
    table_tag = "table" if xml_type == "elsevier" else "table-wrap"
    row_tag = "row" if xml_type == "elsevier" else "tr"
    cell_tags = {"entry"} if xml_type == "elsevier" else {"th", "td"}
    for table_wrap in _findall(root, table_tag):
        rows = []
        for tr in _findall(table_wrap, row_tag):
            cells = []
            for cell in tr:
                if _strip_namespace(cell.tag) in cell_tags:
                    cells.append(_element_text(cell))
            if cells:
                rows.append(cells)
        tables.append(
            {
                "id": table_wrap.attrib.get("id"),
                "caption": _caption_text(table_wrap),
                "rows": rows,
            }
        )
    return tables


def _extract_figure_captions(root: ET.Element) -> list[dict]:
    captions = []
    # JATS: <fig id="f1">
    for figure in _findall(root, "fig"):
        captions.append(
            {
                "id": figure.attrib.get("id"),
                "caption": _caption_text(figure),
                "locator": None,
            }
        )
    # Elsevier: <figure> with <link locator="gr1"/>
    for figure in _findall(root, "figure"):
        locator = None
        link = _first(figure, "link")
        if link is not None:
            locator = link.attrib.get("locator")
        fig_id = figure.attrib.get("id") or locator
        captions.append(
            {
                "id": fig_id,
                "caption": _caption_text(figure),
                "locator": locator,
            }
        )
    return captions
