REGISTRY_COLUMNS = [
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


def make_registry_row(**values):
    row = {column: "" for column in REGISTRY_COLUMNS}
    row.update(
        {
            "xml_status": "pending",
            "md_status": "pending",
            "tables_count": "0",
            "screening_decision": "pending",
            "pipeline_status": "registered",
        }
    )
    for key, value in values.items():
        if key not in row:
            raise KeyError(f"Unknown registry column: {key}")
        row[key] = value
    return row
