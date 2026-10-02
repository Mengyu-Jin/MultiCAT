from __future__ import annotations

import argparse
from pathlib import Path

from multicat.database_builder.reaction_table_builder_v1 import write_v1_tables


def build_v1_csvs(papers_root: Path, output_root: Path) -> tuple[Path, Path]:
    return write_v1_tables(papers_root, output_root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build v1 audit and ML-ready reaction tables.")
    parser.add_argument("--papers-root", default="papers")
    parser.add_argument("--output-root", default="outputs")
    args = parser.parse_args()

    audit_path, ml_path = build_v1_csvs(Path(args.papers_root), Path(args.output_root))
    print(f"audit_table={audit_path}")
    print(f"ml_ready_table={ml_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
