import json
from pathlib import Path

from multicat.text_acquisition.asset_writer import write_text_package_assets


def test_write_text_package_assets_creates_markdown_json_and_table_csv(tmp_path):
    package = {
        "paper_id": "P000001",
        "metadata": {"doi": "10.0000/example"},
        "title": "Glucose conversion",
        "abstract": "Glucose was converted to HMF.",
        "sections": [{"title": "Results", "text": "HMF yield was 45%."}],
        "tables": [
            {
                "id": "t1",
                "caption": "Table 1 Reaction results.",
                "rows": [["Substrate", "Yield"], ["Glucose", "45%"]],
            }
        ],
        "figure_captions": [{"id": "f1", "caption": "Figure 1 Catalyst image."}],
        "source_format": "xml",
        "xml_type": "jats",
    }

    outputs = write_text_package_assets(package, tmp_path)

    assert outputs["markdown_path"] == tmp_path / "02_paper.md"
    assert outputs["json_path"] == tmp_path / "03_text_package.json"
    assert outputs["agent_input_path"] == tmp_path / "05_agent_input.md"
    assert outputs["table_paths"] == [tmp_path / "04_tables" / "Table1.csv"]
    assert "# Glucose conversion" in outputs["markdown_path"].read_text(encoding="utf-8")
    assert "# Agent Input: Glucose conversion" in outputs["agent_input_path"].read_text(encoding="utf-8")
    saved = json.loads(outputs["json_path"].read_text(encoding="utf-8"))
    assert saved["paper_id"] == "P000001"
    assert outputs["table_paths"][0].read_text(encoding="utf-8").splitlines()[1] == "Glucose,45%"
