from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class AblationVariant:
    use_validation: bool
    use_repair: bool
    use_judge: bool


@dataclass(frozen=True)
class VariantResult:
    variant: str
    paper_id: str
    status: str
    validation_status: str | None = None
    judge_status: str | None = None
    repair_attempts: int = 0


class VariantRunner(Protocol):
    def validate(self, paper_dir: Path) -> dict: ...

    def run_agent(self, kind: str, paper_dir: Path, project_root: Path) -> dict: ...


ABLATION_VARIANTS = {
    "full": AblationVariant(True, True, True),
    "no_judge": AblationVariant(True, True, False),
    "no_repair": AblationVariant(True, False, True),
    "extraction_only": AblationVariant(False, False, False),
}

_COMMON_FILES = (
    "03_text_package.json",
    "05_agent_input.md",
    "06_screening.json",
    "07_extraction.json",
)


def create_variant_workspaces(
    source_paper_dir: Path,
    output_root: Path,
) -> dict[str, Path]:
    """Snapshot one extraction and copy the same bytes into all variants."""
    paper_id = source_paper_dir.name
    raw_dir = output_root / "raw_extraction" / paper_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    for filename in _COMMON_FILES:
        source = source_paper_dir / filename
        destination = raw_dir / filename
        if source.exists() and source.resolve() != destination.resolve():
            shutil.copy2(source, destination)

    extraction_snapshot = raw_dir / "07_extraction.json"
    if not extraction_snapshot.exists():
        raise FileNotFoundError(extraction_snapshot)

    workspaces: dict[str, Path] = {}
    for variant in ABLATION_VARIANTS:
        variant_dir = output_root / "variants" / variant / "papers" / paper_id
        variant_dir.mkdir(parents=True, exist_ok=True)
        for filename in _COMMON_FILES:
            source = raw_dir / filename
            destination = variant_dir / filename
            if source.exists() and not destination.exists():
                shutil.copy2(source, destination)
        workspaces[variant] = variant_dir
    return workspaces


def run_variant(
    *,
    variant: str,
    paper_dir: Path,
    project_root: Path,
    runner: VariantRunner,
    max_repair_loops: int = 2,
) -> VariantResult:
    """Execute the enabled quality-control components for one variant."""
    config = ABLATION_VARIANTS[variant]
    validation: dict | None = None
    judge: dict | None = None
    repairs = 0

    if config.use_validation:
        validation = runner.validate(paper_dir)
        while (
            validation.get("status") != "pass"
            and config.use_repair
            and repairs < max_repair_loops
        ):
            try:
                runner.run_agent("repair", paper_dir, project_root)
            except ValueError:
                pass
            repairs += 1
            validation = runner.validate(paper_dir)

    validation_usable = validation is None or validation.get("status") == "pass"
    if config.use_judge and validation_usable:
        judge = runner.run_agent("judge", paper_dir, project_root)
        while judge.get("status") != "pass" and config.use_repair and repairs < max_repair_loops:
            try:
                runner.run_agent("repair", paper_dir, project_root)
            except ValueError:
                pass
            repairs += 1
            if config.use_validation:
                validation = runner.validate(paper_dir)
                if validation.get("status") != "pass":
                    continue
            judge = runner.run_agent("judge", paper_dir, project_root)

    judge_usable = judge is None or judge.get("status") == "pass"
    status = "usable" if validation_usable and judge_usable else "rejected"
    return VariantResult(
        variant=variant,
        paper_id=paper_dir.name,
        status=status,
        validation_status=None if validation is None else validation.get("status"),
        judge_status=None if judge is None else judge.get("status"),
        repair_attempts=repairs,
    )


def select_stratified_papers(
    reaction_table: Path,
    *,
    product_columns: tuple[str, ...],
    papers_per_product: int,
) -> list[str]:
    """Select deterministic, non-overlapping paper IDs for each product."""
    with reaction_table.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    selected: list[str] = []
    used: set[str] = set()
    for product_column in product_columns:
        candidates = sorted(
            {
                row.get("paper_id", "").strip()
                for row in rows
                if row.get("paper_id", "").strip() and row.get(product_column, "").strip()
            }
        )
        chosen = [paper_id for paper_id in candidates if paper_id not in used][
            :papers_per_product
        ]
        selected.extend(chosen)
        used.update(chosen)
    return selected


def select_stratified_papers_by_quotas(
    reaction_table: Path,
    *,
    product_quotas: dict[str, int],
) -> list[str]:
    """Select deterministic, non-overlapping paper IDs using per-product quotas."""
    with reaction_table.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    selected: list[str] = []
    used: set[str] = set()
    for product_column, quota in product_quotas.items():
        candidates = sorted(
            {
                row.get("paper_id", "").strip()
                for row in rows
                if row.get("paper_id", "").strip() and row.get(product_column, "").strip()
            }
        )
        chosen = [paper_id for paper_id in candidates if paper_id not in used][:quota]
        if len(chosen) != quota:
            raise ValueError(
                f"Insufficient distinct papers for {product_column}: "
                f"requested {quota}, found {len(chosen)}."
            )
        selected.extend(chosen)
        used.update(chosen)
    return selected
