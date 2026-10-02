from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import jsonschema


# ── Normalization constants and helper functions ─────────────────────────────

_TEMP_UNIT_MAP: dict[str, str] = {
    "°c": "°C", "℃": "°C", "c": "°C", "ºc": "°C",
    "\x02c": "°C", "\x02\x0bc": "°C",
}

_TIME_UNIT_MAP: dict[str, str] = {
    "minutes": "min", "minute": "min",
    "hours": "h", "hour": "h", "h": "h", "H": "h",
    "seconds": "s", "second": "s",
    "days": "day", "Days": "day",
}

# Pore volume units: normalized to cm3/g
_PORE_VOL_UNIT_RE = re.compile(
    r"(cm\s*[³3]|cc|ml|mL)\s*[·./\s_-]*\s*g\s*[-−]?\s*1?", re.IGNORECASE
)

# Solvent volume unit mapping
_SOLVENT_VOL_UNIT_MAP: dict[str, str] = {
    "ml": "mL", "cm3": "mL", "cm³": "mL",
}

# Mass concentration and loading units: unify spellings (wt% family)
_WT_PCT_MAP: dict[str, str] = {
    "wt %": "wt%", "wt. %": "wt%", "wt.%": "wt%",
    "% w w-1": "wt%", "%w/w": "wt%", "% (w/w)": "wt%",
    "wt. percent": "wt%", "weight%": "wt%", "mass%": "wt%",
}

# Conversion factors for pressure to MPa
_PRESSURE_TO_MPA: dict[str, float] = {
    "bar": 0.1, "kpa": 0.001, "psi": 0.006895, "atm": 0.101325,
    "mpa": 1.0,
}

# Conversion factors for time to h
_TIME_TO_H: dict[str, float] = {
    "min": 1 / 60, "s": 1 / 3600, "h": 1.0, "day": 24.0,
}

# Substrate molecular weights (g/mol) for concentration unit conversion
_SUBSTRATE_MW: dict[str, float] = {
    "glucose": 180.16, "fructose": 180.16, "galactose": 180.16,
    "mannose": 180.16, "xylose": 150.13, "arabinose": 150.13,
    "sucrose": 342.30, "maltose": 342.30, "lactose": 342.30,
    "cellobiose": 342.30, "trehalose": 342.30,
    "dihydroxyacetone": 90.08, "glycolaldehyde": 60.05,
    "hmf": 126.11, "furfural": 96.08, "furfuryl alcohol": 98.10,
    "levulinic acid": 116.12,
}

# Concentration conversion: converting units to wt% assumes a density (dilute aqueous solution ≈ 1 g/mL = 1000 g/L)
# g/L → wt%: wt% = g/L / 10  (assumes a solution density of about 1 g/mL, i.e. 1000 g/L water)
# M → wt%: wt% = M × MW / 10
# mM → wt%: wt% = mM × MW / 10000
# mol/L → wt%: same as M
# mg/mL → wt%: mg/mL = g/L → wt% = value / 10
# % (m/v) → wt%: g/100 mL ≈ g/100 g (dilute solution), equal to wt%
# wt/v% → wt%: g/100 mL ≈ wt% (dilute solution)
# mmol/l → wt%: mM, same as above
# kg m-3 → wt%: = g/L → value / 10
# ppm → wt%: ppm(w/w) / 10000
_CONC_UNIT_NORM: dict[str, str] = {
    "wt %": "wt%", "wt. %": "wt%", "wt.%": "wt%",
    "% w w-1": "wt%", "%w/w": "wt%", "% (w/w)": "wt%",
    "wt. percent": "wt%", "weight%": "wt%", "mass%": "wt%",
    "wt/v%": "wt%", "% (m/v)": "wt%",
}

_BET_UNIT_RE = re.compile(r"m\s*[²2]\s*[·./\s_-]*\s*g\s*[-−]?\s*1?", re.IGNORECASE)
_ACIDITY_UMOL_RE = re.compile(r"[µμu]mol", re.IGNORECASE)
_ACIDITY_MMOL_RE = re.compile(r"mmol", re.IGNORECASE)
_ACIDITY_MEQ_RE  = re.compile(r"meq|eq\.\s*kg", re.IGNORECASE)

_SUBSTRATE_MAP: dict[str, str] = {
    "d-glucose": "glucose", "d glucose": "glucose", "glu": "glucose",
    "glucose monohydrate": "glucose",
    "d-fructose": "fructose", "d fructose": "fructose",
    "d-xylose": "xylose", "d xylose": "xylose",
    "d-mannose": "mannose", "d-galactose": "galactose",
    "microcrystalline cellulose": "cellulose",
    "microcrystalline cel": "cellulose", "avicel": "cellulose",
    "dha": "dihydroxyacetone", "gla": "glycolaldehyde",
    "5-hmf": "hmf",
    "glu/fru/suc": "glucose/fructose/sucrose",
    "glucose and xylose mixtures": "glucose/xylose",
}
_SUBSTRATE_LOWER_CANONICAL: frozenset[str] = frozenset({
    "glucose", "fructose", "xylose", "mannose", "galactose", "arabinose",
    "sucrose", "lactose", "maltose", "cellobiose", "cellulose",
    "hemicellulose", "xylan", "starch", "inulin", "dihydroxyacetone",
    "glycolaldehyde", "levulinic acid", "hmf", "furfuryl alcohol",
    "corn stover", "wheat straw", "rice straw", "rice husk", "bagasse",
    "wood sawdust", "corn stalk",
})

_PRODUCT_MAP: dict[str, str] = {
    "5-hmf": "hmf", "5hmf": "hmf", "hydroxymethylfurfural": "hmf",
    "hydroxymethyl furfural": "hmf", "5-hydroxymethylfurfural": "hmf",
    "ff": "furfural", "fur": "furfural", "furan-2-carbaldehyde": "furfural",
    "la": "lactic_acid", "lactic acid": "lactic_acid",
    "lev": "levulinic_acid", "levulinic acid": "levulinic_acid", "leva": "levulinic_acid",
    "fa": "formic_acid", "formic acid": "formic_acid",
    "acetic acid": "acetic_acid", "aa": "acetic_acid",
    "glycolic acid": "glycolic_acid", "ga": "glycolic_acid",
}
_PRODUCT_CANONICAL: frozenset[str] = frozenset({
    "lactic_acid", "hmf", "furfural", "levulinic_acid",
    "formic_acid", "acetic_acid", "glycolic_acid", "others", "none", "unknown",
})

_SOLVENT_MAP: dict[str, str] = {
    "h2o": "water", "distilled water": "water", "deionized water": "water",
    "dimethyl sulfoxide": "DMSO", "dimethylsulfoxide": "DMSO",
    "thf/water": "THF/H2O", "thf/h2o": "THF/H2O",
    "h2o/thf": "THF/H2O", "water/thf": "THF/H2O",
    "ethanol": "EtOH", "etoh": "EtOH",
    "water-toluene": "water/toluene", "water + toluene": "water/toluene",
    "water–toluene": "water/toluene",
    "water-mibk": "water/MIBK", "water + mibk": "water/MIBK",
    "water–mibk": "water/MIBK",
    "meoh": "methanol", "dimethylformamide": "DMF",
}


def _norm_temp(value: Any, unit: Any) -> tuple[Any, str]:
    u_raw = (unit or "").strip()
    u_low = u_raw.lower()
    if u_low == "k" and value is not None:
        try:
            return round(float(value) - 273.15, 1), "°C"
        except (TypeError, ValueError):
            pass
    clean = _TEMP_UNIT_MAP.get(u_low)
    return value, (clean if clean else u_raw)


def _norm_time_unit(unit: Any) -> str:
    u = (unit or "").strip()
    return _TIME_UNIT_MAP.get(u.lower(), u)


def _norm_bet_unit(unit: Any) -> str:
    u = (unit or "").strip()
    return "m2/g" if _BET_UNIT_RE.search(u) else u


def _norm_acidity(value: Any, unit: Any) -> tuple[Any, str]:
    u = (unit or "").strip()
    if not u:
        return value, u
    if _ACIDITY_UMOL_RE.search(u):
        try:
            return round(float(value) / 1000, 4), "mmol/g"
        except (TypeError, ValueError):
            return value, "mmol/g"
    if _ACIDITY_MMOL_RE.search(u):
        return value, "mmol/g"
    if _ACIDITY_MEQ_RE.search(u):
        return value, "mmol/g"
    return value, u


def _norm_substrate(name: Any) -> Any:
    if not name:
        return name
    n = str(name).strip()
    lo = n.lower()
    if lo in _SUBSTRATE_MAP:
        return _SUBSTRATE_MAP[lo]
    if lo in _SUBSTRATE_LOWER_CANONICAL:
        return lo
    return n


def _norm_product(name: Any) -> Any:
    if not name:
        return name
    n = str(name).strip()
    lo = n.lower()
    if lo in _PRODUCT_CANONICAL:
        return n
    return _PRODUCT_MAP.get(lo, n)


def _norm_solvent(name: Any) -> Any:
    if not name:
        return name
    n = str(name).strip()
    lo = n.lower()
    return _SOLVENT_MAP.get(lo, n)


def _norm_pore_vol_unit(unit: Any) -> str:
    u = (unit or "").strip()
    return "cm3/g" if _PORE_VOL_UNIT_RE.search(u) else u


def _norm_solvent_vol_unit(unit: Any) -> str:
    u = (unit or "").strip()
    return _SOLVENT_VOL_UNIT_MAP.get(u, u)


def _norm_wt_pct_unit(unit: Any) -> str:
    u = (unit or "").strip()
    return _WT_PCT_MAP.get(u, u)


def _norm_pressure(value: Any, unit: Any) -> tuple[Any, str]:
    u = (unit or "").strip()
    factor = _PRESSURE_TO_MPA.get(u.lower())
    if factor is None or factor == 1.0:
        return value, u
    try:
        return round(float(value) * factor, 4), "MPa"
    except (TypeError, ValueError):
        return value, u


def _norm_time_value(value: Any, unit: Any) -> tuple[Any, str]:
    """Convert time values to h (only for min, s, and day)."""
    u_raw = (unit or "").strip()
    u_norm = _TIME_UNIT_MAP.get(u_raw, u_raw)  # unify the spelling first
    factor = _TIME_TO_H.get(u_norm)
    if factor is None or factor == 1.0:
        return value, u_norm
    try:
        return round(float(value) * factor, 4), "h"
    except (TypeError, ValueError):
        return value, u_norm


def _norm_mass(value: Any, unit: Any) -> tuple[Any, str]:
    """Convert mass to g (mg → g)."""
    u = (unit or "").strip()
    if u == "mg":
        try:
            return round(float(value) / 1000, 6), "g"
        except (TypeError, ValueError):
            pass
    return value, u


def _norm_concentration(value: Any, unit: Any, substrate_name: Any) -> tuple[Any, str]:
    """Convert substrate concentration to wt% (assuming a dilute aqueous solution of about 1 g/mL).

    Convertible units: g/L, mg/mL, kg m-3, M, mol/L, mM, mmol/l, % (m/v), wt/v%, ppm
    Not convertible (original value kept): molar concentrations (M, mM) for substrates without a molecular weight
    """
    u = (unit or "").strip()
    # Unify the spelling
    u_norm = _CONC_UNIT_NORM.get(u, u)
    if u_norm == "wt%":
        return value, "wt%"

    try:
        v = float(value)
    except (TypeError, ValueError):
        return value, u

    u_low = u.lower().strip()

    # Mass per volume concentration → wt% (density about 1 g/mL)
    if u_low in ("g/l", "g l-1", "g/ml", "mg ml-1", "mg ml −1", "kg m-3"):
        factor = {"g/l": 0.1, "g l-1": 0.1, "g/ml": 100.0,
                  "mg ml-1": 0.1, "mg ml −1": 0.1, "kg m-3": 0.1}.get(u_low, None)
        if factor:
            return round(v * factor, 4), "wt%"

    # ppm(w/w) → wt%
    if u_low == "ppm":
        return round(v / 10000, 6), "wt%"

    # Molar concentration → wt% (requires the molecular weight)
    sub = (substrate_name or "").strip().lower()
    mw = _SUBSTRATE_MW.get(sub)
    if mw is None:
        return value, u  # no molecular weight, cannot convert

    if u_low in ("m", "mol/l"):
        return round(v * mw / 10, 4), "wt%"
    if u_low in ("mm", "mmol/l"):
        return round(v * mw / 10000, 4), "wt%"

    return value, u


def _norm_partial_acidity(value: Any, unit: Any, total_acidity: Any) -> tuple[Any, str]:
    """When strong/weak_acidity is given in %, back-calculate mmol/g as total_acidity × % / 100."""
    u = (unit or "").strip()
    if u != "%":
        return value, u
    try:
        ta = float(total_acidity)
        return round(float(value) / 100 * ta, 4), "mmol/g"
    except (TypeError, ValueError):
        return value, u


def normalize_extraction_payload(payload: dict) -> dict:
    """Normalize field values of the extraction JSON in place and return the modified payload."""
    for catalyst in payload.get("catalysts") or []:
        if not isinstance(catalyst, dict):
            continue

        # synthesis fields
        syn = catalyst.get("synthesis")
        if isinstance(syn, dict):
            syn["calcination_temp"], syn["calcination_temp_unit"] = _norm_temp(
                syn.get("calcination_temp"), syn.get("calcination_temp_unit")
            )
            syn["calcination_time"], syn["calcination_time_unit"] = _norm_time_value(
                syn.get("calcination_time"), syn.get("calcination_time_unit")
            )
            syn["hydrothermal_temp"], syn["hydrothermal_temp_unit"] = _norm_temp(
                syn.get("hydrothermal_temp"), syn.get("hydrothermal_temp_unit")
            )
            syn["hydrothermal_time"], syn["hydrothermal_time_unit"] = _norm_time_value(
                syn.get("hydrothermal_time"), syn.get("hydrothermal_time_unit")
            )
            syn["drying_temp"], syn["drying_temp_unit"] = _norm_temp(
                syn.get("drying_temp"), syn.get("drying_temp_unit")
            )
            syn["drying_time"], syn["drying_time_unit"] = _norm_time_value(
                syn.get("drying_time"), syn.get("drying_time_unit")
            )

        # characterization fields
        char = catalyst.get("characterization")
        if isinstance(char, dict):
            char["bet_area_unit"] = _norm_bet_unit(char.get("bet_area_unit"))
            char["total_pore_volume_unit"] = _norm_pore_vol_unit(char.get("total_pore_volume_unit"))
            char["micropore_volume_unit"] = _norm_pore_vol_unit(char.get("micropore_volume_unit"))
            for prefix in ("total", "bronsted", "lewis", "strong", "weak"):
                vk, uk = f"{prefix}_acidity", f"{prefix}_acidity_unit"
                char[vk], char[uk] = _norm_acidity(char.get(vk), char.get(uk))
            # strong/weak % → back-calculate mmol/g from total_acidity (must run after _norm_acidity)
            total_acidity = char.get("total_acidity")
            for prefix in ("strong", "weak"):
                vk, uk = f"{prefix}_acidity", f"{prefix}_acidity_unit"
                char[vk], char[uk] = _norm_partial_acidity(char.get(vk), char.get(uk), total_acidity)

    for reaction in payload.get("reactions") or []:
        if not isinstance(reaction, dict):
            continue

        # substrate_name
        sub = reaction.get("substrate")
        if isinstance(sub, dict):
            sub["substrate_name"] = _norm_substrate(sub.get("substrate_name"))

        # conditions
        conds = reaction.get("conditions")
        if isinstance(conds, dict):
            conds["reaction_temperature"], conds["reaction_temperature_unit"] = _norm_temp(
                conds.get("reaction_temperature"), conds.get("reaction_temperature_unit")
            )
            conds["reaction_time"], conds["reaction_time_unit"] = _norm_time_value(
                conds.get("reaction_time"), conds.get("reaction_time_unit")
            )
            conds["reaction_pressure"], conds["reaction_pressure_unit"] = _norm_pressure(
                conds.get("reaction_pressure"), conds.get("reaction_pressure_unit")
            )
            conds["solvent_name"] = _norm_solvent(conds.get("solvent_name"))
            conds["solvent_volume_unit"] = _norm_solvent_vol_unit(conds.get("solvent_volume_unit"))
            conds["substrate_mass"], conds["substrate_mass_unit"] = _norm_mass(
                conds.get("substrate_mass"), conds.get("substrate_mass_unit")
            )
            conds["catalyst_amount"], conds["catalyst_amount_unit"] = _norm_mass(
                conds.get("catalyst_amount"), conds.get("catalyst_amount_unit")
            )
            substrate_name = reaction.get("substrate", {}).get("substrate_name") if isinstance(reaction.get("substrate"), dict) else None
            conds["substrate_concentration"], conds["substrate_concentration_unit"] = _norm_concentration(
                conds.get("substrate_concentration"), conds.get("substrate_concentration_unit"), substrate_name
            )
            conds["catalyst_loading_unit"] = _norm_wt_pct_unit(
                conds.get("catalyst_loading_unit")
            )

        # performance_metrics product_name
        for metric in reaction.get("performance_metrics") or []:
            if isinstance(metric, dict):
                metric["product_name"] = _norm_product(metric.get("product_name"))

    return payload


REQUIRED_TOP_LEVEL_KEYS = ("paper", "catalysts", "reactions", "extraction_meta")
HOMOGENEOUS_CATALYST_PATTERNS = (
    "hcl",
    "hydrochloricacid",
    "h2so4",
    "sulfuricacid",
    "oxalicacid",
    "formicacid",
    "aceticacid",
    "alcl3",
    "crcl",
    "sncl",
    "zrcl",
    "la(otf)3",
)
AGGREGATED_VALUE_MARKERS = ("various", "different", "multiple")


def validate_extraction_file(paper_dir: Path) -> dict:
    extraction_path = paper_dir / "07_extraction.json"
    payload = json.loads(extraction_path.read_text(encoding="utf-8"))
    # Normalize field values and write them back in place (Judge and Repair receive the cleaned data)
    payload = normalize_extraction_payload(payload)
    extraction_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = validate_extraction_payload(payload)
    _validate_table_reaction_coverage(payload, paper_dir, report["issues"])
    _validate_empty_reactions_against_agent_input(payload, paper_dir, report["issues"])
    report["status"] = "fail" if _has_error_issue(report["issues"]) else "pass"
    (paper_dir / "08_validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def validate_extraction_payload(payload: dict) -> dict:
    issues: list[dict[str, str]] = []
    _validate_top_level(payload, issues)
    schema_version = payload.get("extraction_meta", {}).get("schema_version")
    if schema_version == "v1":
        _validate_v1_schema(payload, issues)

    catalysts = payload.get("catalysts")
    reactions = payload.get("reactions")
    catalyst_ids = _collect_catalyst_ids(catalysts if isinstance(catalysts, list) else [])
    if schema_version == "v1" and isinstance(catalysts, list):
        for index, catalyst in enumerate(catalysts):
            if isinstance(catalyst, dict):
                _validate_v1_catalyst_scope(catalyst, index, issues)

    missing_evidence_count = 0
    if isinstance(reactions, list):
        for index, reaction in enumerate(reactions):
            if not isinstance(reaction, dict):
                _add_issue(issues, f"reactions[{index}]", "Reaction must be an object.")
                continue
            if not _has_text(reaction.get("evidence")):
                missing_evidence_count += 1
                _add_issue(issues, f"reactions[{index}].evidence", "Reaction evidence is required.")
            catalyst_id = reaction.get("catalyst_id")
            if schema_version == "v1" and not _has_text(catalyst_id):
                _add_issue(
                    issues,
                    f"reactions[{index}].catalyst_id",
                    "v1 reactions must reference a catalyst_id.",
                )
            elif catalyst_id is not None and catalyst_id not in catalyst_ids:
                _add_issue(
                    issues,
                    f"reactions[{index}].catalyst_id",
                    "Reaction catalyst_id does not match any catalyst.",
                )
            if schema_version == "v1":
                _validate_v1_reaction_scope(reaction, index, issues)
                _validate_v1_reaction_conditions(reaction, index, issues)
                _validate_v1_performance_metrics(reaction, index, issues)
            else:
                _validate_reaction_metrics(reaction, index, issues)

    return {
        "status": "fail" if _has_error_issue(issues) else "pass",
        "issues": issues,
        "stats": {
            "catalysts_count": len(catalysts) if isinstance(catalysts, list) else 0,
            "reactions_count": len(reactions) if isinstance(reactions, list) else 0,
            "missing_reaction_evidence_count": missing_evidence_count,
        },
    }


def _validate_top_level(payload: dict, issues: list[dict[str, str]]) -> None:
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in payload:
            _add_issue(issues, key, "Required top-level key is missing.")
    if "catalysts" in payload and not isinstance(payload["catalysts"], list):
        _add_issue(issues, "catalysts", "Catalysts must be a list.")
    if "reactions" in payload and not isinstance(payload["reactions"], list):
        _add_issue(issues, "reactions", "Reactions must be a list.")


def _validate_v1_schema(payload: dict, issues: list[dict[str, str]]) -> None:
    schema_path = Path(__file__).resolve().parents[3] / "schemas" / "extraction.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path)):
        path = ".".join(str(part) for part in error.path)
        _add_issue(issues, f"schema.{path or '$'}", error.message)


def _collect_catalyst_ids(catalysts: list[Any]) -> set[str]:
    ids: set[str] = set()
    for catalyst in catalysts:
        if isinstance(catalyst, dict) and _has_text(catalyst.get("catalyst_id")):
            ids.add(catalyst["catalyst_id"])
    return ids


def _validate_v1_catalyst_scope(
    catalyst: dict, index: int, issues: list[dict[str, str]]
) -> None:
    name = _normalized_text(catalyst.get("catalyst_name"))
    if name and any(pattern in name for pattern in HOMOGENEOUS_CATALYST_PATTERNS):
        _add_issue(
            issues,
            f"catalysts[{index}].catalyst_name",
            "Homogeneous acid or soluble catalyst is out of scope for heterogeneous catalyst extraction.",
        )

    support_status = catalyst.get("support_status")
    support_class = catalyst.get("support_class")
    unsupported_class = catalyst.get("unsupported_class")
    if support_status == "supported":
        if support_class in (None, "", "none"):
            _add_issue(
                issues,
                f"catalysts[{index}].support_class",
                "Supported catalysts must have support_class other than none.",
            )
        if unsupported_class != "none":
            _add_issue(
                issues,
                f"catalysts[{index}].unsupported_class",
                "Supported catalysts must use unsupported_class=none.",
            )
    elif support_status == "unsupported":
        if support_class != "none":
            _add_issue(
                issues,
                f"catalysts[{index}].support_class",
                "Unsupported catalysts must use support_class=none.",
            )
        if unsupported_class in (None, "", "none"):
            _add_issue(
                issues,
                f"catalysts[{index}].unsupported_class",
                "Unsupported catalysts must have unsupported_class other than none.",
            )


def _validate_reaction_metrics(reaction: dict, index: int, issues: list[dict[str, str]]) -> None:
    _validate_metric_object(
        reaction.get("substrate_conversion"),
        f"reactions[{index}].substrate_conversion",
        issues,
    )
    conditions = reaction.get("reaction_conditions")
    if isinstance(conditions, dict):
        for name in ("temperature", "time"):
            _validate_metric_object(
                conditions.get(name),
                f"reactions[{index}].reaction_conditions.{name}",
                issues,
            )


def _validate_v1_performance_metrics(
    reaction: dict, index: int, issues: list[dict[str, str]]
) -> None:
    metrics = reaction.get("performance_metrics")
    if metrics is None:
        return
    if not isinstance(metrics, list):
        _add_issue(
            issues,
            f"reactions[{index}].performance_metrics",
            "Performance metrics must be a list.",
        )
        return
    for metric_index, metric in enumerate(metrics):
        path = f"reactions[{index}].performance_metrics[{metric_index}]"
        if not isinstance(metric, dict):
            _add_issue(issues, path, "Performance metric must be an object.")
            continue
        if not _has_text(metric.get("evidence")):
            _add_issue(issues, f"{path}.evidence", "Performance metric evidence is required.")
        elif _references_homogeneous_catalyst(metric.get("evidence")):
            _add_issue(
                issues,
                f"{path}.evidence",
                "Performance metric evidence references a homogeneous acid or soluble catalyst.",
            )
        value = metric.get("value")
        if value is not None and not isinstance(value, (int, float)):
            _add_issue(issues, f"{path}.value", "Metric value must be numeric or null.")
    # Deduplicate product_name=others entries by a triple (different by-products have different values and are not duplicates)
    dedup_keys = [
        (metric.get("metric_name"), metric.get("product_name"), metric.get("value"))
        if metric.get("product_name") == "others"
        else (metric.get("metric_name"), metric.get("product_name"))
        for metric in metrics
        if isinstance(metric, dict)
    ]
    if len(dedup_keys) != len(set(dedup_keys)):
        _add_issue(
            issues,
            f"reactions[{index}].performance_metrics",
            "Duplicate metric/product pairs in one reaction indicate merged table rows.",
        )


def _validate_v1_reaction_conditions(
    reaction: dict, index: int, issues: list[dict[str, str]]
) -> None:
    conditions = reaction.get("conditions")
    if not isinstance(conditions, dict):
        return
    for key in (
        "solvent_name",
        "catalyst_loading",
        "reaction_temperature",
        "reaction_time",
        "catalyst_amount",
    ):
        value = conditions.get(key)
        if _has_aggregated_marker(value):
            _add_issue(
                issues,
                f"reactions[{index}].conditions.{key}",
                "Aggregated condition values such as 'various' indicate merged table rows.",
            )


def _validate_v1_reaction_scope(
    reaction: dict, index: int, issues: list[dict[str, str]]
) -> None:
    if _references_homogeneous_catalyst(reaction.get("evidence")):
        _add_issue(
            issues,
            f"reactions[{index}].evidence",
            "Reaction evidence references a homogeneous acid or soluble catalyst.",
        )


def _validate_metric_object(metric: Any, path: str, issues: list[dict[str, str]]) -> None:
    if metric is None:
        return
    if not isinstance(metric, dict):
        _add_issue(issues, path, "Metric must be an object or null.")
        return
    value = metric.get("value")
    if value is not None and not isinstance(value, (int, float)):
        _add_issue(issues, f"{path}.value", "Metric value must be numeric or null.")


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalized_text(value: Any) -> str:
    return value.lower().replace(" ", "") if isinstance(value, str) else ""


def _has_aggregated_marker(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    return any(marker in normalized for marker in AGGREGATED_VALUE_MARKERS)


def _references_homogeneous_catalyst(value: Any) -> bool:
    normalized = _normalized_text(value)
    return bool(normalized) and any(
        pattern in normalized for pattern in HOMOGENEOUS_CATALYST_PATTERNS
    )


PERFORMANCE_TABLE_KEYWORDS = ("yield", "conversion", "selectivity")


def _validate_empty_reactions_against_agent_input(
    payload: dict, paper_dir: Path, issues: list[dict[str, str]]
) -> None:
    """Flag the case where extraction returned zero reactions while the
    Agent Input clearly contains a reaction performance table.

    Observed on P000012: the LLM extraction is not perfectly deterministic
    across runs -- one run correctly extracted catalysts and reactions,
    another run on the same paper returned an empty reactions array with
    extraction_meta.notes saying "No reaction data found", even though the
    Agent Input had a populated "## Textual Tables" section. An empty
    reactions list does not violate any schema or scope rule on its own, so
    without this check the paper would pass validation and judge, and reach
    the database with zero rows of usable data despite having looked
    "accepted" in the report.

    The check requires yield/conversion/selectivity keywords in the tables
    section, not just any "## Textual Tables" heading: a second run on
    P000012 showed the Agent Input can legitimately contain only
    characterization tables (BET area, XPS, acidity) with no performance
    table at all, in which case zero reactions is the correct outcome and
    must not be flagged.
    """
    reactions = payload.get("reactions")
    if not isinstance(reactions, list) or reactions:
        return
    agent_input_path = paper_dir / "05_agent_input.md"
    if not agent_input_path.exists():
        return
    agent_input_text = agent_input_path.read_text(encoding="utf-8")
    if "## Textual Tables" not in agent_input_text:
        return
    tables_section = agent_input_text.split("## Textual Tables", 1)[1].lower()
    if any(keyword in tables_section for keyword in PERFORMANCE_TABLE_KEYWORDS):
        _add_issue(
            issues,
            "reactions",
            "Extraction returned zero reactions but the Agent Input has a "
            "Textual Tables section containing yield/conversion/selectivity "
            "data. This is likely a failed extraction run, not a paper "
            "with no usable reaction data.",
        )


def _validate_table_reaction_coverage(
    payload: dict, paper_dir: Path, issues: list[dict[str, str]]
) -> None:
    table_dir = paper_dir / "04_tables"
    if not table_dir.exists():
        return
    extracted_names = _reaction_catalyst_names(payload)
    for table_path in sorted(table_dir.glob("*.csv")):
        with table_path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            if not reader.fieldnames:
                continue
            catalyst_column = _find_exact_column(reader.fieldnames, "catalyst")
            if catalyst_column is None:
                continue
            if not _has_performance_column(reader.fieldnames):
                continue
            entry_column = _find_column(reader.fieldnames, ("entry", "run"))
            for row_index, row in enumerate(reader, start=2):
                catalyst_name = (row.get(catalyst_column) or "").strip()
                if not catalyst_name or not _is_valid_heterogeneous_table_catalyst(catalyst_name):
                    continue
                if _normalized_catalyst_key(catalyst_name) not in extracted_names:
                    row_label = row.get(entry_column) if entry_column else str(row_index)
                    _add_issue(
                        issues,
                        f"tables.{table_path.name}.row[{row_label}]",
                        "Valid heterogeneous catalyst table row is missing from extraction: "
                        f"{catalyst_name}.",
                        severity="warning",
                    )


def _reaction_catalyst_names(payload: dict) -> set[str]:
    names_by_id: dict[str, str] = {}
    catalysts = payload.get("catalysts")
    if isinstance(catalysts, list):
        for catalyst in catalysts:
            if isinstance(catalyst, dict):
                catalyst_id = catalyst.get("catalyst_id")
                key = _normalized_catalyst_key(catalyst.get("catalyst_name"))
                if isinstance(catalyst_id, str) and key:
                    names_by_id[catalyst_id] = key
    names: set[str] = set()
    reactions = payload.get("reactions")
    if isinstance(reactions, list):
        for reaction in reactions:
            if isinstance(reaction, dict):
                key = names_by_id.get(reaction.get("catalyst_id"))
                if key:
                    names.add(key)
    return names


def _find_column(columns: list[str], tokens: tuple[str, ...]) -> str | None:
    for column in columns:
        normalized = column.strip().lower()
        if any(token in normalized for token in tokens):
            return column
    return None


def _find_exact_column(columns: list[str], name: str) -> str | None:
    expected = name.strip().lower()
    for column in columns:
        if column.strip().lower() == expected:
            return column
    return None


def _has_performance_column(columns: list[str]) -> bool:
    return any(
        any(token in column.strip().lower() for token in ("yield", "conversion", "selectivity"))
        for column in columns
    )


def _is_valid_heterogeneous_table_catalyst(name: str) -> bool:
    normalized = _normalized_text(name)
    if not normalized:
        return False
    if "nocatalyst" in normalized or normalized in {"blank", "none"}:
        return False
    return not any(pattern in normalized for pattern in HOMOGENEOUS_CATALYST_PATTERNS)


def _normalized_catalyst_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.lower()
    text = re.sub(r"\b\d+\s*[-+]", "", text)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\s+[a-z]\s*$", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _add_issue(
    issues: list[dict[str, str]], path: str, message: str, severity: str = "error"
) -> None:
    issues.append({"severity": severity, "path": path, "message": message})


def _has_error_issue(issues: list[dict[str, str]]) -> bool:
    return any(issue.get("severity") == "error" for issue in issues)
