from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


SCHEMA_PATH = Path("schemas/extraction.schema.json")


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _valid_payload() -> dict:
    return {
        "paper": {
            "paper_id": "P000001",
            "doi": "10.0000/example",
            "title": "Example paper",
            "journal": "Example Journal",
            "year": 2026,
            "publisher": "example",
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
                "metals": [
                    {
                        "element": "Sn",
                        "content_value": None,
                        "content_unit": None,
                        "content_label": None,
                        "role": "active",
                        "evidence": "Sn-Beta catalyst was used.",
                    }
                ],
                "synthesis": {
                    "synthesis_method": "hydrothermal",
                    "modification_method": "none",
                    "calcination_temp": 550,
                    "calcination_temp_unit": "C",
                    "calcination_time": 6,
                    "calcination_time_unit": "h",
                    "hydrothermal_temp": None,
                    "hydrothermal_temp_unit": None,
                    "hydrothermal_time": None,
                    "hydrothermal_time_unit": None,
                    "drying_temp": None,
                    "drying_temp_unit": None,
                    "drying_time": None,
                    "drying_time_unit": None,
                    "synthesis_text": "Calcined at 550 C for 6 h.",
                },
                "characterization": {
                    "bet_area": 500,
                    "bet_area_unit": "m2/g",
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
                    "characterization_text": "BET surface area was 500 m2/g.",
                },
                "evidence": "Sn-Beta catalyst was prepared and characterized.",
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
                    "substrate_mass": 450,
                    "substrate_mass_unit": "mg",
                    "substrate_concentration": None,
                    "substrate_concentration_unit": None,
                    "catalyst_amount": 50,
                    "catalyst_amount_unit": "mg",
                    "catalyst_loading": None,
                    "catalyst_loading_unit": None,
                    "catalyst_substrate_ratio": None,
                    "catalyst_substrate_ratio_source": "none",
                    "solvent_name": "DMSO",
                    "solvent_volume": 5,
                    "solvent_volume_unit": "mL",
                    "reactor_type": "sealed tube",
                    "condition_text": "450 mg glucose and 50 mg catalyst in 5 mL DMSO.",
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
                "evidence": "Table 1 reports HMF yield.",
            }
        ],
        "extraction_meta": {"schema_version": "v1", "status": "complete", "notes": None},
    }


def test_extraction_v1_schema_accepts_v1_payload():
    jsonschema.validate(_valid_payload(), _load_schema())


def test_extraction_v1_schema_rejects_old_substrate_conversion_field():
    payload = _valid_payload()
    payload["reactions"][0]["substrate_conversion"] = {"value": 90, "unit": "%"}

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _load_schema())
