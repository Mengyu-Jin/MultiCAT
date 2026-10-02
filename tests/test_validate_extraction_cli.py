from __future__ import annotations

import json
from pathlib import Path

from multicat.validator.validate_extraction_cli import run_validation


def test_run_validation_writes_report_for_paper_id(tmp_path: Path):
    paper_dir = tmp_path / "papers" / "P000001"
    paper_dir.mkdir(parents=True)
    payload = {
        "paper": {"paper_id": "P000001"},
        "catalysts": [{"catalyst_id": "cat_1"}],
        "reactions": [{"catalyst_id": "cat_1", "evidence": "Table 1."}],
        "extraction_meta": {},
    }
    (paper_dir / "07_extraction.json").write_text(json.dumps(payload), encoding="utf-8")

    report = run_validation("P000001", tmp_path / "papers")

    assert report["status"] == "pass"
    assert (paper_dir / "08_validation.json").exists()
