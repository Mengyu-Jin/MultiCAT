"""Batch XML downloader: reads paper_registry.csv, downloads XML for all
pending entries (xml_status==''), updates registry in-place.

Usage:
    python -m multicat.text_acquisition.batch_fetch_xml_cli
    python -m multicat.text_acquisition.batch_fetch_xml_cli --profile c5_sugar
    python -m multicat.text_acquisition.batch_fetch_xml_cli --limit 50
"""
from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path

import requests

from multicat.text_acquisition.env_utils import load_dotenv_keys
from multicat.text_acquisition.xml_downloader import (
    XmlDownloadConfig,
    download_xml_for_doi,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_COLUMNS = [
    "paper_id", "doi", "title", "journal", "year", "publisher",
    "xml_url", "xml_source", "xml_status", "md_status", "tables_count",
    "screening_decision", "pipeline_status", "notes",
]


def load_registry(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_registry(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTRY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch download XML for pending registry entries.")
    parser.add_argument("--registry-path", default="registry/paper_registry.csv")
    parser.add_argument("--output-root", default="papers")
    parser.add_argument("--profile", default=None, help="Only process entries with notes matching this profile (e.g. c5_sugar, levulinic_acid)")
    parser.add_argument("--limit", type=int, default=0, help="Max entries to process (0=all pending)")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between requests")
    args = parser.parse_args()

    project_root = PROJECT_ROOT
    load_dotenv_keys(project_root)

    config = XmlDownloadConfig(
        elsevier_api_key=os.environ.get("ELSEVIER_API_KEY", ""),
        springer_api_key=os.environ.get("SPRINGER_OPENACCESS_API_KEY", "")
        or os.environ.get("SPRINGER_API_KEY", ""),
    )

    registry_path = project_root / args.registry_path
    output_root = project_root / args.output_root

    rows = load_registry(registry_path)
    row_map = {r["paper_id"]: r for r in rows}

    # select pending entries
    pending = [r for r in rows if r.get("xml_status", "") == ""]
    if args.profile:
        pending = [r for r in pending if f"scopus_search:{args.profile}" in r.get("notes", "")]
    if args.limit > 0:
        pending = pending[:args.limit]

    print(f"Registry: {registry_path}")
    print(f"Pending XML downloads: {len(pending)}")
    if args.profile:
        print(f"Profile filter: {args.profile}")
    print()

    success = 0
    fail = 0
    for i, row in enumerate(pending, 1):
        paper_id = row["paper_id"]
        doi = row["doi"]
        print(f"[{i}/{len(pending)}] {paper_id} {doi}", flush=True)

        try:
            result = download_xml_for_doi(doi, config, requests)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            row_map[paper_id]["xml_status"] = "error"
            row_map[paper_id]["notes"] = row.get("notes", "") + f" | download_error:{exc}"
            fail += 1
            save_registry(registry_path, list(row_map.values()))
            time.sleep(args.delay)
            continue

        if result.success:
            paper_dir = output_root / paper_id
            paper_dir.mkdir(parents=True, exist_ok=True)
            xml_path = paper_dir / "01_paper.xml"
            xml_path.write_text(result.xml_text, encoding="utf-8")
            row_map[paper_id]["xml_status"] = "success"
            row_map[paper_id]["xml_source"] = result.source
            row_map[paper_id]["xml_url"] = doi
            print(f"  OK source={result.source}")
            success += 1
        else:
            row_map[paper_id]["xml_status"] = "fail"
            row_map[paper_id]["xml_source"] = "none"
            print(f"  FAIL error={result.error}")
            fail += 1

        save_registry(registry_path, list(row_map.values()))
        time.sleep(args.delay)

    print(f"\nDone. success={success} fail={fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
