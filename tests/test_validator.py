from __future__ import annotations

import json
from pathlib import Path

from multicat.validator.extraction_validator import (
    validate_extraction_file,
    validate_extraction_payload,
)


def _valid_payload() -> dict:
    return {
        "paper": {"paper_id": "P000001"},
        "catalysts": [{"catalyst_id": "cat_1", "catalyst_name": "Nb-Al"}],
        "reactions": [
            {
                "reaction_id": "rxn_1",
                "paper_id": "P000001",
                "catalyst_id": "cat_1",
                "substrate": {"name": "glucose"},
                "reaction_conditions": {
                    "temperature": {"value": 150, "unit": "C", "original_label": "150 C"},
                    "time": {"value": 4, "unit": "h", "original_label": "4 h"},
                },
                "products": [{"product_name": "HMF", "yield": {"value": 59, "unit": "%"}}],
                "substrate_conversion": {"value": 90, "unit": "%", "original_label": "conversion"},
                "evidence": "Table 1 reports glucose conversion and HMF yield.",
                "source_type": "table",
            }
        ],
        "extraction_meta": {"status": "complete"},
    }


def test_validate_extraction_payload_passes_minimal_valid_result():
    report = validate_extraction_payload(_valid_payload())

    assert report["status"] == "pass"
    assert report["issues"] == []
    assert report["stats"] == {
        "catalysts_count": 1,
        "reactions_count": 1,
        "missing_reaction_evidence_count": 0,
    }


def test_validate_extraction_payload_flags_missing_evidence_and_bad_catalyst_reference():
    payload = _valid_payload()
    payload["reactions"][0]["catalyst_id"] = "cat_missing"
    payload["reactions"][0]["evidence"] = ""

    report = validate_extraction_payload(payload)

    assert report["status"] == "fail"
    assert {
        "severity": "error",
        "path": "reactions[0].evidence",
        "message": "Reaction evidence is required.",
    } in report["issues"]
    assert {
        "severity": "error",
        "path": "reactions[0].catalyst_id",
        "message": "Reaction catalyst_id does not match any catalyst.",
    } in report["issues"]


def test_validate_extraction_payload_flags_non_numeric_value_fields():
    payload = _valid_payload()
    payload["reactions"][0]["substrate_conversion"]["value"] = "ninety"

    report = validate_extraction_payload(payload)

    assert report["status"] == "fail"
    assert {
        "severity": "error",
        "path": "reactions[0].substrate_conversion.value",
        "message": "Metric value must be numeric or null.",
    } in report["issues"]


def test_validate_extraction_file_writes_validation_report(tmp_path: Path):
    paper_dir = tmp_path / "P000001"
    paper_dir.mkdir()
    (paper_dir / "07_extraction.json").write_text(
        json.dumps(_valid_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    report = validate_extraction_file(paper_dir)

    assert report["status"] == "pass"
    saved = json.loads((paper_dir / "08_validation.json").read_text(encoding="utf-8"))
    assert saved == report


def test_validate_extraction_file_flags_missing_valid_heterogeneous_table_rows(tmp_path: Path):
    paper_dir = tmp_path / "P000003"
    table_dir = paper_dir / "04_tables"
    table_dir.mkdir(parents=True)
    payload = _valid_payload()
    payload["paper"] = {"paper_id": "P000003"}
    payload["catalysts"] = [{"catalyst_id": "cat_001", "catalyst_name": "CCC"}]
    payload["reactions"][0]["paper_id"] = "P000003"
    payload["reactions"][0]["catalyst_id"] = "cat_001"
    payload["reactions"][0]["evidence"] = "Table 1 Entry 2"
    (paper_dir / "07_extraction.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    (table_dir / "Table1.csv").write_text(
        "\n".join(
            [
                "Entry,Catalyst,HMF yield (%),Glucose conversion (%)",
                "1,No catalyst,1.5,2.7",
                "2,CCC,41.2,60.7",
                "3,H-mordenite (25),14.3,29.5",
                "4,HCl b,18.3,39.4",
            ]
        ),
        encoding="utf-8",
    )

    report = validate_extraction_file(paper_dir)

    # Missing table rows are reported as a warning, not a blocking error: the
    # goal is broad data collection, so a paper with some incomplete table
    # coverage should still have its successfully extracted reactions pass
    # validation and reach the database, rather than being rejected outright.
    assert report["status"] == "pass"
    assert {
        "severity": "warning",
        "path": "tables.Table1.csv.row[3]",
        "message": "Valid heterogeneous catalyst table row is missing from extraction: H-mordenite (25).",
    } in report["issues"]


def test_validate_extraction_file_requires_reaction_for_valid_table_catalyst_row(
    tmp_path: Path,
):
    paper_dir = tmp_path / "P000003"
    table_dir = paper_dir / "04_tables"
    table_dir.mkdir(parents=True)
    payload = _valid_payload()
    payload["paper"] = {"paper_id": "P000003"}
    payload["catalysts"] = [
        {"catalyst_id": "cat_001", "catalyst_name": "CCC"},
        {"catalyst_id": "cat_002", "catalyst_name": "H-mordenite"},
    ]
    payload["reactions"][0]["paper_id"] = "P000003"
    payload["reactions"][0]["catalyst_id"] = "cat_001"
    payload["reactions"][0]["evidence"] = "Table 1 Entry 2"
    (paper_dir / "07_extraction.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    (table_dir / "Table1.csv").write_text(
        "\n".join(
            [
                "Entry,Catalyst,HMF yield (%),Glucose conversion (%)",
                "2,CCC,41.2,60.7",
                "3,H-mordenite (25),14.3,29.5",
            ]
        ),
        encoding="utf-8",
    )

    report = validate_extraction_file(paper_dir)

    assert report["status"] == "pass"
    assert {
        "severity": "warning",
        "path": "tables.Table1.csv.row[3]",
        "message": "Valid heterogeneous catalyst table row is missing from extraction: H-mordenite (25).",
    } in report["issues"]


def test_validate_extraction_file_matches_charge_and_footnote_catalyst_names(
    tmp_path: Path,
):
    paper_dir = tmp_path / "P000003"
    table_dir = paper_dir / "04_tables"
    table_dir.mkdir(parents=True)
    payload = _valid_payload()
    payload["paper"] = {"paper_id": "P000003"}
    payload["catalysts"] = [
        {"catalyst_id": "cat_001", "catalyst_name": "SO4/ZrO2"},
        {"catalyst_id": "cat_002", "catalyst_name": "ICC"},
    ]
    payload["reactions"] = [
        {**payload["reactions"][0], "catalyst_id": "cat_001", "evidence": "Table 1 Entry 6"},
        {**payload["reactions"][0], "catalyst_id": "cat_002", "evidence": "Table 1 Entry 12"},
    ]
    (paper_dir / "07_extraction.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    (table_dir / "Table1.csv").write_text(
        "\n".join(
            [
                "Entry,Catalyst,HMF yield (%),Glucose conversion (%)",
                "6,SO 4 2 - /ZrO 2,15.3,29.8",
                "12,ICC d,2.1,3.8",
            ]
        ),
        encoding="utf-8",
    )

    report = validate_extraction_file(paper_dir)

    assert report["status"] == "pass"
    assert report["issues"] == []


def test_validate_extraction_file_does_not_treat_catalyst_loading_as_catalyst_column(
    tmp_path: Path,
):
    paper_dir = tmp_path / "P000003"
    table_dir = paper_dir / "04_tables"
    table_dir.mkdir(parents=True)
    (paper_dir / "07_extraction.json").write_text(
        json.dumps(_valid_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    (table_dir / "Table2.csv").write_text(
        "\n".join(
            [
                "Entry,Catalyst loading (wt.%),HMF yield (%),Glucose conversion (%)",
                "1,10,17.6,33.9",
                "2,20,29.2,44.8",
            ]
        ),
        encoding="utf-8",
    )

    report = validate_extraction_file(paper_dir)

    assert report["status"] == "pass"
    assert report["issues"] == []


def _valid_v1_payload() -> dict:
    return {
        "paper": {
            "paper_id": "P000001",
            "doi": "10.0000/example",
            "title": "Example",
            "journal": "Journal",
            "year": 2026,
            "publisher": "publisher",
            "xml_source": "pmc",
        },
        "catalysts": [
            {
                "catalyst_id": "cat_001",
                "catalyst_name": "Sn-Beta",
                "support_status": "supported",
                "support_class": "zeolite_silica",
                "unsupported_class": "none",
                "composition_raw": "Sn-Beta",
                "metals": [],
                "synthesis": {
                    "synthesis_method": "unknown",
                    "modification_method": "unknown",
                    "calcination_temp": None,
                    "calcination_temp_unit": None,
                    "calcination_time": None,
                    "calcination_time_unit": None,
                    "hydrothermal_temp": None,
                    "hydrothermal_temp_unit": None,
                    "hydrothermal_time": None,
                    "hydrothermal_time_unit": None,
                    "drying_temp": None,
                    "drying_temp_unit": None,
                    "drying_time": None,
                    "drying_time_unit": None,
                    "synthesis_text": None,
                },
                "characterization": {
                    "bet_area": None,
                    "bet_area_unit": None,
                    "total_pore_volume": None,
                    "total_pore_volume_unit": None,
                    "micropore_volume": None,
                    "micropore_volume_unit": None,
                    "bronsted_acidity": None,
                    "bronsted_acidity_unit": None,
                    "lewis_acidity": None,
                    "lewis_acidity_unit": None,
                    "strong_acidity": None,
                    "strong_acidity_unit": None,
                    "weak_acidity": None,
                    "weak_acidity_unit": None,
                    "total_acidity": None,
                    "total_acidity_unit": None,
                    "characterization_text": None,
                },
                "evidence": "Catalyst evidence.",
            }
        ],
        "reactions": [
            {
                "reaction_id": "rxn_001",
                "paper_id": "P000001",
                "catalyst_id": "cat_001",
                "substrate": {
                    "substrate_name": "glucose",
                    "substrate_class": "c6_sugar",
                    "substrate_origin": "model_compound",
                    "is_polymeric": False,
                },
                "conditions": {
                    "reaction_method": "batch",
                    "reaction_temperature": 150,
                    "reaction_temperature_unit": "C",
                    "reaction_time": 4,
                    "reaction_time_unit": "h",
                    "reaction_pressure": None,
                    "reaction_pressure_unit": None,
                    "reaction_atmosphere": "sealed",
                    "substrate_mass": None,
                    "substrate_mass_unit": None,
                    "substrate_concentration": None,
                    "substrate_concentration_unit": None,
                    "catalyst_amount": None,
                    "catalyst_amount_unit": None,
                    "catalyst_loading": None,
                    "catalyst_loading_unit": None,
                    "catalyst_substrate_ratio": None,
                    "catalyst_substrate_ratio_source": "none",
                    "solvent_name": None,
                    "solvent_volume": None,
                    "solvent_volume_unit": None,
                    "reactor_type": None,
                    "condition_text": None,
                },
                "performance_metrics": [
                    {
                        "metric_name": "yield",
                        "product_name": "hmf",
                        "value": 59,
                        "unit": "%",
                        "basis": "unknown",
                        "original_label": "HMF yield",
                        "evidence": "HMF yield was 59%.",
                    }
                ],
                "source_type": "table",
                "evidence": "Table 1.",
            }
        ],
        "extraction_meta": {"schema_version": "v1", "status": "complete", "notes": None},
    }


def test_validate_extraction_payload_accepts_v1_schema_and_metrics():
    report = validate_extraction_payload(_valid_v1_payload())

    assert report["status"] == "pass"
    assert report["issues"] == []
    assert report["stats"]["catalysts_count"] == 1
    assert report["stats"]["reactions_count"] == 1


def test_validate_extraction_payload_flags_v1_metric_missing_evidence():
    payload = _valid_v1_payload()
    payload["reactions"][0]["performance_metrics"][0]["evidence"] = ""

    report = validate_extraction_payload(payload)

    assert report["status"] == "fail"
    assert {
        "severity": "error",
        "path": "reactions[0].performance_metrics[0].evidence",
        "message": "Performance metric evidence is required.",
    } in report["issues"]


def test_validate_extraction_payload_flags_v1_schema_violation():
    payload = _valid_v1_payload()
    payload["reactions"][0]["substrate_conversion"] = {"value": 90, "unit": "%"}

    report = validate_extraction_payload(payload)

    assert report["status"] == "fail"
    assert any(issue["path"].startswith("schema.") for issue in report["issues"])


def test_validate_extraction_payload_flags_duplicate_v1_metric_product_pair():
    payload = _valid_v1_payload()
    payload["reactions"][0]["performance_metrics"].append(
        {
            "metric_name": "yield",
            "product_name": "hmf",
            "value": 61,
            "unit": "%",
            "basis": "unknown",
            "original_label": "HMF yield",
            "evidence": "Second HMF yield row.",
        }
    )

    report = validate_extraction_payload(payload)

    assert report["status"] == "fail"
    assert {
        "severity": "error",
        "path": "reactions[0].performance_metrics",
        "message": "Duplicate metric/product pairs in one reaction indicate merged table rows.",
    } in report["issues"]


def test_validate_extraction_payload_flags_aggregated_v1_condition_values():
    payload = _valid_v1_payload()
    payload["reactions"][0]["conditions"]["solvent_name"] = "various solvents"

    report = validate_extraction_payload(payload)

    assert report["status"] == "fail"
    assert {
        "severity": "error",
        "path": "reactions[0].conditions.solvent_name",
        "message": "Aggregated condition values such as 'various' indicate merged table rows.",
    } in report["issues"]


def test_validate_extraction_payload_flags_homogeneous_catalyst_leakage():
    payload = _valid_v1_payload()
    payload["catalysts"][0]["catalyst_name"] = "HCl"
    payload["catalysts"][0]["support_status"] = "unsupported"
    payload["catalysts"][0]["support_class"] = "none"
    payload["catalysts"][0]["unsupported_class"] = "others"

    report = validate_extraction_payload(payload)

    assert report["status"] == "fail"
    assert {
        "severity": "error",
        "path": "catalysts[0].catalyst_name",
        "message": "Homogeneous acid or soluble catalyst is out of scope for heterogeneous catalyst extraction.",
    } in report["issues"]


def test_validate_extraction_payload_flags_homogeneous_catalyst_evidence_leakage():
    payload = _valid_v1_payload()
    payload["reactions"][0]["evidence"] = "Table 1 entry 1 reports performance with HCl catalyst."
    payload["reactions"][0]["performance_metrics"][0][
        "evidence"
    ] = "Table 1 entry 1 reports LA yield with HCl catalyst."

    report = validate_extraction_payload(payload)

    assert report["status"] == "fail"
    assert {
        "severity": "error",
        "path": "reactions[0].evidence",
        "message": "Reaction evidence references a homogeneous acid or soluble catalyst.",
    } in report["issues"]
    assert {
        "severity": "error",
        "path": "reactions[0].performance_metrics[0].evidence",
        "message": "Performance metric evidence references a homogeneous acid or soluble catalyst.",
    } in report["issues"]


def test_validate_extraction_payload_flags_v1_support_class_conflict():
    payload = _valid_v1_payload()
    payload["catalysts"][0]["support_status"] = "supported"
    payload["catalysts"][0]["support_class"] = "none"
    payload["catalysts"][0]["unsupported_class"] = "metal_oxide"

    report = validate_extraction_payload(payload)

    assert report["status"] == "fail"
    assert {
        "severity": "error",
        "path": "catalysts[0].support_class",
        "message": "Supported catalysts must have support_class other than none.",
    } in report["issues"]
    assert {
        "severity": "error",
        "path": "catalysts[0].unsupported_class",
        "message": "Supported catalysts must use unsupported_class=none.",
    } in report["issues"]


def test_validate_extraction_payload_flags_missing_v1_reaction_catalyst_id():
    payload = _valid_v1_payload()
    payload["reactions"][0]["catalyst_id"] = None

    report = validate_extraction_payload(payload)

    assert report["status"] == "fail"
    assert {
        "severity": "error",
        "path": "reactions[0].catalyst_id",
        "message": "v1 reactions must reference a catalyst_id.",
    } in report["issues"]


def test_validate_extraction_file_warning_does_not_block_other_error_detection(tmp_path: Path):
    """Regression test: missing table rows are downgraded to warnings so that
    a paper with incomplete table coverage still has its extracted reactions
    reach the database (broad data collection over per-paper completeness).
    This must not weaken real error detection -- a genuine schema violation
    alongside a missing-row warning must still fail validation.
    """
    paper_dir = tmp_path / "P000099"
    table_dir = paper_dir / "04_tables"
    table_dir.mkdir(parents=True)
    payload = _valid_payload()
    payload["paper"] = {"paper_id": "P000099"}
    payload["catalysts"] = [{"catalyst_id": "cat_001", "catalyst_name": "CCC"}]
    payload["reactions"][0]["paper_id"] = "P000099"
    payload["reactions"][0]["catalyst_id"] = "cat_001"
    payload["reactions"][0]["evidence"] = ""  # real error: missing evidence
    (paper_dir / "07_extraction.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    (table_dir / "Table1.csv").write_text(
        "\n".join(
            [
                "Entry,Catalyst,HMF yield (%),Glucose conversion (%)",
                "1,CCC,41.2,60.7",
                "2,H-mordenite (25),14.3,29.5",  # missing from extraction -> warning
            ]
        ),
        encoding="utf-8",
    )

    report = validate_extraction_file(paper_dir)

    assert report["status"] == "fail"
    severities = {issue["severity"] for issue in report["issues"]}
    assert "error" in severities
    assert "warning" in severities


def test_validate_extraction_file_flags_empty_reactions_when_agent_input_has_tables(
    tmp_path: Path,
):
    """Regression test: observed on P000012, where LLM extraction is not
    perfectly deterministic across runs -- one run correctly extracted
    catalysts/reactions, another run on the identical paper returned an
    empty reactions array ("No reaction data found") even though the Agent
    Input clearly had a populated Textual Tables section. An empty
    reactions list violates no schema or scope rule on its own, so without
    this check the paper would pass validation+judge and reach the database
    with zero usable rows despite looking "accepted".
    """
    paper_dir = tmp_path / "P000012"
    paper_dir.mkdir(parents=True)
    payload = _valid_payload()
    payload["reactions"] = []
    payload["extraction_meta"] = {
        "status": "complete",
        "notes": "No reaction data found in the provided text.",
    }
    (paper_dir / "07_extraction.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    (paper_dir / "05_agent_input.md").write_text(
        "# Agent Input\n## Textual Tables\n| Catalyst | yield |\n| WO3 | 41.2 |",
        encoding="utf-8",
    )

    report = validate_extraction_file(paper_dir)

    assert report["status"] == "fail"
    assert {
        "severity": "error",
        "path": "reactions",
        "message": (
            "Extraction returned zero reactions but the Agent Input has a "
            "Textual Tables section containing yield/conversion/selectivity "
            "data. This is likely a failed extraction run, not a paper "
            "with no usable reaction data."
        ),
    } in report["issues"]


def test_validate_extraction_file_allows_empty_reactions_when_tables_are_characterization_only(
    tmp_path: Path,
):
    """Regression test: a second real run on P000012 showed the Agent Input
    can legitimately contain a "## Textual Tables" section with ONLY
    characterization tables (XPS surface concentrations, BET area, acid
    site density) and no performance table at all. In that case the LLM's
    "no reaction data found" conclusion is correct -- zero reactions must
    not be flagged just because some table heading exists.
    """
    paper_dir = tmp_path / "P000012"
    paper_dir.mkdir(parents=True)
    payload = _valid_payload()
    payload["reactions"] = []
    payload["extraction_meta"] = {
        "status": "complete",
        "notes": "No specific reaction data or performance metrics were found.",
    }
    (paper_dir / "07_extraction.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    (paper_dir / "05_agent_input.md").write_text(
        "# Agent Input\n"
        "## Textual Tables\n"
        "### Table 1\n"
        "Table 1 Atomic surface concentrations of W VI /W V\n"
        "| Sample | W VI 4f eV/% | W/dopant (XPS) |\n"
        "| --- | --- | --- |\n"
        "| WO3 | 35.9/94.4 | - |\n"
        "### Table 2\n"
        "Table 2 Physico-chemical properties\n"
        "| Material | S BET (m2 g-1) | N BAS,pyr |\n"
        "| --- | --- | --- |\n"
        "| WO3 | 17 | 0.029 |\n",
        encoding="utf-8",
    )

    report = validate_extraction_file(paper_dir)

    assert report["status"] == "pass"


def test_validate_extraction_file_allows_empty_reactions_without_tables_in_agent_input(
    tmp_path: Path,
):
    """A paper whose Agent Input genuinely has no reaction tables (e.g. text
    only, or fully pruned in ml_core mode) is a legitimately empty paper,
    not a failed extraction -- it must not be flagged.
    """
    paper_dir = tmp_path / "P000099"
    paper_dir.mkdir(parents=True)
    payload = _valid_payload()
    payload["reactions"] = []
    (paper_dir / "07_extraction.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    (paper_dir / "05_agent_input.md").write_text(
        "# Agent Input\n## Abstract\nNo tables here, only narrative text.",
        encoding="utf-8",
    )

    report = validate_extraction_file(paper_dir)

    assert report["status"] == "pass"
