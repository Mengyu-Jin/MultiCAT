from __future__ import annotations

import argparse
from pathlib import Path

from multicat.validator.extraction_validator import validate_extraction_file


def run_validation(paper_id: str, papers_root: Path) -> dict:
    return validate_extraction_file(papers_root / paper_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one Extraction Agent output.")
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--papers-root", default="papers")
    args = parser.parse_args()

    report = run_validation(args.paper_id, Path(args.papers_root))
    print(
        f"validation_status={report['status']} "
        f"issues={len(report['issues'])} "
        f"path={Path(args.papers_root) / args.paper_id / '08_validation.json'}"
    )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
