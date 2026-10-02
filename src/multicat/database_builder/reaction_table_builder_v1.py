from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

from multicat.validator.extraction_validator import normalize_extraction_payload


# Performance unit filter: only percentage-type units enter the numeric columns
_PCT_UNITS: frozenset[str] = frozenset({
    "%", "mol%", "wt%", "molar%", "weight%", "area%", "c-mol%",
    "% w w-1", "%w/w", "% (w/w)", "wt. %", "wt.%", "mass%",
    "", "unknown",
})

def _is_percent_unit(unit: Any) -> bool:
    u = (unit or "").strip().lower()
    if u in _PCT_UNITS:
        return True
    if u.endswith("%"):
        return True
    if "%" in u and any(k in u for k in ("w", "v", "mol")):
        return True
    return False


PRODUCTS = [
    "lactic_acid",
    "hmf",
    "furfural",
    "levulinic_acid",
    "formic_acid",
    "acetic_acid",
    "glycolic_acid",
    "others",
]

AUDIT_COLUMNS = [
    "record_id",
    "paper_id",
    "reaction_id",
    "catalyst_id",
    "doi",
    "title",
    "journal",
    "year",
    "publisher",
    "xml_source",
    "catalyst_name",
    "support_status",
    "support_class",
    "unsupported_class",
    "composition_raw",
    "num_metals",
    "metal_1",
    "metal_1_content_value",
    "metal_1_content_unit",
    "metal_2",
    "metal_2_content_value",
    "metal_2_content_unit",
    "metal_3",
    "metal_3_content_value",
    "metal_3_content_unit",
    "has_more_than_3_metals",
    "metals_all",
    "synthesis_method",
    "calcination_temp",
    "calcination_temp_unit",
    "calcination_time",
    "calcination_time_unit",
    "hydrothermal_temp",
    "hydrothermal_temp_unit",
    "hydrothermal_time",
    "hydrothermal_time_unit",
    "drying_temp",
    "drying_temp_unit",
    "drying_time",
    "drying_time_unit",
    "synthesis_text",
    "bet_area",
    "bet_area_unit",
    "total_pore_volume",
    "total_pore_volume_unit",
    "micropore_volume",
    "micropore_volume_unit",
    "bronsted_acidity",
    "bronsted_acidity_unit",
    "lewis_acidity",
    "lewis_acidity_unit",
    "strong_acidity",
    "strong_acidity_unit",
    "weak_acidity",
    "weak_acidity_unit",
    "total_acidity",
    "total_acidity_unit",
    "characterization_text",
    "substrate_name",
    "substrate_class",
    "substrate_origin",
    "is_polymeric",
    "reaction_method",
    "reaction_temperature",
    "reaction_temperature_unit",
    "reaction_time",
    "reaction_time_unit",
    "reaction_pressure",
    "reaction_pressure_unit",
    "reaction_atmosphere",
    "substrate_mass",
    "substrate_mass_unit",
    "substrate_concentration",
    "substrate_concentration_unit",
    "catalyst_amount",
    "catalyst_amount_unit",
    "catalyst_loading",
    "catalyst_loading_unit",
    "catalyst_substrate_ratio",
    "catalyst_substrate_ratio_source",
    "solvent_name",
    "solvent_volume",
    "solvent_volume_unit",
    "reactor_type",
    "condition_text",
    "substrate_conversion",
    "source_type",
    "evidence",
]

for product in PRODUCTS:
    AUDIT_COLUMNS.append(f"{product}_yield")
for product in PRODUCTS:
    AUDIT_COLUMNS.append(f"{product}_selectivity")

ML_EXCLUDED_COLUMNS = {
    "paper_id",
    "reaction_id",
    "catalyst_id",
    "title",
    "journal",
    "publisher",
    "xml_source",
    "source_type",
    "evidence",
    "condition_text",
    "synthesis_text",
    "characterization_text",
    "composition_raw",
}

ML_EXCLUDED_SUFFIXES = ("_unit", "_label", "_source")


def _load_payload(paper_dir: Path) -> dict | None:
    """Read 07_extraction.json and make sure the fields are normalized (fallback)."""
    payload = json.loads((paper_dir / "07_extraction.json").read_text(encoding="utf-8"))
    if payload.get("extraction_meta", {}).get("schema_version") != "v1":
        return None
    return normalize_extraction_payload(payload)


def build_audit_table_v1(papers_root: Path, registry_year: dict | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for paper_dir in sorted(path for path in papers_root.iterdir() if path.is_dir()):
        if not _paper_passed(paper_dir):
            continue
        payload = _load_payload(paper_dir)
        if payload is None:
            continue
        rows.extend(build_audit_rows_v1(payload, registry_year=registry_year))
    return rows


def build_ml_table_v1(papers_root: Path, registry_year: dict | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for paper_dir in sorted(path for path in papers_root.iterdir() if path.is_dir()):
        if not _paper_passed(paper_dir):
            continue
        payload = _load_payload(paper_dir)
        if payload is None:
            continue
        rows.extend(build_ml_rows_v1(payload, registry_year=registry_year))
    return rows


def build_audit_rows_v1(payload: dict, registry_year: dict | None = None) -> list[dict[str, Any]]:
    paper = payload.get("paper", {})
    # Year backfill: year in extraction.json is usually None, so it is filled from the registry
    if paper.get("year") is None and registry_year:
        pid = paper.get("paper_id") or ""
        if pid in registry_year:
            paper = dict(paper)
            paper["year"] = registry_year[pid]
    catalysts = _catalysts_by_id(payload.get("catalysts", []))
    rows: list[dict[str, Any]] = []
    for reaction in payload.get("reactions", []):
        catalyst = catalysts.get(reaction.get("catalyst_id"), {})
        rows.append(_build_audit_row(paper, catalyst, reaction))
    return rows


def build_ml_rows_v1(payload: dict, registry_year: dict | None = None) -> list[dict[str, Any]]:
    return [_to_ml_row(row) for row in build_audit_rows_v1(payload, registry_year=registry_year)]


def _load_registry_year(papers_root: Path) -> dict[str, Any]:
    """Build a paper_id -> year map from paper_registry.csv to backfill missing years in extraction.json."""
    registry_path = papers_root.parent / "registry" / "paper_registry.csv"
    if not registry_path.exists():
        return {}
    year_map: dict[str, Any] = {}
    with open(registry_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get("paper_id", "").strip()
            yr = row.get("year", "").strip()
            if pid and yr:
                try:
                    year_map[pid] = int(yr)
                except ValueError:
                    year_map[pid] = yr
    return year_map


def write_v1_tables(papers_root: Path, output_root: Path) -> tuple[Path, Path]:
    registry_year = _load_registry_year(papers_root)
    audit_rows = build_audit_table_v1(papers_root, registry_year=registry_year)
    ml_rows = build_ml_table_v1(papers_root, registry_year=registry_year)
    audit_path = output_root / "reaction_audit_table_v1.csv"
    ml_path = output_root / "ml_ready_table_v1.csv"
    _write_csv(audit_rows, audit_path, AUDIT_COLUMNS)
    _write_csv(ml_rows, ml_path, _ml_columns())
    return audit_path, ml_path


def _build_audit_row(paper: dict, catalyst: dict, reaction: dict) -> dict[str, Any]:
    reaction_id = reaction.get("reaction_id")
    paper_id = reaction.get("paper_id") or paper.get("paper_id")
    row: dict[str, Any] = {
        "record_id": _record_id(paper_id, reaction_id),
        "paper_id": paper_id,
        "reaction_id": reaction_id,
        "catalyst_id": reaction.get("catalyst_id"),
        "doi": paper.get("doi"),
        "title": paper.get("title"),
        "journal": paper.get("journal"),
        "year": paper.get("year"),
        "publisher": paper.get("publisher"),
        "xml_source": paper.get("xml_source"),
        "catalyst_name": catalyst.get("catalyst_name"),
        "support_status": catalyst.get("support_status"),
        "support_class": catalyst.get("support_class"),
        "unsupported_class": catalyst.get("unsupported_class"),
        "composition_raw": catalyst.get("composition_raw"),
        "source_type": reaction.get("source_type"),
        "evidence": reaction.get("evidence"),
    }
    row.update(_metal_columns(catalyst.get("metals", [])))
    row.update(_prefixless(catalyst.get("synthesis", {})))
    row.update(_prefixless(catalyst.get("characterization", {})))
    row.update(_prefixless(reaction.get("substrate", {})))
    row.update(_sanitize_conditions(reaction.get("conditions", {})))
    row.update(_performance_columns(reaction.get("performance_metrics", [])))
    return {column: row.get(column) for column in AUDIT_COLUMNS}


# Elements that are genuinely metallic (including metalloids used as active
# metal centres in heterogeneous catalysis: Al, Si excluded as they are
# framework atoms, not active metals; B/P/S are non-metal modifiers).
_METAL_ELEMENTS: frozenset[str] = frozenset({
    "Li", "Be",
    "Na", "Mg", "Al",
    "K",  "Ca", "Sc", "Ti", "V",  "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
    "Rb", "Sr", "Y",  "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Cs", "Ba",
    "La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
    "Hf", "Ta", "W",  "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi",
    # common metalloids treated as active centres in this project
    "Sb", "Te",
})


def _metal_columns(metals: Any) -> dict[str, Any]:
    if not isinstance(metals, list):
        metals = []

    metal_entries = []
    for m in metals:
        if not isinstance(m, dict):
            continue
        el = m.get("element", "")
        if not el:
            continue
        if el in _METAL_ELEMENTS:
            metal_entries.append(m)

    elements = [m.get("element") for m in metal_entries]
    row: dict[str, Any] = {
        "num_metals": len(elements),
        "has_more_than_3_metals": len(elements) > 3,
        "metals_all": ";".join(elements) if elements else "none",
    }
    for index in range(3):
        m = metal_entries[index] if index < len(metal_entries) else {}
        number = index + 1
        row[f"metal_{number}"] = m.get("element") or "none"
        row[f"metal_{number}_content_value"] = m.get("content_value")
        row[f"metal_{number}_content_unit"] = m.get("content_unit")
    return row


def _performance_columns(metrics: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"substrate_conversion": None}
    for product in PRODUCTS:
        row[f"{product}_yield"] = None
        row[f"{product}_selectivity"] = None
    if not isinstance(metrics, list):
        return row
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        name = metric.get("metric_name")
        product = metric.get("product_name")
        value = metric.get("value")
        unit = metric.get("unit")
        # Drop non-percentage units (absolute amounts such as g/kg, mg, mmol do not enter the numeric columns)
        if not _is_percent_unit(unit):
            continue
        if name == "conversion":
            row["substrate_conversion"] = value
        elif name == "yield" and product in PRODUCTS:
            row[f"{product}_yield"] = value
        elif name == "selectivity" and product in PRODUCTS:
            row[f"{product}_selectivity"] = value
    return row


def _to_ml_row(audit_row: dict[str, Any]) -> dict[str, Any]:
    ml_row: dict[str, Any] = {}
    for column in _ml_columns():
        ml_row[column] = audit_row.get(column)
    return ml_row


def _ml_columns() -> list[str]:
    return [
        column
        for column in AUDIT_COLUMNS
        if column not in ML_EXCLUDED_COLUMNS
        and not any(column.endswith(suffix) for suffix in ML_EXCLUDED_SUFFIXES)
    ]


def _paper_passed(paper_dir: Path) -> bool:
    # Judge is the final authority; validation may remain "fail" if repair loop
    # improved quality enough for judge to pass without re-running validator.
    required = ["07_extraction.json", "09_judge.json"]
    if not all((paper_dir / name).exists() for name in required):
        return False
    judge = json.loads((paper_dir / "09_judge.json").read_text(encoding="utf-8"))
    return judge.get("status") == "pass"


def _catalysts_by_id(catalysts: list[Any]) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for catalyst in catalysts:
        if isinstance(catalyst, dict) and catalyst.get("catalyst_id"):
            by_id[catalyst["catalyst_id"]] = catalyst
    return by_id


def _record_id(paper_id: Any, reaction_id: Any) -> str | None:
    if paper_id is None or reaction_id is None:
        return None
    return f"{paper_id}_{reaction_id}"


def _sanitize_conditions(conditions: Any) -> dict[str, Any]:
    if not isinstance(conditions, dict):
        return {}
    result = dict(conditions)
    pressure = result.get("reaction_pressure")
    if isinstance(pressure, str):
        result["reaction_pressure"] = None
    return result


def _prefixless(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _write_csv(
    rows: list[dict[str, Any]], output_path: Path, columns: list[str], retries: int = 3
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    last_error: PermissionError | None = None
    for attempt in range(retries + 1):
        try:
            with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                for row in rows:
                    writer.writerow({column: row.get(column) for column in columns})
            return output_path
        except PermissionError as exc:
            # On Windows, the report CSV is frequently still open in Excel
            # or another viewer from a previous run. A brief retry usually
            # succeeds once the file is released; this must not throw away
            # an entire overnight batch's worth of completed paper results
            # just because the final summary write hit a transient lock.
            last_error = exc
            if attempt < retries:
                time.sleep(1.0)
    assert last_error is not None
    raise last_error
    return output_path
