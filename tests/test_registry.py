from multicat.registry import REGISTRY_COLUMNS, make_registry_row


def test_registry_columns_include_xml_first_status_fields():
    assert REGISTRY_COLUMNS == [
        "paper_id",
        "doi",
        "title",
        "journal",
        "year",
        "publisher",
        "xml_url",
        "xml_source",
        "xml_status",
        "md_status",
        "tables_count",
        "screening_decision",
        "pipeline_status",
        "notes",
    ]


def test_make_registry_row_defaults_to_unprocessed_xml_first_state():
    row = make_registry_row(paper_id="P000001", doi="10.0000/example")

    assert row["paper_id"] == "P000001"
    assert row["doi"] == "10.0000/example"
    assert row["xml_status"] == "pending"
    assert row["md_status"] == "pending"
    assert row["tables_count"] == "0"
    assert row["screening_decision"] == "pending"
    assert row["pipeline_status"] == "registered"
