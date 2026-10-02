"""End-to-end data ingestion pipeline for MultiCat.

Runs all five steps in sequence for a single command:
  Step 1 (optional): Scopus DOI search     -- fetch_dois_scopus
  Step 2: XML download                     -- batch_fetch_xml_cli
  Step 3: Text packaging                   -- batch_package_cli
  Step 4: LLM pipeline                     -- run_pipeline_cli
  Step 5: Print summary stats

Usage examples
--------------
# Full run: search + download + package + pipeline
python -m multicat.ingest_cli --profile c5_sugar --limit 100

# Skip DOI fetch (re-process existing pending XMLs)
python -m multicat.ingest_cli --skip-doi-fetch

# Only fetch DOIs + download XML, no LLM (dry-run cost check)
python -m multicat.ingest_cli --profile lactic_acid --limit 50 --skip-pipeline

# Custom workers / repair loops
python -m multicat.ingest_cli --profile metal_catalyst --limit 100 --workers 4
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import requests

from multicat.text_acquisition.env_utils import load_dotenv_keys
from multicat.text_acquisition.fetch_dois_scopus import (
    SEARCH_PROFILES,
    append_to_registry,
    build_query,
    deduplicate_against_registry,
    get_next_paper_id,
    load_config,
    load_existing_dois,
    search_scopus,
)
from multicat.text_acquisition.fetch_dois_openalex import search_openalex
from multicat.text_acquisition.fetch_dois_crossref import search_crossref
from multicat.text_acquisition.fetch_dois_semanticscholar import search_semanticscholar
from multicat.text_acquisition.fetch_dois_pmc import search_pmc
from multicat.text_acquisition.xml_downloader import (
    XmlDownloadConfig,
    download_xml_for_doi,
)
from multicat.text_acquisition.package_builder import build_text_package_from_xml
from multicat.text_acquisition.asset_writer import write_text_package_assets
from multicat.pipeline.run_pipeline_cli import run_pipeline

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_COLUMNS = [
    "paper_id", "doi", "title", "journal", "year", "publisher",
    "xml_url", "xml_source", "xml_status", "md_status", "tables_count",
    "screening_decision", "pipeline_status", "notes",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_registry(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _save_registry(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTRY_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def _section(title: str) -> None:
    print(f"\n{'='*60}", flush=True)
    print(f"  {title}", flush=True)
    print(f"{'='*60}", flush=True)


# ---------------------------------------------------------------------------
# Step 1: Scopus DOI fetch
# ---------------------------------------------------------------------------

def step_doi_fetch(
    registry_path: Path,
    config: dict,
    profile: str | None,
    limit: int,
    dedup_registry_path: Path | None = None,
    source: str = "scopus",
) -> list[str]:
    """Search Scopus or OpenAlex and append new DOIs to registry.

    dedup_registry_path: additional source for deduplication (the main registry), so that separate registry batches are not downloaded twice.
    source: 'scopus' or 'openalex'
    """
    _section(f"Step 1: DOI Search ({source})")

    existing_dois = load_existing_dois(registry_path)
    if dedup_registry_path and dedup_registry_path != registry_path:
        existing_dois |= load_existing_dois(dedup_registry_path)
    next_id = get_next_paper_id(registry_path)
    print(f"Existing DOIs in registry: {len(existing_dois)}")
    print(f"Source: {source}, Profile: {profile or 'default'}, limit: {limit or 'unlimited'}")

    if source == "all":
        # Merge several sources (Scopus, OpenAlex, CrossRef, plus Semantic Scholar and PMC), deduplicated
        seen: set[str] = set()
        results = []
        query = build_query(config, profile=profile)
        for r in search_scopus(config, query, limit):
            d = r["doi"].strip().lower()
            if d not in seen:
                seen.add(d)
                results.append(r)
        for r in search_openalex(profile or "default", limit):
            d = r["doi"].strip().lower()
            if d not in seen:
                seen.add(d)
                results.append(r)
        for r in search_crossref(profile or "default", limit):
            d = r["doi"].strip().lower()
            if d not in seen:
                seen.add(d)
                results.append(r)
        try:
            for r in search_semanticscholar(profile or "default", limit):
                d = r["doi"].strip().lower()
                if d not in seen:
                    seen.add(d)
                    results.append(r)
        except Exception as exc:
            print(f"  Semantic Scholar skipped ({exc})")
        pmc_dois: set[str] = set()
        try:
            for r in search_pmc(profile or "default", limit):
                d = r["doi"].strip().lower()
                if d not in seen:
                    seen.add(d)
                    results.append(r)
                pmc_dois.add(d)
        except Exception as exc:
            print(f"  PMC skipped ({exc})")
        print(f"  {len(results)} papers after merging five sources (deduplicated)")
    elif source == "openalex":
        results = search_openalex(profile or "default", limit)
    elif source == "crossref":
        results = search_crossref(profile or "default", limit)
    elif source == "pmc":
        pmc_dois: set[str] = set()
        results = search_pmc(profile or "default", limit)
        for r in results:
            pmc_dois.add(r["doi"].strip().lower())
    else:
        query = build_query(config, profile=profile)
        results = search_scopus(config, query, limit)
    new_results = deduplicate_against_registry(results, existing_dois)
    print(f"New (not in registry): {len(new_results)}")

    # Prefilter: keep only Elsevier and PMC OA; papers found directly in PMC are known to have full text and skip the prefix filter
    _DOWNLOADABLE_PREFIXES = (
        "10.1016/",   # Elsevier TDM API (main source)
        "10.1186/",   # BioMed Central (indexed in PMC)
        "10.3389/",   # Frontiers (indexed in PMC)
        "10.1371/",   # PLOS (indexed in PMC)
        "10.3390/",   # MDPI (indexed in PMC)
        "10.1155/",   # Hindawi (indexed in PMC)
        "10.1038/",   # Nature (partly indexed in PMC)
    )
    # pmc_dois is only filled when source == "all"; it is an empty set for other sources
    _pmc_dois = locals().get("pmc_dois", set())
    before = len(new_results)
    new_results = [
        r for r in new_results
        if r["doi"].lower().startswith(_DOWNLOADABLE_PREFIXES)
        or r["doi"].strip().lower() in _pmc_dois
    ]
    print(f"After publisher filter (Elsevier/PMC-OA + PMC direct): {len(new_results)} / {before}")

    if not new_results:
        print("Nothing new to add.")
        return []

    notes = f"scopus_search:{profile}" if profile else "scopus_search"
    records = []
    new_ids = []
    for rec in new_results:
        paper_id = f"P{next_id:06d}"
        records.append({
            "paper_id": paper_id, "doi": rec["doi"], "title": rec["title"],
            "journal": rec["journal"], "year": rec["year"], "publisher": "",
            "xml_url": "", "xml_source": "", "xml_status": "", "md_status": "",
            "tables_count": "", "screening_decision": "", "pipeline_status": "",
            "notes": notes,
        })
        new_ids.append(paper_id)
        next_id += 1

    append_to_registry(registry_path, records)
    print(f"Written {len(records)} new records to registry.")
    return new_ids


# ---------------------------------------------------------------------------
# Step 2: XML download
# ---------------------------------------------------------------------------

def step_xml_download(
    registry_path: Path,
    papers_root: Path,
    xml_config: XmlDownloadConfig,
    target_ids: list[str] | None,
    delay: float = 1.0,
) -> tuple[list[str], list[str]]:
    """Download XML for pending papers. Returns (success_ids, fail_ids)."""
    _section("Step 2: XML Download")

    rows = _load_registry(registry_path)
    row_map = {r["paper_id"]: r for r in rows}

    if target_ids is not None:
        pending = [r for r in rows if r["paper_id"] in set(target_ids) and r.get("xml_status", "") == ""]
    else:
        pending = [r for r in rows if r.get("xml_status", "") == ""]

    print(f"Pending XML downloads: {len(pending)}")
    if not pending:
        print("Nothing to download.")
        return [], []

    success_ids: list[str] = []
    fail_ids: list[str] = []

    for i, row in enumerate(pending, 1):
        paper_id = row["paper_id"]
        doi = row["doi"]
        print(f"[{i}/{len(pending)}] {paper_id} {doi}", flush=True)

        try:
            result = download_xml_for_doi(doi, xml_config, requests)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            row_map[paper_id]["xml_status"] = "error"
            fail_ids.append(paper_id)
            _save_registry(registry_path, list(row_map.values()))
            time.sleep(delay)
            continue

        if result.success:
            paper_dir = papers_root / paper_id
            paper_dir.mkdir(parents=True, exist_ok=True)
            (paper_dir / "01_paper.xml").write_text(result.xml_text, encoding="utf-8")
            row_map[paper_id]["xml_status"] = "success"
            row_map[paper_id]["xml_source"] = result.source
            print(f"  OK source={result.source}")
            success_ids.append(paper_id)
        else:
            row_map[paper_id]["xml_status"] = "fail"
            row_map[paper_id]["xml_source"] = "none"
            print(f"  FAIL error={result.error}")
            fail_ids.append(paper_id)

        _save_registry(registry_path, list(row_map.values()))
        time.sleep(delay)

    print(f"XML download done. success={len(success_ids)} fail={len(fail_ids)}")
    return success_ids, fail_ids


# ---------------------------------------------------------------------------
# Step 3: Text packaging
# ---------------------------------------------------------------------------

def step_package(
    registry_path: Path,
    papers_root: Path,
    target_ids: list[str] | None,
) -> list[str]:
    """Build text packages for papers with XML but no package. Returns packaged_ids."""
    _section("Step 3: Text Packaging")

    rows = _load_registry(registry_path)
    row_map = {r["paper_id"]: r for r in rows}

    if target_ids is not None:
        candidates = [papers_root / pid for pid in target_ids]
    else:
        candidates = sorted(p for p in papers_root.iterdir() if p.is_dir())

    to_process = [
        p for p in candidates
        if p.is_dir()
        and (p / "01_paper.xml").exists()
        and not (p / "03_text_package.json").exists()
    ]

    print(f"Papers to package: {len(to_process)}")
    if not to_process:
        print("Nothing to package.")
        return []

    packaged_ids: list[str] = []
    fail_count = 0

    for i, paper_dir in enumerate(to_process, 1):
        paper_id = paper_dir.name
        reg = row_map.get(paper_id, {})
        print(f"[{i}/{len(to_process)}] {paper_id}", flush=True)
        try:
            xml_text = (paper_dir / "01_paper.xml").read_text(encoding="utf-8")
            metadata = {
                "paper_id": paper_id,
                "doi": reg.get("doi", ""),
                "title": reg.get("title", ""),
                "journal": reg.get("journal", ""),
                "year": reg.get("year", ""),
            }
            package = build_text_package_from_xml(paper_id, metadata, xml_text)
            assets = write_text_package_assets(package, paper_dir)
            tables_count = len(assets["table_paths"])
            print(f"  OK tables={tables_count} sections={len(package.get('sections', []))}")
            if paper_id in row_map:
                row_map[paper_id]["md_status"] = "success"
                row_map[paper_id]["tables_count"] = str(tables_count)
                _save_registry(registry_path, list(row_map.values()))
            packaged_ids.append(paper_id)
        except Exception as exc:
            print(f"  FAIL {exc}")
            fail_count += 1

    print(f"Packaging done. success={len(packaged_ids)} fail={fail_count}")
    return packaged_ids


# ---------------------------------------------------------------------------
# Step 4: LLM pipeline
# ---------------------------------------------------------------------------

def step_pipeline(
    papers_root: Path,
    output_root: Path,
    target_ids: list[str] | None,
    workers: int,
    max_repair_loops: int,
    extraction_mode: str,
    paper_timeout_seconds: float,
    skip_existing_pass: bool = True,
) -> None:
    """Run screening → extraction → validate → repair → judge."""
    _section("Step 4: LLM Pipeline (Screening → Extraction → Validate → Repair → Judge)")

    result = run_pipeline(
        project_root=PROJECT_ROOT,
        papers_root=papers_root,
        output_root=output_root,
        paper_ids=target_ids,
        max_repair_loops=max_repair_loops,
        skip_existing_pass=skip_existing_pass,
        extraction_mode=extraction_mode,
        workers=workers,
        paper_timeout_seconds=paper_timeout_seconds,
    )

    print(f"\nPipeline result:")
    print(f"  accepted:   {len(result.accepted)}")
    print(f"  rejected:   {len(result.rejected)}")
    print(f"  incomplete: {len(result.incomplete)}")


# ---------------------------------------------------------------------------
# Step 5: Summary
# ---------------------------------------------------------------------------

def step_summary(papers_root: Path) -> None:
    _section("Step 5: Dataset Summary")

    from collections import Counter
    dirs = [p for p in papers_root.iterdir() if p.is_dir()]

    xml_n      = sum(1 for d in dirs if (d / "01_paper.xml").exists())
    packaged_n = sum(1 for d in dirs if (d / "03_text_package.json").exists())
    judged_n   = sum(1 for d in dirs if (d / "09_judge.json").exists())

    judge_status: Counter = Counter()
    substrate_count: Counter = Counter()
    product_count: Counter = Counter()

    for d in dirs:
        j = d / "09_judge.json"
        if not j.exists():
            continue
        jdata = json.loads(j.read_text(encoding="utf-8"))
        status = jdata.get("status", "")
        judge_status[status] += 1

        if status != "pass":
            continue
        ext = d / "07_extraction.json"
        if not ext.exists():
            continue
        edata = json.loads(ext.read_text(encoding="utf-8"))
        for rxn in edata.get("reactions", []):
            sub = rxn.get("substrate", {})
            if isinstance(sub, dict):
                sc = sub.get("substrate_class", "")
                if sc:
                    substrate_count[sc] += 1
            for metric in rxn.get("performance_metrics", []):
                if not isinstance(metric, dict):
                    continue
                if metric.get("metric_name") == "yield":
                    prod = metric.get("product_name", "")
                    if prod and prod != "none":
                        product_count[prod] += 1

    total_rxn = sum(substrate_count.values())
    accepted_papers = judge_status.get("pass", 0)

    print(f"Papers:   XML={xml_n}  packaged={packaged_n}  judged={judged_n}")
    print(f"Accepted: {accepted_papers} papers, {total_rxn} reaction rows")
    print(f"\nSubstrate distribution:")
    for k, v in substrate_count.most_common():
        print(f"  {k}: {v}")
    print(f"\nProduct distribution (by yield rows):")
    for k, v in product_count.most_common():
        print(f"  {k}: {v}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end ingestion: Scopus → XML → Package → Pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    # Step 1 options
    parser.add_argument(
        "--profile",
        choices=sorted(SEARCH_PROFILES.keys()),
        default=None,
        help="Scopus search profile (bimetallic / c5_sugar / lactic_acid / metal_catalyst / levulinic_acid). "
             "Omit for default config.yaml query.",
    )
    parser.add_argument(
        "--limit", type=int, default=100,
        help="Max Scopus results to fetch (0=unlimited, default=100).",
    )
    parser.add_argument(
        "--source", choices=["scopus", "openalex", "crossref", "all", "pmc"], default="scopus",
        help="DOI search source; all = merge several databases with deduplication (default=scopus).",
    )
    parser.add_argument(
        "--skip-doi-fetch", action="store_true",
        help="Skip Step 1 (DOI search). Process existing pending entries only.",
    )
    parser.add_argument(
        "--skip-pipeline", action="store_true",
        help="Skip Step 4 (LLM pipeline). Only fetch DOIs + download + package.",
    )
    # Step 4 options
    parser.add_argument("--workers", type=int, default=3,
                        help="Parallel workers for LLM pipeline (default=3).")
    parser.add_argument("--max-repair-loops", type=int, default=2,
                        help="Max repair attempts per paper (default=2).")
    parser.add_argument("--extraction-mode", choices=["full", "ml_core"], default="ml_core",
                        help="Extraction mode (default=ml_core).")
    parser.add_argument("--paper-timeout-seconds", type=float, default=1800,
                        help="Per-paper LLM timeout in seconds (default=1800).")
    # Paths
    parser.add_argument("--registry-path", default="registry/paper_registry.csv")
    parser.add_argument("--papers-root", default="papers")
    parser.add_argument("--output-root", default="outputs")
    parser.add_argument("--download-delay", type=float, default=1.0,
                        help="Seconds between XML download requests (default=1.0).")
    args = parser.parse_args()

    # Setup
    load_dotenv_keys(PROJECT_ROOT)
    config = load_config(PROJECT_ROOT)
    registry_path = PROJECT_ROOT / args.registry_path
    papers_root = PROJECT_ROOT / args.papers_root
    output_root = PROJECT_ROOT / args.output_root

    xml_config = XmlDownloadConfig(
        elsevier_api_key=os.environ.get("ELSEVIER_API_KEY", ""),
        springer_api_key=os.environ.get("SPRINGER_OPENACCESS_API_KEY", "")
        or os.environ.get("SPRINGER_API_KEY", ""),
    )

    print(f"MultiCat — Ingest CLI")
    print(f"Profile:  {args.profile or 'default'}")
    print(f"Registry: {registry_path}")
    print(f"Papers:   {papers_root}")

    # Step 1: DOI fetch
    main_registry_path = PROJECT_ROOT / "registry" / "paper_registry.csv"
    new_ids: list[str] | None = None
    if not args.skip_doi_fetch:
        new_ids = step_doi_fetch(
            registry_path, config, args.profile, args.limit,
            dedup_registry_path=main_registry_path if registry_path != main_registry_path else None,
            source=args.source,
        )
    else:
        print("\n[Step 1 skipped: --skip-doi-fetch]")

    # Step 2: XML download (only newly fetched IDs, or all pending if skipped step 1)
    success_ids, _ = step_xml_download(
        registry_path, papers_root, xml_config,
        target_ids=new_ids,  # None = all pending
        delay=args.download_delay,
    )

    # Step 3: Text packaging (only newly downloaded)
    packaged_ids = step_package(
        registry_path, papers_root,
        target_ids=success_ids if success_ids else None,
    )

    # Step 4: LLM pipeline
    if args.skip_pipeline:
        print("\n[Step 4 skipped: --skip-pipeline]")
    elif not packaged_ids and new_ids is not None:
        # new_ids is not None means Step 1 ran but produced nothing new,
        # so there is no new batch to process -- skip pipeline to avoid
        # accidentally processing all historical backlog papers.
        print("\n[Step 4 skipped: no new papers packaged in this run]")
    else:
        # First run the new batch only
        if packaged_ids:
            step_pipeline(
                papers_root, output_root,
                target_ids=packaged_ids,
                workers=args.workers,
                max_repair_loops=args.max_repair_loops,
                extraction_mode=args.extraction_mode,
                paper_timeout_seconds=args.paper_timeout_seconds,
            )
        # Backlog sweep removed: earlier backlog papers have already been screened or failed XML download,
        # so rerunning them would only consume tokens without new results.

    # Step 5: Summary
    step_summary(papers_root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
