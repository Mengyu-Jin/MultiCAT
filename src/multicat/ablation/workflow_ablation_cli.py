from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Protocol

from multicat.agents.run_agent_cli import run_agent
from multicat.pipeline.run_pipeline_cli import DefaultPipelineRunner

from .audit_judge import audit_report_is_complete, audit_variant_paper
from .build_ablation_tables import build_quality_summary
from .variant_runner import (
    ABLATION_VARIANTS,
    create_variant_workspaces,
    run_variant,
    select_stratified_papers,
    select_stratified_papers_by_quotas,
)


PRODUCT_COLUMNS = (
    "hmf_yield",
    "furfural_yield",
    "levulinic_acid_yield",
    "formic_acid_yield",
    "lactic_acid_yield",
    "acetic_acid_yield",
)

FIFTY_PAPER_PRODUCT_QUOTAS = {
    "hmf_yield": 8,
    "furfural_yield": 8,
    "levulinic_acid_yield": 8,
    "formic_acid_yield": 8,
    "lactic_acid_yield": 9,
    "acetic_acid_yield": 9,
}


class ExtractionRunner(Protocol):
    def run_agent(self, kind: str, paper_dir: Path, project_root: Path) -> dict: ...


def variant_is_complete(output_root: Path, variant: str, paper_id: str) -> bool:
    return (
        output_root / "variants" / variant / "results" / f"{paper_id}.json"
    ).exists() and (
        output_root / "variants" / variant / "papers" / paper_id / "07_extraction.json"
    ).exists()


def prepare_raw_extraction(
    *,
    source_paper_dir: Path,
    output_root: Path,
    project_root: Path,
    runner: ExtractionRunner,
) -> Path:
    """Run Extraction once in staging and preserve the result as raw input."""
    paper_id = source_paper_dir.name
    raw_dir = output_root / "raw_extraction" / paper_id
    if (raw_dir / "07_extraction.json").exists():
        return raw_dir
    staging_dir = output_root / "staging" / paper_id
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)
    for filename in ("03_text_package.json", "05_agent_input.md", "06_screening.json"):
        source = source_paper_dir / filename
        if source.exists():
            shutil.copy2(source, staging_dir / filename)
    runner.run_agent("extraction", staging_dir, project_root)

    if raw_dir.exists():
        shutil.rmtree(raw_dir)
    shutil.copytree(staging_dir, raw_dir)
    shutil.rmtree(staging_dir)
    return raw_dir


def run_ablation(
    *,
    project_root: Path,
    paper_ids: list[str],
    output_root: Path,
    max_repair_loops: int = 2,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    extraction_runner = DefaultPipelineRunner(output_root=output_root)
    for paper_id in paper_ids:
        source_dir = project_root / "papers" / paper_id
        raw_dir = prepare_raw_extraction(
            source_paper_dir=source_dir,
            output_root=output_root,
            project_root=project_root,
            runner=extraction_runner,
        )
        workspaces = create_variant_workspaces(raw_dir, output_root)
        for variant, paper_dir in workspaces.items():
            if variant_is_complete(output_root, variant, paper_id):
                continue
            runner = DefaultPipelineRunner(output_root=output_root / "variants" / variant)
            result = run_variant(
                variant=variant,
                paper_dir=paper_dir,
                project_root=project_root,
                runner=runner,
                max_repair_loops=max_repair_loops,
            )
            result_path = output_root / "variants" / variant / "results" / f"{paper_id}.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(result.__dict__, indent=2), encoding="utf-8")

    audit_runner = DefaultPipelineRunner(output_root=output_root / "audit")
    for variant in ABLATION_VARIANTS:
        for paper_id in paper_ids:
            if audit_report_is_complete(output_root, variant, paper_id):
                continue
            audit_variant_paper(
                variant=variant,
                variant_paper_dir=output_root / "variants" / variant / "papers" / paper_id,
                output_root=output_root,
                project_root=project_root,
                runner=audit_runner,
            )
    build_quality_summary(
        output_root,
        output_root / "tables" / "quality_summary.csv",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run four-branch workflow ablation.")
    parser.add_argument("--papers-per-product", type=int, default=2)
    parser.add_argument("--target-total", type=int, choices=(50,))
    parser.add_argument("--output-root", default="outputs/workflow_ablation_v1")
    parser.add_argument("--max-repair-loops", type=int, default=2)
    args = parser.parse_args()
    project_root = Path.cwd()
    reaction_table = project_root / "outputs" / "reaction_audit_table_v1.csv"
    if args.target_total == 50:
        paper_ids = select_stratified_papers_by_quotas(
            reaction_table,
            product_quotas=FIFTY_PAPER_PRODUCT_QUOTAS,
        )
    else:
        paper_ids = select_stratified_papers(
            reaction_table,
            product_columns=PRODUCT_COLUMNS,
            papers_per_product=args.papers_per_product,
        )
    (project_root / args.output_root / "sample_manifest.json").parent.mkdir(
        parents=True, exist_ok=True
    )
    (project_root / args.output_root / "sample_manifest.json").write_text(
        json.dumps(
            {
                "paper_ids": paper_ids,
                "product_columns": PRODUCT_COLUMNS,
                "product_quotas": FIFTY_PAPER_PRODUCT_QUOTAS if args.target_total == 50 else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    run_ablation(
        project_root=project_root,
        paper_ids=paper_ids,
        output_root=project_root / args.output_root,
        max_repair_loops=args.max_repair_loops,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
