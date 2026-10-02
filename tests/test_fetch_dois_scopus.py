from __future__ import annotations

import csv
from pathlib import Path

from multicat.text_acquisition.fetch_dois_scopus import (
    SEARCH_PROFILES,
    append_to_registry,
    build_query,
    deduplicate_against_registry,
    get_next_paper_id,
    load_existing_dois,
)


def _config() -> dict:
    return {
        "scopus": {
            "query_substrate": "glucose OR fructose",
            "query_catalyst": "zeolite OR \"metal oxide\"",
            "query_product": "HMF OR furfural",
            "query_experimental": "conversion OR yield",
            "query_exclude_fermentation": "fermentation OR enzymatic",
            "query_exclude_polyol": "glycerol OR sorbitol",
            "query_exclude_downstream": "hydrogenation OR FDCA",
            "query_exclude_other_energy": "electrocatalysis OR battery",
            "query_exclude_thermochemical": "pyrolysis OR gasification",
            "query_exclude_review": '"review" OR "survey"',
        }
    }


def test_build_query_includes_substrate_catalyst_product_and_experimental_terms():
    query = build_query(_config())

    assert "TITLE-ABS-KEY(glucose OR fructose)" in query
    assert 'TITLE-ABS-KEY(zeolite OR "metal oxide")' in query
    assert "TITLE-ABS-KEY(HMF OR furfural)" in query
    assert "TITLE-ABS-KEY(conversion OR yield)" in query


def test_build_query_excludes_fermentation_polyol_downstream_other_energy_and_thermochemical():
    """Regression test: the query must exclude the same scope-violating
    categories as the Screening Agent skip conditions, including the
    thermochemical exclusion added 2026-06-16 after P000014 (flash
    pyrolysis paper) slipped through the old Screening Agent.
    """
    query = build_query(_config())

    assert "AND NOT TITLE-ABS-KEY(fermentation OR enzymatic)" in query
    assert "AND NOT TITLE-ABS-KEY(glycerol OR sorbitol)" in query
    assert "AND NOT TITLE-ABS-KEY(hydrogenation OR FDCA)" in query
    assert "AND NOT TITLE-ABS-KEY(electrocatalysis OR battery)" in query
    assert "AND NOT TITLE-ABS-KEY(pyrolysis OR gasification)" in query
    assert "AND NOT TITLE(\"review\" OR \"survey\")" in query


def test_build_query_has_no_year_limit_and_keeps_article_doctype():
    query = build_query(_config())

    assert "PUBYEAR" not in query
    assert "AND DOCTYPE(ar)" in query


def test_all_search_profiles_have_no_year_limit():
    for profile in SEARCH_PROFILES:
        query = build_query(_config(), profile=profile)
        assert "PUBYEAR" not in query, profile
        assert "AND DOCTYPE(ar)" in query, profile


def test_load_existing_dois_returns_empty_set_when_registry_missing(tmp_path: Path):
    assert load_existing_dois(tmp_path / "missing.csv") == set()


def test_load_existing_dois_is_case_insensitive(tmp_path: Path):
    registry_path = tmp_path / "paper_registry.csv"
    registry_path.write_text(
        "paper_id,doi,title,journal,year,publisher,xml_url,xml_source,xml_status,"
        "md_status,tables_count,screening_decision,pipeline_status,notes\n"
        "P000001,10.1000/ABC,Title,Journal,2020,,,,,,,,,,\n",
        encoding="utf-8",
    )

    existing = load_existing_dois(registry_path)

    assert "10.1000/abc" in existing


def test_get_next_paper_id_increments_from_max_existing_id(tmp_path: Path):
    registry_path = tmp_path / "paper_registry.csv"
    registry_path.write_text(
        "paper_id,doi,title,journal,year,publisher,xml_url,xml_source,xml_status,"
        "md_status,tables_count,screening_decision,pipeline_status,notes\n"
        "P000003,10.1/a,t,j,2020,,,,,,,,,\n"
        "P000007,10.1/b,t,j,2020,,,,,,,,,\n",
        encoding="utf-8",
    )

    assert get_next_paper_id(registry_path) == 8


def test_get_next_paper_id_starts_at_one_when_registry_missing(tmp_path: Path):
    assert get_next_paper_id(tmp_path / "missing.csv") == 1


def test_append_to_registry_preserves_existing_14_column_header(tmp_path: Path):
    """Regression test: paper_registry.csv has 14 columns with no
    abstract/oa_status fields (unlike the Battery project's registry).
    Newly appended rows must match this exact column count/order so old
    and new rows stay aligned when read back with csv.DictReader.
    """
    registry_path = tmp_path / "paper_registry.csv"
    registry_path.write_text(
        "paper_id,doi,title,journal,year,publisher,xml_url,xml_source,xml_status,"
        "md_status,tables_count,screening_decision,pipeline_status,notes\n"
        "P000001,10.1/a,Old Title,Old Journal,2020,Elsevier,,elsevier,success,success,2,keep,text_packaged,old\n",
        encoding="utf-8",
    )

    append_to_registry(
        registry_path,
        [
            {
                "paper_id": "P000002",
                "doi": "10.1/b",
                "title": "New Title",
                "journal": "New Journal",
                "year": "2024",
                "publisher": "",
                "xml_url": "",
                "xml_source": "",
                "xml_status": "",
                "md_status": "",
                "tables_count": "",
                "screening_decision": "",
                "pipeline_status": "",
                "notes": "scopus_search",
            }
        ],
    )

    with registry_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert list(rows[0].keys()) == [
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
    assert rows[0]["title"] == "Old Title"
    assert rows[1]["paper_id"] == "P000002"
    assert rows[1]["doi"] == "10.1/b"
    assert rows[1]["notes"] == "scopus_search"


def test_append_to_registry_creates_file_with_header_when_missing(tmp_path: Path):
    registry_path = tmp_path / "paper_registry.csv"

    append_to_registry(
        registry_path,
        [
            {
                "paper_id": "P000001",
                "doi": "10.1/a",
                "title": "T",
                "journal": "J",
                "year": "2024",
                "publisher": "",
                "xml_url": "",
                "xml_source": "",
                "xml_status": "",
                "md_status": "",
                "tables_count": "",
                "screening_decision": "",
                "pipeline_status": "",
                "notes": "scopus_search",
            }
        ],
    )

    with registry_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["paper_id"] == "P000001"


def test_deduplicate_against_registry_drops_dois_already_in_registry():
    results = [
        {"doi": "10.1/a", "title": "A", "journal": "J", "year": "2020"},
        {"doi": "10.1/b", "title": "B", "journal": "J", "year": "2021"},
    ]
    existing = {"10.1/a"}

    new_results = deduplicate_against_registry(results, existing)

    assert [r["doi"] for r in new_results] == ["10.1/b"]


def test_deduplicate_against_registry_drops_duplicates_within_the_same_batch():
    """Regression test: Scopus pagination returned the same DOI twice within
    one search call (observed in practice with
    10.1016/j.chemosphere.2023.140126), which produced two separate
    paper_registry.csv rows (P000044 and P000045) for the identical paper.
    Deduplication must catch repeats within a single batch of results, not
    just DOIs that were already present in the registry before this run.
    """
    results = [
        {"doi": "10.1016/j.chemosphere.2023.140126", "title": "X", "journal": "J", "year": "2023"},
        {"doi": "10.1016/j.chemosphere.2023.140126", "title": "X", "journal": "J", "year": "2023"},
        {"doi": "10.1/other", "title": "Y", "journal": "J", "year": "2024"},
    ]
    existing: set[str] = set()

    new_results = deduplicate_against_registry(results, existing)

    assert len(new_results) == 2
    assert [r["doi"] for r in new_results] == [
        "10.1016/j.chemosphere.2023.140126",
        "10.1/other",
    ]



def test_deduplicate_against_registry_is_case_insensitive():
    results = [
        {"doi": "10.1/ABC", "title": "A", "journal": "J", "year": "2020"},
    ]
    existing = {"10.1/abc"}

    new_results = deduplicate_against_registry(results, existing)

    assert new_results == []
