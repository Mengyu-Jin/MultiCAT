import json

from multicat.text_acquisition.qa import qa_paper_assets


def test_qa_paper_assets_passes_complete_package(tmp_path):
    (tmp_path / "01_paper.xml").write_text("<article/>", encoding="utf-8")
    (tmp_path / "02_paper.md").write_text("# Good title\n\nBody", encoding="utf-8")
    (tmp_path / "04_tables").mkdir()
    (tmp_path / "04_tables" / "Table1.csv").write_text("A,B\n1,2\n", encoding="utf-8")
    package = {
        "title": "Good title",
        "abstract": "A complete abstract.",
        "sections": [{"title": "Results", "text": "Useful result text."}],
        "tables": [{"rows": [["A", "B"], ["1", "2"]]}],
        "figure_captions": [],
    }
    (tmp_path / "03_text_package.json").write_text(json.dumps(package), encoding="utf-8")

    report = qa_paper_assets(tmp_path)

    assert report["status"] == "pass"
    assert report["issues"] == []


def test_qa_paper_assets_flags_missing_assets_and_empty_content(tmp_path):
    package = {
        "title": "",
        "abstract": "",
        "sections": [],
        "tables": [{"rows": [["A"], ["1"]]}],
        "figure_captions": [],
    }
    (tmp_path / "03_text_package.json").write_text(json.dumps(package), encoding="utf-8")

    report = qa_paper_assets(tmp_path)

    assert report["status"] == "fail"
    issue_codes = {issue["code"] for issue in report["issues"]}
    assert "missing_xml" in issue_codes
    assert "missing_markdown" in issue_codes
    assert "empty_title" in issue_codes
    assert "empty_abstract" in issue_codes
    assert "empty_sections" in issue_codes
    assert "table_count_mismatch" in issue_codes


def test_qa_paper_assets_flags_common_mojibake_patterns(tmp_path):
    (tmp_path / "01_paper.xml").write_text("<article/>", encoding="utf-8")
    (tmp_path / "02_paper.md").write_text("# Bad ¦Ă title", encoding="utf-8")
    package = {
        "title": "Bad ¦Ă title",
        "abstract": "A complete abstract.",
        "sections": [{"title": "Results", "text": "Useful result text."}],
        "tables": [],
        "figure_captions": [],
    }
    (tmp_path / "03_text_package.json").write_text(json.dumps(package), encoding="utf-8")

    report = qa_paper_assets(tmp_path)

    assert report["status"] == "fail"
    assert "mojibake_pattern" in {issue["code"] for issue in report["issues"]}
