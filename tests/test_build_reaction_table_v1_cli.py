from __future__ import annotations

import csv
import json
from pathlib import Path

from multicat.database_builder.build_reaction_table_v1_cli import build_v1_csvs


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
                "metals": [],
                "synthesis": {},
                "characterization": {},
                "evidence": "Catalyst evidence.",
            }
        ],
        "reactions": [
            {
                "reaction_id": "rxn_001",
                "paper_id": "P000001",
                "catalyst_id": "cat_001",
                "substrate": {},
                "conditions": {},
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


def test_build_v1_csvs_writes_audit_and_ml_tables(tmp_path: Path):
    paper_dir = tmp_path / "papers" / "P000001"
    paper_dir.mkdir(parents=True)
    (paper_dir / "07_extraction.json").write_text(
        json.dumps(_payload_v1(), ensure_ascii=False),
        encoding="utf-8",
    )
    (paper_dir / "08_validation.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    (paper_dir / "09_judge.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")

    audit_path, ml_path = build_v1_csvs(tmp_path / "papers", tmp_path / "outputs")

    assert audit_path.name == "reaction_audit_table_v1.csv"
    assert ml_path.name == "ml_ready_table_v1.csv"
    with audit_path.open(encoding="utf-8-sig", newline="") as handle:
        audit_rows = list(csv.DictReader(handle))
    with ml_path.open(encoding="utf-8-sig", newline="") as handle:
        ml_rows = list(csv.DictReader(handle))
    assert audit_rows[0]["paper_id"] == "P000001"
    assert ml_rows[0]["record_id"] == "P000001_rxn_001"
