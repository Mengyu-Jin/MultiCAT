from __future__ import annotations

import csv
import json
from pathlib import Path

from multicat.database_builder.reaction_table_builder_v1 import (
    build_audit_rows_v1,
    build_ml_rows_v1,
    write_v1_tables,
)


def _payload_v1() -> dict:
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
                        "content_value": 3,
                        "content_unit": "wt%",
                        "content_label": "3 wt% Sn",
                        "role": "active",
                        "evidence": "3 wt% Sn-Beta.",
                    },
                    {
                        "element": "Zr",
                        "content_value": 1,
                        "content_unit": "wt%",
                        "content_label": "1 wt% Zr",
                        "role": "promoter",
                        "evidence": "1 wt% Zr.",
                    },
                    {
                        "element": "Nb",
                        "content_value": 0.5,
                        "content_unit": "wt%",
                        "content_label": "0.5 wt% Nb",
                        "role": "promoter",
                        "evidence": "0.5 wt% Nb.",
                    },
                    {
                        "element": "Ti",
                        "content_value": 0.2,
                        "content_unit": "wt%",
                        "content_label": "0.2 wt% Ti",
                        "role": "promoter",
                        "evidence": "0.2 wt% Ti.",
                    },
                ],
                "synthesis": {
                    "synthesis_method": "hydrothermal",
                    "modification_method": "calcination",
                    "calcination_temp": 550,
                    "calcination_temp_unit": "C",
                    "calcination_time": 6,
                    "calcination_time_unit": "h",
                    "hydrothermal_temp": 180,
                    "hydrothermal_temp_unit": "C",
                    "hydrothermal_time": 24,
                    "hydrothermal_time_unit": "h",
                    "drying_temp": None,
                    "drying_temp_unit": None,
                    "drying_time": None,
                    "drying_time_unit": None,
                    "synthesis_text": "Hydrothermal synthesis and calcination.",
                },
                "characterization": {
                    "bet_area": 500,
                    "bet_area_unit": "m2/g",
                    "total_pore_volume": 0.5,
                    "total_pore_volume_unit": "cm3/g",
                    "micropore_volume": 0.1,
                    "micropore_volume_unit": "cm3/g",
                    "bronsted_acidity": 0.2,
                    "bronsted_acidity_unit": "mmol/g",
                    "lewis_acidity": 0.3,
                    "lewis_acidity_unit": "mmol/g",
                    "strong_acidity": None,
                    "strong_acidity_unit": None,
                    "weak_acidity": None,
                    "weak_acidity_unit": None,
                    "total_acidity": 0.5,
                    "total_acidity_unit": "mmol/g",
                    "characterization_text": "BET and acidity data.",
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
                    "condition_text": "Reaction condition evidence.",
                },
                "performance_metrics": [
                    {
                        "metric_name": "conversion",
                        "product_name": "none",
                        "value": 90,
                        "unit": "%",
                        "basis": "unknown",
                        "original_label": "glucose conversion",
                        "evidence": "Glucose conversion was 90%.",
                    },
                    {
                        "metric_name": "yield",
                        "product_name": "hmf",
                        "value": 59,
                        "unit": "%",
                        "basis": "unknown",
                        "original_label": "HMF yield",
                        "evidence": "HMF yield was 59%.",
                    },
                    {
                        "metric_name": "selectivity",
                        "product_name": "hmf",
                        "value": 65,
                        "unit": "%",
                        "basis": "unknown",
                        "original_label": "HMF selectivity",
                        "evidence": "HMF selectivity was 65%.",
                    },
                ],
                "source_type": "table",
                "evidence": "Table 1.",
            }
        ],
        "extraction_meta": {"schema_version": "v1", "status": "complete", "notes": None},
    }


def test_build_audit_rows_v1_flattens_trace_raw_and_performance_fields():
    row = build_audit_rows_v1(_payload_v1())[0]

    assert row["record_id"] == "P000001_rxn_001"
    assert row["paper_id"] == "P000001"
    assert row["catalyst_id"] == "cat_001"
    assert row["doi"] == "10.0000/example"
    assert row["catalyst_name"] == "Sn-Beta"
    assert row["num_metals"] == 4
    assert row["metal_1"] == "Sn"
    assert row["metal_3"] == "Nb"
    assert row["has_more_than_3_metals"] is True
    assert row["metals_all"] == "Sn;Zr;Nb;Ti"
    assert row["substrate_conversion"] == 90
    assert row["hmf_yield"] == 59
    assert row["hmf_selectivity"] == 65
    assert row["evidence"] == "Table 1."
    assert row["condition_text"] == "Reaction condition evidence."


def test_build_ml_rows_v1_keeps_minimal_trace_and_removes_audit_fields():
    row = build_ml_rows_v1(_payload_v1())[0]

    assert row["record_id"] == "P000001_rxn_001"
    assert row["doi"] == "10.0000/example"
    assert row["support_status"] == "supported"
    assert row["hmf_yield"] == 59
    assert "paper_id" not in row
    assert "reaction_id" not in row
    assert "catalyst_id" not in row
    assert "evidence" not in row
    assert "condition_text" not in row
    assert "composition_raw" not in row
    assert "reaction_temperature_unit" not in row


def test_write_v1_tables_writes_excel_friendly_csvs(tmp_path: Path):
    paper_dir = tmp_path / "papers" / "P000001"
    paper_dir.mkdir(parents=True)
    (paper_dir / "07_extraction.json").write_text(
        json.dumps(_payload_v1(), ensure_ascii=False),
        encoding="utf-8",
    )
    (paper_dir / "08_validation.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    (paper_dir / "09_judge.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")

    audit_path, ml_path = write_v1_tables(tmp_path / "papers", tmp_path / "outputs")

    assert audit_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert ml_path.read_bytes().startswith(b"\xef\xbb\xbf")
    with ml_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["record_id"] == "P000001_rxn_001"
    assert rows[0]["hmf_yield"] == "59"


def test_write_csv_retries_after_transient_permission_error(tmp_path, monkeypatch):
    """Regression test: on Windows, the summary CSV is often still locked by
    Excel or another viewer from a previous run when the pipeline tries to
    overwrite it (observed during a full 20-paper batch run). A transient
    PermissionError must be retried instead of immediately discarding the
    entire batch's results.
    """
    from multicat.database_builder import reaction_table_builder_v1 as module

    paper_dir = tmp_path / "papers" / "P000001"
    paper_dir.mkdir(parents=True)
    (paper_dir / "07_extraction.json").write_text(
        json.dumps(_payload_v1(), ensure_ascii=False),
        encoding="utf-8",
    )
    (paper_dir / "08_validation.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    (paper_dir / "09_judge.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")

    real_open = Path.open
    call_count = {"n": 0}

    def flaky_open(self, *args, **kwargs):
        if self.name == "ml_ready_table_v1.csv":
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise PermissionError("file is open in another program")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    audit_path, ml_path = write_v1_tables(tmp_path / "papers", tmp_path / "outputs")

    assert call_count["n"] == 2
    assert ml_path.exists()


def test_write_csv_raises_after_exhausting_retries_on_persistent_lock(tmp_path, monkeypatch):
    from multicat.database_builder import reaction_table_builder_v1 as module
    import pytest

    paper_dir = tmp_path / "papers" / "P000001"
    paper_dir.mkdir(parents=True)
    (paper_dir / "07_extraction.json").write_text(
        json.dumps(_payload_v1(), ensure_ascii=False),
        encoding="utf-8",
    )
    (paper_dir / "08_validation.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    (paper_dir / "09_judge.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")

    real_open = Path.open

    def always_locked_open(self, *args, **kwargs):
        if self.name == "ml_ready_table_v1.csv":
            raise PermissionError("file is open in another program")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(Path, "open", always_locked_open)

    with pytest.raises(PermissionError):
        write_v1_tables(tmp_path / "papers", tmp_path / "outputs")
