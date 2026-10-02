"""Batch text packaging: reads 01_paper.xml for each paper dir that lacks
03_text_package.json, builds the text package, and writes all assets.

Usage:
    python -m multicat.text_acquisition.batch_package_cli
    python -m multicat.text_acquisition.batch_package_cli --paper-ids P000252 P000256
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from multicat.text_acquisition.asset_writer import write_text_package_assets
from multicat.text_acquisition.package_builder import build_text_package_from_xml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_COLUMNS = [
    "paper_id", "doi", "title", "journal", "year", "publisher",
    "xml_url", "xml_source", "xml_status", "md_status", "tables_count",
    "screening_decision", "pipeline_status", "notes",
]


def load_registry(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {r["paper_id"]: r for r in csv.DictReader(f)}


def save_registry(path: Path, row_map: dict[str, dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTRY_COLUMNS)
        w.writeheader()
        w.writerows(row_map.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch text packaging for papers with XML but no text package.")
    parser.add_argument("--papers-root", default="papers")
    parser.add_argument("--registry-path", default="registry/paper_registry.csv")
    parser.add_argument("--paper-ids", nargs="*", default=None, help="Specific paper IDs to process")
    args = parser.parse_args()

    project_root = PROJECT_ROOT
    papers_root = project_root / args.papers_root
    registry_path = project_root / args.registry_path

    row_map = load_registry(registry_path)

    # discover papers to process
    if args.paper_ids:
        candidates = [papers_root / pid for pid in args.paper_ids]
    else:
        candidates = sorted(p for p in papers_root.iterdir() if p.is_dir())

    to_process = [
        p for p in candidates
        if (p / "01_paper.xml").exists() and not (p / "03_text_package.json").exists()
    ]

    print(f"Papers to package: {len(to_process)}")

    success = 0
    fail = 0
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
                save_registry(registry_path, row_map)
            success += 1
        except Exception as exc:
            print(f"  FAIL {exc}")
            fail += 1

    print(f"\nDone. success={success} fail={fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
